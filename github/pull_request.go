package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"regexp"
	"strings"

	"github.com/aws/aws-sdk-go/service/sqs"
	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

var (
	TaggerName   = os.Getenv("GIT_TAGGER_NAME")
	TaggerEmail  = os.Getenv("GIT_TAGGER_EMAIL")
	SQSQueueName = os.Getenv("SQS_QUEUE")

	ErrNotMergeEvent  = errors.New("Not a merge event")
	ErrNotRegistrator = errors.New("PR not created by Registrator")
	ErrBaseBranch     = errors.New("Base branch is not the default")
	ErrRepoMatch      = errors.New("No repo regex match")
	ErrVersionMatch   = errors.New("No version regex match")
	ErrCommitMatch    = errors.New("No commit regex match")
	ErrNoAuthHeader   = errors.New("Authentication header was not set")
	ErrBadExistingTag = errors.New("A tag already exists, but it points at the wrong commit")
	ErrNoCommits      = errors.New("No commits were found")
	ErrNotEnoughTags  = errors.New("Not enough tags were found")
	ErrNoVersion      = errors.New("Version was not found in Project.toml")
	ErrReleaseExists  = errors.New("A release for this tag already exists")
	ErrNoSQSClient    = errors.New("SQS client was not initialized")

	RepoRegex         = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	VersionRegex      = regexp.MustCompile(`Version:\s*(v.*)`)
	CommitRegex       = regexp.MustCompile(`Commit:\s*(.*)`)
	ReleaseNotesRegex = regexp.MustCompile(`(?s)<!-- BEGIN (?:PATCH|RELEASE) NOTES -->(.*)<!-- END (?:PATCH|RELEASE) NOTES -->`)
	MergedPRRegex     = regexp.MustCompile(`Merge pull request #(\d+)`)

	SQSQueueURL *string
)

// ReleaseInfo contains the information needed to create a GitHub release.
type ReleaseInfo struct {
	Owner        string
	Name         string
	Version      string
	Commit       string
	ReleaseNotes string
}

// HandlePullRequest handles a pull request event.
func HandlePullRequest(pre *github.PullRequestEvent, id string) error {
	pr := pre.GetPullRequest()

	info := `
Event: PullRequestEvent
PR Action: %s
PR Merged: %t
PR Creator: %s
PR Base: %s
PR Title: %s
PR Body:
-----
%s
-----
`
	fmt.Printf(
		info,
		pre.GetAction(),
		pr.GetMerged(),
		pr.GetUser().GetLogin(),
		pr.GetBase().GetRef(),
		pr.GetTitle(),
		PreprocessBody(pr.GetBody()),
	)

	if err := ShouldRelease(pre); err != nil {
		return errors.Wrap(err, "Validation")
	}

	ri := ParseBody(PreprocessBody(pr.GetBody()))

	client, err := GetInstallationClient(ri.Owner, ri.Name)
	if err != nil {
		if err == ErrRepoNotEnabled {
			MakeErrorComment(pr, id, err)
		}
		return errors.Wrap(err, "Installation client")
	}

	if err := ri.DoRelease(client, pr, id); err != nil {
		return errors.Wrap(err, "Creating release")
	}

	return nil
}

// ShouldRelease determines whether the PR indicates a release.
func ShouldRelease(pre *github.PullRequestEvent) error {
	pr := pre.GetPullRequest()
	u := pr.GetUser()
	body := pr.GetBody()

	if pre.GetAction() != ActionClosed || !pr.GetMerged() {
		return ErrNotMergeEvent
	}

	if u.GetLogin() != RegistratorUsername {
		return ErrNotRegistrator
	}

	if pr.GetBase().GetRef() != pr.GetBase().GetRepo().GetDefaultBranch() {
		return ErrBaseBranch
	}

	if !RepoRegex.MatchString(body) {
		return ErrRepoMatch
	}

	if !VersionRegex.MatchString(body) {
		return ErrVersionMatch
	}

	if !CommitRegex.MatchString(body) {
		return ErrCommitMatch
	}

	return nil
}

// ParseBody parses the PR body and returns a ReleaseInfo.
// The assumption is that the PR body is valid.
func ParseBody(body string) ReleaseInfo {
	match := RepoRegex.FindStringSubmatch(body)
	owner, name := match[1], match[2]

	match = VersionRegex.FindStringSubmatch(body)
	version := match[1]

	match = CommitRegex.FindStringSubmatch(body)
	commit := match[1]

	// This one is optional, and just defaults to no notes.
	match = ReleaseNotesRegex.FindStringSubmatch(body)
	var notes string
	if match != nil {
		notes = strings.TrimSpace(match[1])
		lines := strings.Split(notes, "\n")
		if strings.HasPrefix(lines[0], "> ") {
			for i, l := range lines {
				lines[i] = strings.TrimSpace(l[1:])
			}
			notes = strings.Join(lines, "\n")
		}
	}

	return ReleaseInfo{
		Owner:        owner,
		Name:         name,
		Version:      version,
		Commit:       commit,
		ReleaseNotes: notes,
	}
}

// CreateTag creates and pushes a Git tag.
// We use the Git CLI instead of the GitHub API so that we can use GPG signing.
func (ri ReleaseInfo) CreateTag(auth string) error {
	// Clone the repo to a temp directory that we can write to, using an authenticated URL.
	dir, err := ioutil.TempDir("", "")
	if err != nil {
		return errors.Wrap(err, "Temp dir")
	}
	url := fmt.Sprintf("https://oauth2:%s@github.com/%s/%s", auth, ri.Owner, ri.Name)
	if err = DoCmd("git", "clone", url, dir); err != nil {
		return errors.Wrap(err, "git clone")
	}
	defer os.RemoveAll(dir)

	// Configure Git.
	if err = DoCmd("git", "-C", dir, "config", "user.name", TaggerName); err != nil {
		return errors.Wrap(err, "git config")
	}
	if err := DoCmd("git", "-C", dir, "config", "user.email", TaggerEmail); err != nil {
		return errors.Wrap(err, "git config")
	}

	// Create and push the tag.
	msg := ri.ReleaseNotes
	if msg == "" {
		msg = fmt.Sprintf(
			"See https://github.com/%s/%s/releases/tag/%s for release notes",
			ri.Owner, ri.Name, ri.Version,
		)
	}
	if err = DoCmd("git", "-C", dir, "tag", ri.Version, ri.Commit, "-s", "-m", msg); err != nil {
		return errors.Wrap(err, "git tag")
	}
	if err = DoCmd("git", "-C", dir, "push", "origin", "--tags"); err != nil {
		return errors.Wrap(err, "git push")
	}

	return nil
}

// DoRelease creates the Git tag and GitHub release.
func (ri ReleaseInfo) DoRelease(client *github.Client, pr *github.PullRequest, id string) error {
	// Create a Git tag, only if one doesn't already exist.
	// If a tag already exists, make sure that it points to the right commit.
	ref, resp, err := client.Git.GetRef(Ctx, ri.Owner, ri.Name, "tags/"+ri.Version)

	// We'll need an auth token later so grab one now.
	header := resp.Request.Header.Get("Authorization")
	if header == "" {
		err = ErrNoAuthHeader
		MakeErrorComment(pr, id, err)
		return err
	}
	tokens := strings.Split(header, " ")
	auth := tokens[len(tokens)-1]

	if resp.StatusCode == http.StatusNotFound {
		// No tag exists, so create one.
		if err = ri.CreateTag(auth); err != nil {
			err = errors.Wrap(err, "Creating tag")
			MakeErrorComment(pr, id, err)
			return err
		}
	} else if err != nil {
		// Don't worry about errors, just let GitHub create the tag along with the release.
		fmt.Println("Get ref:", err)
	} else {
		// A tag already exists.
		var sha string
		obj := ref.GetObject()
		switch t := obj.GetType(); t {
		case "commit":
			sha = obj.GetSHA()
		case "tag":
			tag, _, err := client.Git.GetTag(Ctx, ri.Owner, ri.Name, obj.GetSHA())
			if err != nil {
				fmt.Println("Get tag:", err)
			} else {
				sha = tag.GetObject().GetSHA()
			}
		default:
			fmt.Println("Unknown ref type", t)
			sha = obj.GetSHA()
		}

		if sha != ri.Commit {
			// The existing tag is on the wrong commit.
			err = ErrBadExistingTag
			MakeErrorComment(pr, id, err)
			return err
		}
	}

	// GitHub doesn't display the nice "n commits to <branch> since this release"
	// when we use a commit SHA as a release target.
	// If the commit being released is the head commit, we can use the branch name instead.
	target := ri.Commit
	repo, _, err := client.Repositories.Get(Ctx, ri.Owner, ri.Name)
	if err == nil {
		branch, _, err := client.Repositories.GetBranch(Ctx, ri.Owner, ri.Name, repo.GetDefaultBranch())
		if err == nil && branch.GetCommit().GetSHA() == target {
			target = branch.GetName()
		}
	}

	// Create a GitHub release associated with the tag.
	rel := &github.RepositoryRelease{
		TagName:         github.String(ri.Version),
		Name:            github.String(ri.Version),
		TargetCommitish: github.String(target),
	}
	if ri.ReleaseNotes == "" {
		if err := ri.QueueChangelog(auth); err != nil {
			fmt.Println("Changelog request:", err)
		}
	} else {
		rel.Body = github.String(ri.ReleaseNotes)
	}
	if rel, resp, err = client.Repositories.CreateRelease(Ctx, ri.Owner, ri.Name, rel); err != nil {
		// If the release already exists, there's no need to bug the user about it.
		// We know from the checks above that the existing tag is correct.
		if resp.StatusCode == http.StatusUnprocessableEntity {
			return ErrReleaseExists
		}
		err = errors.Wrap(err, "Creating release")
		MakeErrorComment(pr, id, err)
		return err
	}

	MakeSuccessComment(pr, id, rel)
	fmt.Printf("Created release %s for %s/%s at %s\n", ri.Version, ri.Owner, ri.Name, ri.Commit)
	return nil
}

// QueueChangelog queue a changelog request.
func (ri ReleaseInfo) QueueChangelog(auth string) error {
	if SQS == nil {
		return ErrNoSQSClient
	}

	if SQSQueueURL == nil {
		url, err := SQS.GetQueueUrl(&sqs.GetQueueUrlInput{QueueName: &SQSQueueName})
		if err != nil {
			return errors.Wrap(err, "Getting queue URL")
		}
		SQSQueueURL = url.QueueUrl
	}

	b, err := json.Marshal(map[string]string{
		"user": ri.Owner,
		"repo": ri.Name,
		"tag":  ri.Version,
		"auth": auth,
	})
	if err != nil {
		return errors.Wrap(err, "Encoding queue input")
	}
	body := string(b)

	_, err = SQS.SendMessage(&sqs.SendMessageInput{
		QueueUrl:    SQSQueueURL,
		MessageBody: &body,
	})
	if err != nil {
		return errors.Wrap(err, "Sending queue message")
	}

	return nil
}

// MakeSuccessComment adds a comment to the PR indicating success.
func MakeSuccessComment(pr *github.PullRequest, id string, r *github.RepositoryRelease) {
	body := fmt.Sprintf(
		"I've created release `%s`, [here](%s) it is.",
		r.GetTagName(), r.GetHTMLURL(),
	)
	SendComment(pr, id, body)
}

// MakeErrorComment adds a comment to the PR indicating failure.
func MakeErrorComment(pr *github.PullRequest, id string, err error) {
	lines := []string{
		"I tried to create a release but ran into this error:",
		"```\n%v\n```",
		"To retry, comment on this PR with the phrase `%s`.",
		"cc: @%s",
	}
	body := fmt.Sprintf(strings.Join(lines, "\n"), err, CommandTag, ContactUser)
	SendComment(pr, id, body)
}

// SendComment adds a comment to a PR.
func SendComment(pr *github.PullRequest, id, body string) {
	repo := pr.GetBase().GetRepo()
	owner := repo.GetOwner().GetLogin()
	name := repo.GetName()
	num := pr.GetNumber()

	client, err := GetInstallationClient(owner, name)
	if err != nil {
		fmt.Println("Creating comment:", err)
		return
	}

	body += fmt.Sprintf("\n<!-- %s -->", id)
	c := &github.IssueComment{Body: &body}
	if _, _, err := client.Issues.CreateComment(Ctx, owner, name, num, c); err != nil {
		fmt.Println("Creating comment:", err)
	}
}
