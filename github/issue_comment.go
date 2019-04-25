package main

import (
	"errors"
	"fmt"
	"strings"

	"github.com/google/go-github/github"
)

const TypeBot = "Bot"

var (
	ErrNotNewComment  = errors.New("Not a comment creation event")
	ErrNotPullRequest = errors.New("Comment not on a pull request")
	ErrCommentByBot   = errors.New("Comment is made by a bot")
	ErrNoTrigger      = errors.New("Comment doesn't contain trigger phrase")
)

func HandleIssueComment(ice *github.IssueCommentEvent, id string) string {
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

	if err := IsTriggerComment(ice); err != nil {
		return "Validation: " + err.Error()
	}

	repo := ice.GetRepo()
	owner := repo.GetOwner().GetLogin()
	name := repo.GetName()

	client, err := GetInstallationClient(owner, name)
	if err != nil {
		return "Installation client: " + err.Error()
	}

	pr, _, err := client.PullRequests.Get(Ctx, owner, name, i.GetNumber())
	if err != nil {
		return "Getting PR: " + err.Error()
	}

	fmt.Println("Processing fake PullRequestEvent")
	pre := &github.PullRequestEvent{Action: github.String(ActionClosed), PullRequest: pr}
	return HandlePullRequest(pre, id)
}

// IsTriggerComment determines whether a comment should trigger a release.
func IsTriggerComment(ice *github.IssueCommentEvent) error {
	if ice.GetAction() != ActionCreated {
		return ErrNotNewComment
	}

	if !ice.GetIssue().IsPullRequest() {
		return ErrNotPullRequest
	}

	if ice.GetSender().GetType() == TypeBot {
		return ErrCommentByBot
	}

	if !strings.Contains(ice.GetComment().GetBody(), TriggerPhrase) {
		return ErrNoTrigger
	}

	return nil
}
