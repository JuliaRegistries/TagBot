package main

import (
	"strings"
	"testing"

	"github.com/google/go-github/v25/github"
)

func makePRE(action string, merged bool, user, branch, body string) *github.PullRequestEvent {
	return &github.PullRequestEvent{
		Action: &action,
		PullRequest: &github.PullRequest{
			Merged: github.Bool(merged),
			User:   &github.User{Login: github.String(user)},
			Base:   &github.PullRequestBranch{Ref: github.String(branch)},
			Body:   github.String(body),
		},
	}
}

func makeBody(repository, version, commit, notes string) string {
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
	if notes != "" {
		ss = append(ss, "Release notes:", "<!-- BEGIN RELEASE NOTES -->", notes, "<!-- END RELEASE NOTES -->")
	}
	return strings.TrimSpace(strings.Join(ss, "\n"))
}

func TestShouldRelease(t *testing.T) {
	RegistratorUsername = "R"
	r := RegistratorUsername
	RegistryBranch = "b"
	b := RegistryBranch
	cases := []struct {
		in  *github.PullRequestEvent
		out error
	}{
		{makePRE("opened", true, "", "", ""), ErrNotMergeEvent},
		{makePRE(ActionClosed, false, "", "", ""), ErrNotMergeEvent},
		{makePRE(ActionClosed, true, "foo", "", ""), ErrNotRegistrator},
		{makePRE(ActionClosed, true, r, "foo", ""), ErrBaseBranch},
		{makePRE(ActionClosed, true, r, b, makeBody("", "", "", "")), ErrRepoMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "", "", "")), ErrVersionMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "v0.1.0", "", "")), ErrCommitMatch},
		{makePRE(ActionClosed, true, r, b, makeBody("github.com/a/b", "v0.1.0", "sha", "")), nil},
	}

	for i, tt := range cases {
		if out := ShouldRelease(tt.in); out != tt.out {
			t.Errorf("Case %d: Expected '%v', got '%v'", i, tt.out, out)
		}
	}
}

func TestParseBody(t *testing.T) {
	cases := []struct {
		in  string
		out ReleaseInfo
	}{
		{makeBody("github.com/a/b", "v0.1.0", "sha", ""), ReleaseInfo{"a", "b", "v0.1.0", "sha", ""}},
		{makeBody("https://github.com/a/b", "v0.1.0", "sha", ""), ReleaseInfo{"a", "b", "v0.1.0", "sha", ""}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha", " "), ReleaseInfo{"a", "b", "v0.1.0", "sha", ""}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha", "notes"), ReleaseInfo{"a", "b", "v0.1.0", "sha", "notes"}},
		{makeBody("http://github.com/a/b", "v0.1.0", "sha", "> foo\n> bar"), ReleaseInfo{"a", "b", "v0.1.0", "sha", "foo\nbar"}},
	}

	for i, tt := range cases {
		ri := ParseBody(tt.in)
		if ri.Owner != tt.out.Owner {
			t.Errorf("Case %d: Expected owner = %s, got %s", i, tt.out.Owner, ri.Owner)
		}
		if ri.Name != tt.out.Name {
			t.Errorf("Case %d: Expected name = %s, got %s", i, tt.out.Name, ri.Name)
		}
		if ri.Version != tt.out.Version {
			t.Errorf("Case %d: Expected version = %s, got %s", i, tt.out.Version, ri.Version)
		}
		if ri.Commit != tt.out.Commit {
			t.Errorf("Case %d: Expected commit = %s, got %s", i, tt.out.Commit, ri.Commit)
		}
	}
}
