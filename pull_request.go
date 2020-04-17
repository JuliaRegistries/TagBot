package main

import (
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/google/go-github/v30/github"
)

const ActionClosed = "closed"

var (
	RegistratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	RepoRegex           = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	VersionRegex        = regexp.MustCompile(`Version:\s*(v.*)`)
	CommitRegex         = regexp.MustCompile(`Commit:\s*(.*)`)
	MergedPRRegex       = regexp.MustCompile(`Merge pull request #(\d+)`)
	ServerMaintainer    = os.Getenv("SERVER_MAINTAINER")
)

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

	if err := shouldRelease(pre); err != nil {
		return fmt.Errorf("Validation: %w", err)
	}

	r := parseBody(PreprocessBody(pr.GetBody()))

	if ok, err := IsActionEnabled(r.User, r.Repo); err != nil {
		if err == ErrNoSpace {
			fmt.Println("No space left on server!")
			MakeErrorComment(pr, id, err)
			return nil
		}
		fmt.Println("Checking for GitHub Action failed:", err)
	} else if ok {
		fmt.Println("TagBot as a GitHub Action is enabled, skipping")
		return nil
	}

	client, err := GetInstallationClient(r.User, r.Repo)
	if err != nil {
		if err == ErrRepoNotEnabled {
			MakeErrorComment(pr, id, err)
		}
		return fmt.Errorf("Installation client: %w", err)
	}

	if err := r.Do(client, pr, id); err != nil {
		return fmt.Errorf("Creating release: %w", err)
	}

	return nil
}

// shouldRelease determines whether the PR indicates a release.
func shouldRelease(pre *github.PullRequestEvent) error {
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

// parseBody parses the PR body and returns a Release.
// The assumption is that the PR body is valid.
func parseBody(body string) Release {
	match := RepoRegex.FindStringSubmatch(body)
	owner, name := match[1], match[2]

	match = VersionRegex.FindStringSubmatch(body)
	version := match[1]

	match = CommitRegex.FindStringSubmatch(body)
	commit := match[1]

	return Release{
		User:    owner,
		Repo:    name,
		Version: version,
		Commit:  commit,
	}
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
	}
	if err == ErrNoSpace && ServerMaintainer != "" {
		lines = append(lines, "cc: @"+ServerMaintainer)
	}
	body := fmt.Sprintf(strings.Join(lines, "\n"), err, CommandTag)
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
