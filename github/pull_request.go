package main

import (
	"fmt"
	"io/ioutil"
	"os"
	"regexp"
	"sort"
	"strings"

	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

var (
	TaggerName  = os.Getenv("GIT_TAGGER_NAME")
	TaggerEmail = os.Getenv("GIT_TAGGER_EMAIL")

	ErrNotMergeEvent  = errors.New("Not a merge event")
	ErrNotRegistrator = errors.New("PR not created by Registrator")
	ErrBaseBranch     = errors.New("Base branch is not the default")
	ErrRepoMatch      = errors.New("No repo regex match")
	ErrVersionMatch   = errors.New("No version regex match")
	ErrCommitMatch    = errors.New("No commit regex match")
	ErrNoAuthHeader   = errors.New("Authentication header was not set")
	ErrNoCommits      = errors.New("No commits were found")
	ErrNotEnoughTags  = errors.New("Not enough tags were found")
	ErrNoVersion      = errors.New("Version was not found in Project.toml")

	RepoRegex         = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	VersionRegex      = regexp.MustCompile(`Version:\s*(v.*)`)
	CommitRegex       = regexp.MustCompile(`Commit:\s*(.*)`)
	ReleaseNotesRegex = regexp.MustCompile(`(?s)<!-- BEGIN (?:PATCH|RELEASE) NOTES -->(.*)<!-- END (?:PATCH|RELEASE) NOTES -->`)
	MergedPRRegex     = regexp.MustCompile(`Merge pull request #(\d+)`)
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
	var err error

	// Get an OAuth token to use for the Git remote.
	// TODO: There is probably a better way to get a token.
	_, resp, _ := client.Users.Get(Ctx, "")
	header := resp.Request.Header.Get("Authorization")
	if header == "" {
		MakeErrorComment(pr, id, ErrNoAuthHeader)
		return ErrNoAuthHeader
	}
	tokens := strings.Split(header, " ")
	auth := tokens[len(tokens)-1]

	// Create a Git tag, only if one doesn't already exist.
	// If a tag already exists, then there's a pretty good chance that a GitHub release also exists.
	// However, failing there provides a much more useful error message for users.
	// Also, we only check for 404, not any other request errors.
	// If the request didn't go through for some reason,
	// we can still safely skip tag creation and GitHub will tag for us when we create the release.
	ref := "tags/" + ri.Version
	if _, resp, _ := client.Git.GetRef(Ctx, ri.Owner, ri.Name, ref); resp.StatusCode == 404 {
		if err = ri.CreateTag(auth); err != nil {
			err = errors.Wrap(err, "Creating tag")
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
		body, err := ri.Changelog(client)
		if err == nil {
			rel.Body = github.String(body)
		} else {
			fmt.Println("Changelog:", err)
		}
	} else {
		rel.Body = github.String(ri.ReleaseNotes)
	}
	if rel, _, err = client.Repositories.CreateRelease(Ctx, ri.Owner, ri.Name, rel); err != nil {
		err = errors.Wrap(err, "Creating release")
		MakeErrorComment(pr, id, err)
		return err
	}

	MakeSuccessComment(pr, id, rel)
	fmt.Printf("Created release %s for %s/%s at %s\n", ri.Version, ri.Owner, ri.Name, ri.Commit)
	return nil
}

// Changelog generates a changelog based on commits.
func (ri ReleaseInfo) Changelog(client *github.Client) (string, error) {
	// Collect all the tags.
	opts := &github.ListOptions{}
	tags := []*github.RepositoryTag{}
	for {
		ts, resp, err := client.Repositories.ListTags(Ctx, ri.Owner, ri.Name, opts)
		if err != nil {
			return "", errors.Wrap(err, "List tags")
		}

		for _, t := range ts {
			tags = append(tags, t)
		}

		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}
	if len(tags) == 0 {
		return "", ErrNotEnoughTags
	}

	// Get the highest tag that is not the new release.
	sort.Slice(tags, func(i, j int) bool {
		return tags[i].GetName() < tags[j].GetName()
	})
	lastTag := tags[len(tags)-1]
	if lastTag.GetName() == ri.Version {
		if len(tags) < 2 {
			return "", ErrNotEnoughTags
		}
		lastTag = tags[len(tags)-2]
	}

	// Collect all the commits since the previous tag.
	commits := []*github.RepositoryCommit{}
	cOpts := &github.CommitsListOptions{SHA: ri.Commit}
outer:
	for {
		cs, resp, err := client.Repositories.ListCommits(Ctx, ri.Owner, ri.Name, cOpts)
		if err != nil {
			return "", errors.Wrap(err, "List commits")
		}

		for _, c := range cs {
			if c.GetSHA() == lastTag.GetCommit().GetSHA() {
				break outer
			}
			commits = append(commits, c)
		}

		if resp.NextPage == 0 {
			break
		}
		cOpts.Page = resp.NextPage
	}
	if len(commits) == 0 {
		return "", ErrNoCommits
	}

	// Build up the message.
	sort.Slice(commits, func(i, j int) bool {
		return commits[i].GetCommit().GetMessage() < commits[j].GetCommit().GetMessage()
	})
	body := "**Commits**\n\n"
	prs := []string{}
	for _, c := range commits {
		lines := strings.Split(c.GetCommit().GetMessage(), "\n")
		msg := strings.TrimSpace(lines[0])
		sha := c.GetSHA()[:7]
		if match := MergedPRRegex.FindStringSubmatch(msg); match != nil {
			prs = append(prs, fmt.Sprintf("- #%s (%s)\n", match[1], sha))
		} else {
			body += fmt.Sprintf("- %s (%s)\n", msg, sha)
		}
	}
	if len(prs) > 0 {
		body += "\n**Merged PRs**\n\n"
		for _, pr := range prs {
			body += pr
		}
	}
	body += "\nThis changelog was automatically generated, and might contain inaccuracies."

	return body, nil
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
