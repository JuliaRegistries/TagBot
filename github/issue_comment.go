package main

import (
	"fmt"
	"strings"

	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

const (
	CommandIgnore = CommandPrefix + "ignore"
	TypeBot       = "Bot"
)

var (
	ErrNotNewComment  = errors.New("Not a comment creation event")
	ErrNotPullRequest = errors.New("Comment not on a pull request")
	ErrCommentByBot   = errors.New("Comment is made by a bot")
	ErrIgnored        = errors.New("Comment contained ignore command")
	ErrNoTrigger      = errors.New("Comment doesn't contain trigger phrase")
)

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

	if err := IsTriggerComment(ice); err != nil {
		return errors.Wrap(err, "Validation")
	}

	repo := ice.GetRepo()
	owner := repo.GetOwner().GetLogin()
	name := repo.GetName()

	if err := Setup(); err != nil {
		return errors.Wrap(err, "Setup")
	}

	client, err := GetInstallationClient(owner, name)
	if err != nil {
		return errors.Wrap(err, "Installation client")
	}

	pr, _, err := client.PullRequests.Get(Ctx, owner, name, i.GetNumber())
	if err != nil {
		return errors.Wrap(err, "Getting PR")
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

	body := ice.GetComment().GetBody()

	if strings.Contains(body, CommandIgnore) {
		return ErrIgnored
	}

	if !strings.Contains(ice.GetComment().GetBody(), CommandTag) {
		return ErrNoTrigger
	}

	return nil
}
