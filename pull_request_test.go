package main

import (
	"strings"
	"testing"

	"github.com/google/go-github/v30/github"
)

func makePRE(action string, merged bool, user, branch, body string) *github.PullRequestEvent {
	return &github.PullRequestEvent{
		Action: &action,
		PullRequest: &github.PullRequest{
			Merged: github.Bool(merged),
			User:   &github.User{Login: github.String(user)},
			Body:   github.String(body),
			Base: &github.PullRequestBranch{
				Ref: github.String(branch),
				Repo: &github.Repository{
					DefaultBranch: github.String("master"),
				},
			},
		},
	}
}

func makeBody(repository, version, commit string) string {
	ss := []string{}
	if repository != "" {
		ss = append(ss, "Repository: "+repository)
	}
	if version != "" {
		ss = append(ss, "Version: "+version)
	}
	if commit != "" {
		ss = append(ss, "Commit: "+commit)
	}
	return strings.TrimSpace(strings.Join(ss, "\n"))
}

func TestShouldRelease(t *testing.T) {
	RegistratorUsername = "R"
	r := RegistratorUsername
	b := "master"
	cases := []struct {
		in  *github.PullRequestEvent
		out error
	}{
		{makePRE("opened", true, "", "", ""), ErrNotMergeEvent},
		{makePRE(ActionClosed, false, "", "", ""), ErrNotMergeEvent},
		{makePRE(ActionClosed, true, "foo", "", ""), ErrNotRegistrator},
		{makePRE(ActionClosed, true, r, "foo", ""), ErrBaseBranch},
		{makePRE(ActionClosed, true, r, b, makeBody("", "", "")), ErrRepoMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "", "")), ErrVersionMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "v0.1.0", "")), ErrCommitMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "v0.1.0", "sha")), nil},
	}

	for i, tt := range cases {
		if out := shouldRelease(tt.in); out != tt.out {
			t.Errorf("Case %d: Expected '%v', got '%v'", i, tt.out, out)
		}
	}
}

func TestParseBody(t *testing.T) {
	cases := []struct {
		in  string
		out Release
	}{
		{makeBody("github.com/a/b", "v0.1.0", "sha"), Release{"a", "b", "v0.1.0", "sha"}},
		{makeBody("https://github.com/a/b", "v0.1.0", "sha"), Release{"a", "b", "v0.1.0", "sha"}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha"), Release{"a", "b", "v0.1.0", "sha"}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha"), Release{"a", "b", "v0.1.0", "sha"}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha"), Release{"a", "b", "v0.1.0", "sha"}},
	}

	for i, tt := range cases {
		r := parseBody(tt.in)
		if r.User != tt.out.User {
			t.Errorf("Case %d: Expected owner = %s, got %s", i, tt.out.User, r.User)
		}
		if r.Repo != tt.out.Repo {
			t.Errorf("Case %d: Expected name = %s, got %s", i, tt.out.Repo, r.Repo)
		}
		if r.Version != tt.out.Version {
			t.Errorf("Case %d: Expected version = %s, got %s", i, tt.out.Version, r.Version)
		}
		if r.Commit != tt.out.Commit {
			t.Errorf("Case %d: Expected commit = %s, got %s", i, tt.out.Commit, r.Commit)
		}
	}
}
