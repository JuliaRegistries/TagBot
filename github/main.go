package main

import (
	"bytes"
	"context"
	"errors"
	"log"
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
	webhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))
	repoRegex           = regexp.MustCompile(`Repository:\s+(.*)`)
	repoPiecesRegex     = regexp.MustCompile(`github.com/(.*)/(.*)`)
	versionRegex        = regexp.MustCompile(`Version:\s+(v.*)`)
	commitRegex         = regexp.MustCompile(`Commit:\s+(.*)`)
	ctx                 = context.Background()
	client              *github.Client
)

// LambdaRequest is what we get from AWS Lambda.
type LambdaRequest struct {
	Method  string            `json:"httpMethod"`
	Headers map[string]string `json:"headers`
	Body    string            `json:"body`
}

type Response events.APIGatewayProxyResponse

func init() {
	appID, err := strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		log.Println("App ID:", err)
		return
	}

	installationID, err := strconv.Atoi(os.Getenv("GITHUB_INSTALLATION_ID"))
	if err != nil {
		log.Println("Installation ID:", err)
		return
	}

	pemFile := "bin/" + os.Getenv("GITHUB_PEM_FILE")
	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, appID, installationID, pemFile)
	if err != nil {
		log.Println("Transport:", err)
		return
	}

	client = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	if client == nil {
		log.Println("Client is not available")
		return
	}

	lambda.Start(func(lr LambdaRequest) (response Response, nilErr error) {
		// It doesn't matter what we return to the webhook.
		response = Response{StatusCode: 204}

		// Convert the request to an HTTP request.
		r, err := lambdaToHttp(lr)
		if err != nil {
			log.Println("Converting request:", err)
			return
		}

		// Validate the payload.
		payload, err := github.ValidatePayload(r, webhookSecret)
		if err != nil {
			log.Println("Validating payload:", err)
			return
		}

		// Parse the event.
		event, err := github.ParseWebHook(github.WebHookType(r), payload)
		if err != nil {
			log.Println("Parsing payload:", err)
			return
		}

		// Check the event type.
		pre, ok := event.(*github.PullRequestEvent)
		if !ok {
			log.Println("Unknown event type:", github.WebHookType(r))
			return
		}

		// Handle the pull request event.
		if err = handlePullRequestEvent(pre); err != nil {
			log.Println("Event handling:", err)
			return
		}

		return
	})
}

// Lambda2HTTP converts a Lambda request to an HTTP request.
func lambdaToHttp(lr LambdaRequest) (*http.Request, error) {
	r, err := http.NewRequest(lr.Method, "", bytes.NewBufferString(lr.Body))
	if err != nil {
		return nil, err
	}
	for k, v := range lr.Headers {
		r.Header.Add(k, v)
	}
	return r, nil
}

// handlePullRequest creates a release from a merged pull request.
func handlePullRequestEvent(pre *github.PullRequestEvent) error {
	pr := pre.GetPullRequest()
	u := pr.GetUser()
	body := strings.TrimSpace(pr.GetBody())

	// Check that the event is a PR merge.
	if pre.GetAction() != "closed" || !pr.GetMerged() {
		return errors.New("Not a merge event")
	}

	// Check that the PR creator is Registrator.
	if u.GetLogin() != registratorUsername {
		return errors.New("PR not created by Registrator")
	}

	// Check that the base branch is the default.
	if pr.GetBase().GetRef() != registryBranch {
		return errors.New("Base branch is not the default")
	}

	// Get the repository URL.
	match := repoRegex.FindStringSubmatch(body)
	if match == nil {
		return errors.New("No repo regex match")
	}
	repoURL := match[1]
	log.Println("Extracted repo URL:", repoURL)

	// Get the repository owner and name.
	match = repoPiecesRegex.FindStringSubmatch(repoURL)
	if match == nil {
		return errors.New("No repo pieces regex match")
	}
	owner, name := match[1], match[2]
	log.Println("Extracted repo owner:", owner)
	log.Println("Extracted repo name:", name)

	// Get the package version.
	match = versionRegex.FindStringSubmatch(body)
	if match == nil {
		return errors.New("No version regex match")
	}
	version := match[1]
	log.Println("Extracted package version:", version)

	// Get the release commit hash.
	match = commitRegex.FindStringSubmatch(body)
	if match == nil {
		return errors.New("No commit regex match")
	}
	sha := match[1]
	log.Println("Extracted commit:", sha)

	// Create the release.
	release := &github.RepositoryRelease{TagName: &version, TargetCommitish: &sha}
	if _, _, err := client.Repositories.CreateRelease(ctx, owner, name, release); err != nil {
		return err
	}

	log.Printf("Created release %s for %s/%s at %s\n", version, owner, name, sha)
	return nil
}
