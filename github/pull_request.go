package main

import (
	"errors"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"regexp"
	"strings"

	"github.com/google/go-github/v25/github"
)

var (
	ErrNotMergeEvent  = errors.New("Not a merge event")
	ErrNotRegistrator = errors.New("PR not created by Registrator")
	ErrBaseBranch     = errors.New("Base branch is not the default")
	ErrRepoMatch      = errors.New("No repo regex match")
	ErrVersionMatch   = errors.New("No version regex match")
	ErrCommitMatch    = errors.New("No commit regex match")
	ErrNoAuthHeader   = errors.New("Authentication header was not set")

	RepoRegex       = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	VersionRegex    = regexp.MustCompile(`Version:\s*(v.*)`)
	CommitRegex     = regexp.MustCompile(`Commit:\s*(.*)`)
	PatchNotesRegex = regexp.MustCompile(`(?s)<!-- BEGIN PATCH NOTES -->(.*)<!-- END PATCH NOTES -->`)
)

// ReleaseInfo contains the information needed to create a GitHub release.
type ReleaseInfo struct {
	Owner      string
	Name       string
	Version    string
	Commit     string
	PatchNotes string
}

// HandlePullRequest handles a pull request event.
func HandlePullRequest(pre *github.PullRequestEvent, id string) string {
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
		return "Validation: " + err.Error()
	}

	ri := ParseBody(PreprocessBody(pr.GetBody()))

	client, err := GetInstallationClient(ri.Owner, ri.Name)
	if err != nil {
		if err == ErrRepoNotEnabled {
			MakeErrorComment(pr, id, err)
		}
		return "Installation client: " + err.Error()
	}

	if err := ri.DoRelease(client, pr, id); err != nil {
		return "Creating release: " + err.Error()
	}

	return "No error, created release"
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

	if pr.GetBase().GetRef() != RegistryBranch {
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
	match = PatchNotesRegex.FindStringSubmatch(body)
	var notes string
	if match != nil {
		notes = strings.TrimSpace(match[1])
	}

	return ReleaseInfo{
		Owner:      owner,
		Name:       name,
		Version:    version,
		Commit:     commit,
		PatchNotes: notes,
	}
}

// CreateTag creates and pushes a Git tag.
// We use the Git CLI instead of the GitHub API so that we can use GPG signing.
func (ri ReleaseInfo) CreateTag(auth string) error {
	dir, err := ioutil.TempDir("", "")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)

	url := fmt.Sprintf("https://oauth2:%s@github.com/%s/%s", auth, ri.Owner, ri.Name)
	cmd := exec.Command("git", "clone", url, dir)
	if err = cmd.Run(); err != nil {
		return err
	}

	// TODO: GPG stuff (add -s to Git command when ready).
	cmd = exec.Command("git", "-C", dir, "tag", ri.Version, "-m", ri.PatchNotes)
	if err = cmd.Run(); err != nil {
		return err
	}

	cmd = exec.Command("git", "-C", dir, "push", "origin", "--tags")
	if err = cmd.Run(); err != nil {
		return err
	}

	return nil
}

// DoRelease creates the GitHub release.
func (ri ReleaseInfo) DoRelease(client *github.Client, pr *github.PullRequest, id string) error {
	var err error

	// TODO: There is probably a better way to get a token.
	_, resp, _ := client.Users.Get(Ctx, "")
	header := resp.Request.Header.Get("Authorization")
	if header == "" {
		MakeErrorComment(pr, id, ErrNoAuthHeader)
		return ErrNoAuthHeader
	}
	tokens := strings.Split(header, " ")
	auth := tokens[len(tokens)-1]
	if err = ri.CreateTag(auth); err != nil {
		MakeErrorComment(pr, id, err)
		return err
	}

	// Finally, create a GitHub release associated with the tag.
	rel := &github.RepositoryRelease{
		TagName:         github.String(ri.Version),
		Name:            github.String(ri.Version),
		TargetCommitish: github.String(ri.Commit),
		Body:            github.String(ri.PatchNotes),
	}
	if rel, _, err = client.Repositories.CreateRelease(Ctx, ri.Owner, ri.Name, rel); err != nil {
		MakeErrorComment(pr, id, err)
		return err
	}

	MakeSuccessComment(pr, id, rel)
	fmt.Printf("Created release %s for %s/%s at %s\n", ri.Version, ri.Owner, ri.Name, ri.Commit)
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
