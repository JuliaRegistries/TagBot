package main

import (
	"testing"

	"github.com/google/go-github/v30/github"
)

func makeICE(action string, isPR bool, senderType, body string) *github.IssueCommentEvent {
	var prLinks *github.PullRequestLinks = nil
	if isPR {
		prLinks = &github.PullRequestLinks{}
	}

	return &github.IssueCommentEvent{
		Action:  github.String(action),
		Issue:   &github.Issue{PullRequestLinks: prLinks},
		Sender:  &github.User{Type: github.String(senderType)},
		Comment: &github.IssueComment{Body: github.String(body)},
	}
}

func TestIsTriggerComment(t *testing.T) {
	cases := []struct {
		in  *github.IssueCommentEvent
		out error
	}{
		{makeICE("deleted", true, "", ""), ErrNotNewComment},
		{makeICE(ActionCreated, false, "", ""), ErrNotPullRequest},
		{makeICE(ActionCreated, true, "Bot", ""), ErrCommentByBot},
		{makeICE(ActionCreated, true, "", ""), ErrNoTrigger},
		{makeICE(ActionCreated, true, "", "foo "+CommandTag+" bar "+CommandIgnore), ErrIgnored},
		{makeICE(ActionCreated, true, "", "foo "+CommandTag+" bar"), nil},
	}

	for i, tt := range cases {
		if out := isTriggerComment(tt.in); out != tt.out {
			t.Errorf("Case %d: Expected '%v', got '%v'", i, tt.out, out)
		}
	}
}
