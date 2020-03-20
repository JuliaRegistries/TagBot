package main

import (
	"fmt"
	"strings"

	"github.com/google/go-github/v30/github"
)

const (
	ActionCreated = "created"
	CommandPrefix = "TagBot "
	CommandTag    = CommandPrefix + "tag"
	CommandIgnore = CommandPrefix + "ignore"
)

// HandleIssueComment handles issue comment events.
func HandleIssueComment(ice *github.IssueCommentEvent, id string) error {
	i := ice.GetIssue()
	c := ice.GetComment()

	info := `
Event: IssueCommentEvent
Is pull request: %t
Issue: #%d %s
Comment action: %s
Comment author: %s
Comment body:
-----
%s
-----
`
	fmt.Printf(
		info,
		i.IsPullRequest(),
		i.GetNumber(),
		i.GetTitle(),
		ice.GetAction(),
		i.GetUser().GetLogin(),
		PreprocessBody(c.GetBody()),
	)

	if err := isTriggerComment(ice); err != nil {
		return fmt.Errorf("Validation: %w", err)
	}

	repo := ice.GetRepo()
	owner := repo.GetOwner().GetLogin()
	name := repo.GetName()

	client, err := GetInstallationClient(owner, name)
	if err != nil {
		return fmt.Errorf("Installation client: %w", err)
	}

	pr, _, err := client.PullRequests.Get(Ctx, owner, name, i.GetNumber())
	if err != nil {
		return fmt.Errorf("Getting PR: %w", err)
	}

	fmt.Println("Processing fake PullRequestEvent")
	pre := &github.PullRequestEvent{Action: github.String(ActionClosed), PullRequest: pr}
	return HandlePullRequest(pre, id)
}

// isTriggerComment determines whether a comment should trigger a release.
func isTriggerComment(ice *github.IssueCommentEvent) error {
	if ice.GetAction() != ActionCreated {
		return ErrNotNewComment
	}

	if !ice.GetIssue().IsPullRequest() {
		return ErrNotPullRequest
	}

	if ice.GetSender().GetType() == "Bot" {
		return ErrCommentByBot
	}

	body := ice.GetComment().GetBody()

	if strings.Contains(body, CommandIgnore) {
		return ErrIgnored
	}

	if !strings.Contains(ice.GetComment().GetBody(), CommandTag) {
		return ErrNoTrigger
	}

	return nil
}
