package main

import "github.com/pkg/errors"

var (
	ErrBadExistingTag = errors.New("A tag already exists, but it points at the wrong commit")
	ErrBaseBranch     = errors.New("Base branch is not the default")
	ErrCommentByBot   = errors.New("Comment is made by a bot")
	ErrCommitMatch    = errors.New("No commit regex match")
	ErrIgnored        = errors.New("Comment contained ignore command")
	ErrNoSpace        = errors.New("No space left on device")
	ErrNoTrigger      = errors.New("Comment doesn't contain trigger phrase")
	ErrNotMergeEvent  = errors.New("Not a merge event")
	ErrNotNewComment  = errors.New("Not a comment creation event")
	ErrNotPullRequest = errors.New("Comment not on a pull request")
	ErrNotRegistrator = errors.New("PR not created by Registrator")
	ErrReleaseExists  = errors.New("A release for this tag already exists")
	ErrRepoMatch      = errors.New("No repo regex match")
	ErrRepoNotEnabled = errors.New("App is installed for user but the repository is not enabled")
	ErrVersionMatch   = errors.New("No version regex match")
)
