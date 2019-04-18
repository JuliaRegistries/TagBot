package main

import (
	"io/ioutil"
	"strconv"
	"strings"
	"testing"

	"github.com/google/go-github/github"
)

func TestLambdaToHttp(t *testing.T) {
	lr := LambdaRequest{"POST", map[string]string{"foo": "bar", "bar": "baz"}, "abc"}
	r, err := LambdaToHttp(lr)
	if err != nil {
		t.Fatalf("Expected err = nil, got %v", err)
	}

	if r.Method != "POST" {
		t.Errorf("Expected method = 'POST', got '%s'", r.Method)
	}

	if n := len(r.Header); n != 2 {
		t.Errorf("Expected length of headers = 2, got %d", n)
	}
	if h := r.Header.Get("foo"); h != "bar" {
		t.Errorf("Expected 'foo' header = 'bar', got '%s'", h)
	}
	if h := r.Header.Get("bar"); h != "baz" {
		t.Errorf("Expected 'bar' header = 'baz', got '%s'", h)
	}

	if b, err := ioutil.ReadAll(r.Body); err != nil {
		t.Errorf("Expected err = nil, got %v", err)
	} else if string(b) != "abc" {
		t.Errorf("Expected body = 'abc', got %s", b)
	}
}

func makePRE(action string, merged bool, user, branch, body string) *github.PullRequestEvent {
	return &github.PullRequestEvent{
		Action: &action,
		PullRequest: &github.PullRequest{
			Merged: &merged,
			User: &github.User{Login: &user},
			Base: &github.PullRequestBranch{Ref: &branch},
			Body: &body,
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
	registratorUsername = "R"
	r := registratorUsername
	registryBranch = "b"
	b := registryBranch
	cases := []struct {
		in  *github.PullRequestEvent
		out error
	}{
		{makePRE("opened", true, "", "", ""), ErrNotMergeEvent},
		{makePRE("closed", false, "", "", ""), ErrNotMergeEvent},
		{makePRE("closed", true, "foo", "", ""), ErrNotRegistrator},
		{makePRE("closed", true, r, "foo", ""), ErrBaseBranch},
		{makePRE("closed", true, r, b, makeBody("", "", "")), ErrRepoMatch},
		{makePRE("closed", true, r, b, makeBody("github.com/foo/bar", "", "")), ErrVersionMatch},
		{makePRE("closed", true, r, b, makeBody("github.com/foo/bar", "v0.1.0", "")), ErrCommitMatch},
		{makePRE("closed", true, r, b, makeBody("github.com/foo/bar", "v0.1.0", "sha")), nil},
	}

	for i, tt := range cases {
		if out := ShouldRelease(tt.in); out != tt.out {
			t.Errorf("Case %d: Expected %v, got %v", i, tt.out, out)
		}
	}
}

func TestPreprocessBody(t *testing.T) {
	cases := []string{
		"a \r\n b \r\n c",
		"\r\n a \r\n b \r\n c \r\n",
		"\n a \n b \n c \n",
		"a \n b \r\n c \n",
	}
	expected := "a \n b \n c"

	for i, in := range cases {
		if out := PreprocessBody(in); out != expected {
			t.Errorf("Case %d: Expected %s, got %s", i, strconv.Quote(expected), strconv.Quote(out))
		}
	}
}

func TestParseBody(t *testing.T) {
	cases := []struct {
		in  string
		out ReleaseInfo
	}{
		{makeBody("github.com/foo/bar", "v0.1.0", "sha"), ReleaseInfo{"foo", "bar", "v0.1.0", "sha"}},
		{makeBody("https://github.com/foo/bar", "v0.1.0", "sha"), ReleaseInfo{"foo", "bar", "v0.1.0", "sha"}},
		{makeBody("http://github.com/foo/bar", "v0.1.0", "sha"), ReleaseInfo{"foo", "bar", "v0.1.0", "sha"}},
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
