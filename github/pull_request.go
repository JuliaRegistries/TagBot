package main

import (
	"errors"
	"fmt"
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

// DoRelease creates the GitHub release.
func (ri ReleaseInfo) DoRelease(client *github.Client, pr *github.PullRequest, id string) error {
	var err error
	obj := &github.GitObject{
		Type: github.String("commit"),
		SHA:  github.String(ri.Commit),
	}

	// First, create the Git tag.
	// FYI: Something, probably on GitHub's end, prevents the message from being applied to the tag.
	// However, whenever it's fixed it should just start to work properly without any intervention.
	tag := &github.Tag{
		Tag:     github.String(ri.Version),
		SHA:     github.String(ri.Commit),
		Message: github.String(ri.PatchNotes),
		Object:  obj,
	}
	if _, _, err = client.Git.CreateTag(Ctx, ri.Owner, ri.Name, tag); err != nil {
		MakeErrorComment(pr, id, err)
		return err
	}

	// Then, create a reference to the tag.
	ref := &github.Reference{
		Ref:    github.String("refs/tags/" + ri.Version),
		Object: obj,
	}
	if _, _, err = client.Git.CreateRef(Ctx, ri.Owner, ri.Name, ref); err != nil {
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
