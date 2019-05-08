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
	"github.com/google/go-github/v25/github"
)

const (
	ActionClosed  = "closed"
	ActionCreated = "created"
	CommandPrefix = "TagBot "
	CommandTag    = CommandPrefix + "tag"
)

var (
	RegistratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	RegistryBranch      = os.Getenv("REGISTRY_BRANCH")
	ContactUser         = os.Getenv("GITHUB_CONTACT_USER")
	WebhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))
	PemFile             = "bin/" + os.Getenv("GITHUB_PEM_FILE")

	RepoRegex    = regexp.MustCompile(`Repository:.*github.com/(.*)/(.*)`)
	VersionRegex = regexp.MustCompile(`Version:\s*(v.*)`)
	CommitRegex  = regexp.MustCompile(`Commit:\s*(.*)`)

	Ctx = context.Background()

	AppID     int
	AppClient *github.Client

	ErrRepoNotEnabled = errors.New("App is installed for user but the repository is not enabled")
)

// LambdaRequest is what we get from AWS Lambda.
type LambdaRequest struct {
	Method  string            `json:"httpMethod"`
	Headers map[string]string `json:"headers"`
	Body    string            `json:"body"`
}

// Reponse is what we return from the handler.
type Response events.APIGatewayProxyResponse

func init() {
	var err error
	AppID, err = strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		fmt.Println("App ID:", err)
		return
	}

	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, AppID, PemFile)
	if err != nil {
		fmt.Println("Transport:", err)
		return
	}

	AppClient = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	if AppClient == nil {
		fmt.Println("App client is not available")
		return
	}

	lambda.Start(func(lr LambdaRequest) (response Response, nilErr error) {
		response = Response{StatusCode: 200}
		defer func(r *Response) {
			fmt.Println(r.Body)
		}(&response)

		r, err := LambdaToHttp(lr)
		if err != nil {
			response.Body = "Converting request: " + err.Error()
			return
		}

		payload, err := github.ValidatePayload(r, WebhookSecret)
		if err != nil {
			response.Body = "Validating payload: " + err.Error()
			return
		}

		event, err := github.ParseWebHook(github.WebHookType(r), payload)
		if err != nil {
			response.Body = "Parsing payload: " + err.Error()
			return
		}

		id := github.DeliveryID(r)
		info := `
Delivery ID: %s
Registrator: %s
Registry branch: %s
Contact user: %s
`
		fmt.Printf(info, id, RegistratorUsername, RegistryBranch, ContactUser)

		switch event.(type) {
		case *github.PullRequestEvent:
			response.Body = HandlePullRequest(event.(*github.PullRequestEvent), id)
		case *github.IssueCommentEvent:
			response.Body = HandleIssueComment(event.(*github.IssueCommentEvent), id)
		default:
			response.Body = "Unknown event type: " + github.WebHookType(r)
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

// GetInstallationClient returns a client that can be used to interact with an installation.
func GetInstallationClient(owner, name string) (*github.Client, error) {
	i, resp, err := AppClient.Apps.FindRepositoryInstallation(Ctx, owner, name)
	if err != nil {
		if resp.StatusCode == 404 {
			if _, _, err = AppClient.Apps.FindUserInstallation(Ctx, owner); err == nil {
				return nil, ErrRepoNotEnabled
			}
		}
		return nil, err
	}

	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, AppID, int(i.GetID()), PemFile)
	if err != nil {
		return nil, err
	}

	return github.NewClient(&http.Client{Transport: tr}), nil
}

// PreprocessBody preprocesses the PR body.
func PreprocessBody(body string) string {
	return strings.TrimSpace(strings.Replace(body, "\r\n", "\n", -1))
}
