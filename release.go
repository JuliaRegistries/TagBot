package main

import (
	"fmt"
	"net/http"

	"github.com/google/go-github/v30/github"
)

// Release contains the information needed to create a GitHub release.
type Release struct {
	User    string
	Repo    string
	Version string
	Commit  string
}

// Do creates the Git tag and GitHub release.
func (r Release) Do(client *github.Client, pr *github.PullRequest, id string) error {
	// Create a Git tag, only if one doesn't already exist.
	// If a tag already exists, make sure that it points to the right commit.
	ref, resp, err := client.Git.GetRef(Ctx, r.User, r.Repo, "tags/"+r.Version)
	if err != nil {
		// Don't worry about errors, just let GitHub create the tag along with the release.
		fmt.Println("Get ref:", err)
	} else if resp.StatusCode == http.StatusOK {
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
	if rel, resp, err = client.Repositories.CreateRelease(Ctx, r.User, r.Repo, rel); err != nil {
		// If the release already exists, there's no need to bug the user about it.
		// We know from the checks above that the existing tag is correct.
		if resp.StatusCode == http.StatusUnprocessableEntity {
			return ErrReleaseExists
		}
		err = fmt.Errorf("Creating release: %w", err)
		MakeErrorComment(pr, id, err)
		return err
	}

	MakeSuccessComment(pr, id, rel)
	fmt.Printf("Created release %s for %s/%s at %s\n", r.Version, r.User, r.Repo, r.Commit)

	return nil
}
