package main

import (
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"strings"

	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

var (
	TaggerName  = os.Getenv("GIT_TAGGER_NAME")
	TaggerEmail = os.Getenv("GIT_TAGGER_EMAIL")
	WIPMessage  = os.Getenv("CHANGELOG_WIP_MESSAGE")
)

// Release contains the information needed to create a GitHub release.
type Release struct {
	User    string
	Repo    string
	Version string
	Commit  string
	Notes   string
}

// ToChangelogRequest creates a ChangelogRequest from a Release.
func (r Release) ToChangelogRequest(pr *github.PullRequest, auth string) ChangelogRequest {
	cr := ChangelogRequest{
		User: r.User,
		Repo: r.Repo,
		Tag:  r.Version,
		Auth: auth,
	}
	repo := pr.GetBase().GetRepo()
	cr.PR.User = repo.GetOwner().GetLogin()
	cr.PR.Repo = repo.GetName()
	cr.PR.Number = pr.GetNumber()
	return cr
}

// Do creates the Git tag and GitHub release.
func (r Release) Do(client *github.Client, pr *github.PullRequest, id string) error {
	// Create a Git tag, only if one doesn't already exist.
	// If a tag already exists, make sure that it points to the right commit.
	ref, resp, err := client.Git.GetRef(Ctx, r.User, r.Repo, "tags/"+r.Version)

	// We'll need an auth token later so grab one now.
	header := resp.Request.Header.Get("Authorization")
	if header == "" {
		err = ErrNoAuthHeader
		MakeErrorComment(pr, id, err)
		return err
	}
	tokens := strings.Split(header, " ")
	auth := tokens[len(tokens)-1]

	if resp.StatusCode == http.StatusNotFound {
		// No tag exists, so create one.
		if err = r.createTag(auth); err != nil {
			err = errors.Wrap(err, "Creating tag")
			MakeErrorComment(pr, id, err)
			return err
		}
	} else if err != nil {
		// Don't worry about errors, just let GitHub create the tag along with the release.
		fmt.Println("Get ref:", err)
	} else {
		// A tag already exists.
		var sha string
		obj := ref.GetObject()
		switch t := obj.GetType(); t {
		case "commit":
			sha = obj.GetSHA()
		case "tag":
			tag, _, err := client.Git.GetTag(Ctx, r.User, r.Repo, obj.GetSHA())
			if err != nil {
				fmt.Println("Get tag:", err)
			} else {
				sha = tag.GetObject().GetSHA()
			}
		default:
			fmt.Println("Unknown ref type", t)
			sha = obj.GetSHA()
		}

		if sha != r.Commit {
			// The existing tag is on the wrong commit.
			err = ErrBadExistingTag
			MakeErrorComment(pr, id, err)
			return err
		}
	}

	// GitHub doesn't display the nice "n commits to <branch> since this release"
	// when we use a commit SHA as a release target.
	// If the commit being released is the head commit, we can use the branch name instead.
	target := r.Commit
	repo, _, err := client.Repositories.Get(Ctx, r.User, r.Repo)
	if err == nil {
		branch, _, err := client.Repositories.GetBranch(Ctx, r.User, r.Repo, repo.GetDefaultBranch())
		if err == nil && branch.GetCommit().GetSHA() == target {
			target = branch.GetName()
		}
	}

	// Create a GitHub release associated with the tag.
	rel := &github.RepositoryRelease{
		TagName:         github.String(r.Version),
		Name:            github.String(r.Version),
		TargetCommitish: github.String(target),
	}
	if r.Notes == "" {
		if err := r.ToChangelogRequest(pr, auth).Send(); err != nil {
			fmt.Println("Changelog request:", err)
		} else {
			rel.Body = github.String(WIPMessage)
		}
	} else {
		rel.Body = github.String(r.Notes)
	}
	if rel, resp, err = client.Repositories.CreateRelease(Ctx, r.User, r.Repo, rel); err != nil {
		// If the release already exists, there's no need to bug the user about it.
		// We know from the checks above that the existing tag is correct.
		if resp.StatusCode == http.StatusUnprocessableEntity {
			return ErrReleaseExists
		}
		err = errors.Wrap(err, "Creating release")
		MakeErrorComment(pr, id, err)
		return err
	}

	MakeSuccessComment(pr, id, rel)
	fmt.Printf("Created release %s for %s/%s at %s\n", r.Version, r.User, r.Repo, r.Commit)

	return nil
}

// createTag creates and pushes a Git tag.
// We use the Git CLI instead of the GitHub API so that we can use GPG signing.
func (r Release) createTag(auth string) error {
	// Clone the repo to a temp directory that we can write to, using an authenticated URL.
	dir, err := ioutil.TempDir("", "")
	if err != nil {
		return errors.Wrap(err, "Temp dir")
	}
	url := fmt.Sprintf("https://oauth2:%s@github.com/%s/%s", auth, r.User, r.Repo)
	if err = DoCmd("git", "clone", url, dir); err != nil {
		return errors.Wrap(err, "git clone")
	}
	defer os.RemoveAll(dir)

	// Configure Git.
	if err = DoCmd("git", "-C", dir, "config", "user.name", TaggerName); err != nil {
		return errors.Wrap(err, "git config")
	}
	if err := DoCmd("git", "-C", dir, "config", "user.email", TaggerEmail); err != nil {
		return errors.Wrap(err, "git config")
	}

	// Create and push the tag.
	msg := r.Notes
	if msg == "" {
		msg = fmt.Sprintf(
			"See github.com/%s/%s/releases/tag/%s for release notes",
			r.User, r.Repo, r.Version,
		)
	}
	if err = DoCmd("git", "-C", dir, "tag", r.Version, r.Commit, "-s", "-m", msg); err != nil {
		return errors.Wrap(err, "git tag")
	}
	if err = DoCmd("git", "-C", dir, "push", "origin", "--tags"); err != nil {
		return errors.Wrap(err, "git push")
	}

	return nil
}
