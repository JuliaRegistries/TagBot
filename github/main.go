package main

import (
	"bytes"
	"context"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/bradleyfalzon/ghinstallation"
	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

const (
	ActionClosed  = "closed"
	ActionCreated = "created"
	PemName       = "tag-bot.pem"
	GPGDir        = "gnupg"
	CommandPrefix = "TagBot "
	CommandTag    = CommandPrefix + "tag"
)

var (
	RegistratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	ContactUser         = os.Getenv("GITHUB_CONTACT_USER")
	WebhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))

	Ctx          = context.Background()
	ResourcesTar = filepath.Join("bin", "resources.tar")
	IsSetup      = false

	ResourcesDir string
	AppID        int
	AppClient    *github.Client

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
	if IsSetup {
		return
	}

	var err error

	// Load the app ID from the environment.
	AppID, err = strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		fmt.Println("App ID:", err)
		return
	}

	// Get a directory that we can write to.
	ResourcesDir, err = ioutil.TempDir("", "")
	if err != nil {
		fmt.Println("Temp dir:", err)
		return
	}

	// Extract the resources into the temp directory.
	// The reason that we have to do the extraction in the first place is that
	// the default bundling doesn't preserve file permissions, which fudges GnuPG.
	if err := DoCmd("tar", "-xf", ResourcesTar, "-C", ResourcesDir); err != nil {
		fmt.Println("tar:", err)
		return
	}

	// Make GnuPG use our key.
	os.Setenv("GNUPGHOME", filepath.Join(ResourcesDir, GPGDir))

	// Load the private GitHub key for our app.
	pemFile := filepath.Join(ResourcesDir, PemName)
	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, AppID, pemFile)
	if err != nil {
		fmt.Println("Transport:", err)
		return
	}
	AppClient = github.NewClient(&http.Client{Transport: tr})

	IsSetup = true
}

func main() {
	lambda.Start(func(lr LambdaRequest) (resp Response, nilErr error) {
		resp = Response{StatusCode: 200}
		defer func(r *Response) {
			fmt.Println(r.Body)
		}(&resp)

		req, err := LambdaToHttp(lr)
		if err != nil {
			resp.Body = "Converting request: " + err.Error()
			return
		}

		payload, err := github.ValidatePayload(req, WebhookSecret)
		if err != nil {
			resp.Body = "Validating payload: " + err.Error()
			return
		}

		event, err := github.ParseWebHook(github.WebHookType(req), payload)
		if err != nil {
			resp.Body = "Parsing payload: " + err.Error()
			return
		}

		id := github.DeliveryID(req)
		info := `
Delivery ID: %s
Registrator: %s
Contact user: %s
`
		fmt.Printf(info, id, RegistratorUsername, ContactUser)

		switch event.(type) {
		case *github.PullRequestEvent:
			err = HandlePullRequest(event.(*github.PullRequestEvent), id)
		case *github.IssueCommentEvent:
			err = HandleIssueComment(event.(*github.IssueCommentEvent), id)
		default:
			err = errors.New("Unknown event type: " + github.WebHookType(req))
		}

		if err == nil {
			resp.Body = "No error"
		} else {
			resp.Body = err.Error()
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

	pemFile := filepath.Join(ResourcesDir, PemName)
	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, AppID, int(i.GetID()), pemFile)
	if err != nil {
		return nil, err
	}

	return github.NewClient(&http.Client{Transport: tr}), nil
}

// PreprocessBody preprocesses the PR body.
func PreprocessBody(body string) string {
	return strings.TrimSpace(strings.Replace(body, "\r\n", "\n", -1))
}

// DoCmd runs a shell command and prints any output.
func DoCmd(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	b, err := cmd.CombinedOutput()
	s := strings.TrimSpace(string(b))
	if len(s) > 0 {
		fmt.Println(s)
	}
	return err
}
