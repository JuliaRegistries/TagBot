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
	CommandPrefix = "TagBot "
	CommandTag    = CommandPrefix + "tag"
)

var (
	RegistratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	RegistryBranch      = os.Getenv("REGISTRY_BRANCH")
	ContactUser         = os.Getenv("GITHUB_CONTACT_USER")
	S3Bucket            = os.Getenv("S3_BUCKET")
	WebhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))

	Ctx        = context.Background()
	MissingEnv = ""
	IsSetup    = false

	ResourcesDir string
	PemFile      string
	AppID        int
	AppClient    *github.Client

	ErrAppIDNotSet    = errors.New("App ID environment variable is not set")
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
	for _, k := range []string{
		"GITHUB_APP_ID",
		"GITHUB_WEBHOOK_SECRET",
		"GITHUB_CONTACT_USER",
		"REGISTRATOR_USERNAME",
		"REGISTRY_BRANCH",
		"GIT_TAGGER_NAME",
		"GIT_TAGGER_EMAIL",
		"S3_BUCKET",
	} {
		if os.Getenv(k) == "" {
			MissingEnv = k
			return
		}
	}
}

func main() {
	lambda.Start(func(lr LambdaRequest) (response Response, nilErr error) {
		response = Response{StatusCode: 200}
		defer func(r *Response) {
			fmt.Println(r.Body)
		}(&response)

		if MissingEnv != "" {
			response.Body = "Missing environment variable " + MissingEnv
		}

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
			err = HandlePullRequest(event.(*github.PullRequestEvent), id)
		case *github.IssueCommentEvent:
			err = HandleIssueComment(event.(*github.IssueCommentEvent), id)
		default:
			err = errors.New("Unknown event type: " + github.WebHookType(r))
		}

		if err == nil {
			response.Body = "No error"
		} else {
			response.Body = err.Error()
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

// Setup does mandatory preparation and configuration.
func Setup() error {
	if IsSetup {
		return nil
	}

	var err error
	AppID, err = strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		return errors.Wrap(err, "App ID")
	}

	ResourcesDir, err = ioutil.TempDir("", "")
	if err != nil {
		return errors.Wrap(err, "Temp dir")
	}

	if err := DoCmd("aws", "s3", "sync", "s3://"+S3Bucket, ResourcesDir); err != nil {
		return errors.Wrap(err, "S3 sync")
	}

	PemFile = filepath.Join(ResourcesDir, "tag-bot.pem")
	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, AppID, PemFile)
	if err != nil {
		return errors.Wrap(err, "Transport")
	}

	AppClient = github.NewClient(&http.Client{Transport: tr})

	gpg := filepath.Join(ResourcesDir, "gnupg")
	os.Setenv("GNUPGHOME", gpg)

	if err = DoCmd("find", gpg, "-type", "d", "-exec", "chmod", "700", "{}", ";"); err != nil {
		return errors.Wrap(err, "chmod")
	}
	if err = DoCmd("find", gpg, "-type", "f", "-exec", "chmod", "600", "{}", ";"); err != nil {
		return errors.Wrap(err, "chmod")
	}

	IsSetup = true
	return nil
}
