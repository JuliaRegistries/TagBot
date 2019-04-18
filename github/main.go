package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/bradleyfalzon/ghinstallation"
	"github.com/google/go-github/github"
)

var (
	registratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	registryBranch      = os.Getenv("REGISTRY_BRANCH")
	pemFile             = "bin/" + os.Getenv("GITHUB_PEM_FILE")
	contactUser         = os.Getenv("GITHUB_CONTACT_USER")
	webhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))
	repoRegex           = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	versionRegex        = regexp.MustCompile(`Version:\s*(v.*)`)
	commitRegex         = regexp.MustCompile(`Commit:\s*(.*)`)
	ctx                 = context.Background()
	appID               int
	appClient           *github.Client

	ErrNotMergeEvent  = errors.New("Not a merge event")
	ErrNotRegistrator = errors.New("PR not created by Registrator")
	ErrBaseBranch     = errors.New("Base branch is not the default")
	ErrRepoMatch      = errors.New("No repo regex match")
	ErrVersionMatch   = errors.New("No version regex match")
	ErrCommitMatch    = errors.New("No commit regex match")
)

// LambdaRequest is what we get from AWS Lambda.
type LambdaRequest struct {
	Method  string            `json:"httpMethod"`
	Headers map[string]string `json:"headers"`
	Body    string            `json:"body"`
}

// Reponse is what we return from the handler.
type Response events.APIGatewayProxyResponse

// ReleaseInfo contains the information needed to create a GitHub release.
type ReleaseInfo struct {
	Owner   string
	Name    string
	Version string
	Commit  string
}

func init() {
	var err error
	appID, err = strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		fmt.Println("App ID:", err)
		return
	}

	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, appID, pemFile)
	if err != nil {
		fmt.Println("Transport:", err)
		return
	}

	appClient = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	if appClient == nil {
		fmt.Println("App client is not available")
		return
	}

	lambda.Start(func(lr LambdaRequest) (response Response, nilErr error) {
		response = Response{StatusCode: 200}
		defer func(r *Response) {
			if r.Body != "" {
				fmt.Println(r.Body)
			} else {
				fmt.Println("No error")
			}
		}(&response)

		r, err := LambdaToHttp(lr)
		if err != nil {
			response.Body = "Converting request: " + err.Error()
			return
		}

		payload, err := github.ValidatePayload(r, webhookSecret)
		if err != nil {
			response.Body = "Validating payload: " + err.Error()
			return
		}

		event, err := github.ParseWebHook(github.WebHookType(r), payload)
		if err != nil {
			response.Body = "Parsing payload: " + err.Error()
			return
		}

		pre, ok := event.(*github.PullRequestEvent)
		if !ok {
			response.Body = "Unknown event type: " + github.WebHookType(r)
			return
		}

		PrintInfo(pre)

		if err = ShouldRelease(pre); err != nil {
			response.Body = "Validation: " + err.Error()
			return
		}

		ri := ParseBody(PreprocessBody(pre.GetPullRequest().GetBody()))

		client, err := GetInstallationClient(ri.Owner)
		if err != nil {
			response.Body = "Installation client: " + err.Error()
			return
		}

		if err := ri.DoRelease(client, pre.GetPullRequest()); err != nil {
			response.Body = "Creating release: " + err.Error()
			return
		}

		return
	})
}

// LambdaToHttp converts a Lambda request to an HTTP request.
func LambdaToHttp(lr LambdaRequest) (*http.Request, error) {
	r, err := http.NewRequest(lr.Method, "", bytes.NewBufferString(lr.Body))
	if err != nil {
		return nil, err
	}
	for k, v := range lr.Headers {
		r.Header.Add(k, v)
	}
	return r, nil
}

// PrintInfo prints out some logging information.
func PrintInfo(pre *github.PullRequestEvent) {
	pr := pre.GetPullRequest()
	u := pr.GetUser()
	body := strings.TrimSpace(pr.GetBody())

	info := `
=== Info ===
Registrator: %s
Registry branch: %s
PR Action: %s
PR Merged: %t
PR Creator: %s
PR Base: %s
PR Title: %s
PR Body:
-----
%s
-----
============
`
	fmt.Printf(
		info,
		registratorUsername,
		registryBranch,
		pre.GetAction(),
		pr.GetMerged(),
		u.GetLogin(),
		pr.GetBase().GetRef(),
		pr.GetTitle(),
		body,
	)
}

// PreprocessBody preprocesses the PR body.
func PreprocessBody(body string) string {
	return strings.TrimSpace(strings.Replace(body, "\r\n", "\n", -1))
}

// ShouldRelease determines whether the PR indicates a release.
func ShouldRelease(pre *github.PullRequestEvent) error {
	pr := pre.GetPullRequest()
	u := pr.GetUser()
	body := pr.GetBody()

	if pre.GetAction() != "closed" || !pr.GetMerged() {
		return ErrNotMergeEvent
	}

	if u.GetLogin() != registratorUsername {
		return ErrNotRegistrator
	}

	if pr.GetBase().GetRef() != registryBranch {
		return ErrBaseBranch
	}

	if !repoRegex.MatchString(body) {
		return ErrRepoMatch
	}

	if !versionRegex.MatchString(body) {
		return ErrVersionMatch
	}

	if !commitRegex.MatchString(body) {
		return ErrCommitMatch
	}

	return nil
}

// ParseBody parses the PR body and returns a ReleaseInfo.
// The assumption is that the PR body is valid.
func ParseBody(body string) ReleaseInfo {
	match := repoRegex.FindStringSubmatch(body)
	owner, name := match[1], match[2]

	match = versionRegex.FindStringSubmatch(body)
	version := match[1]

	match = commitRegex.FindStringSubmatch(body)
	commit := match[1]

	return ReleaseInfo{
		Owner:   owner,
		Name:    name,
		Version: version,
		Commit:  commit,
	}
}

// GetInstallationClient returns a client that can be used to interact with an installation.
func GetInstallationClient(user string) (*github.Client, error) {
	i, _, err := appClient.Apps.FindUserInstallation(ctx, user)
	if err != nil {
		return nil, err
	}

	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, appID, int(i.GetID()), pemFile)
	if err != nil {
		return nil, err
	}

	return github.NewClient(&http.Client{Transport: tr}), nil
}

// DoRelease creates the GitHub release.
func (ri ReleaseInfo) DoRelease(client *github.Client, pr *github.PullRequest) error {
	var err error
	r := &github.RepositoryRelease{TagName: &ri.Version, TargetCommitish: &ri.Commit}

	r, _, err = client.Repositories.CreateRelease(ctx, ri.Owner, ri.Name, r)
	if err != nil {
		MakeErrorComment(pr, err)
		return errors.New("Creating release: " + err.Error())
	}

	MakeSuccessComment(pr, r)
	fmt.Printf("Created release %s for %s/%s at %s\n", ri.Version, ri.Owner, ri.Name, ri.Commit)
	return nil
}

// MakeSuccessComment adds a comment to the PR indicating success.
func MakeSuccessComment(pr *github.PullRequest, r *github.RepositoryRelease) {
	body := fmt.Sprintf(
		"I've created release `%s`, [here](%s) it is.",
		r.GetTagName(), r.GetHTMLURL(),
	)
	SendComment(pr, body)
}

// MakeErrorComment adds a comment to the PR indicating failure.
func MakeErrorComment(pr *github.PullRequest, err error) {
	body := fmt.Sprintf(
		"I tried to create a release but ran into this error:\n```\n%v\n```\ncc: @%s",
		err, contactUser,
	)
	SendComment(pr, body)
}

// SendComment adds a comment to a PR.
func SendComment(pr *github.PullRequest, body string) {
	repo := pr.GetBase().GetRepo()
	owner := repo.GetOwner().GetLogin()
	name := repo.GetName()
	num := pr.GetNumber()

	client, err := GetInstallationClient(owner)
	if err != nil {
		fmt.Println("Creating comment:", err)
		return
	}

	c := github.IssueComment{Body: &body}
	if _, _, err := client.Issues.CreateComment(ctx, owner, name, num, &c); err != nil {
		fmt.Println("Creating comment:", err)
	}
}
