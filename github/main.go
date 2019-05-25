package main

import (
	"context"
	"encoding/json"
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
	"github.com/aws/aws-sdk-go/aws/session"
	"github.com/aws/aws-sdk-go/service/sqs"
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
	FailureMsg    = "I tried to create a changelog but failed, you may want to edit the release yourself."
)

var (
	RegistratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	ContactUser         = os.Getenv("GITHUB_CONTACT_USER")
	WebhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))

	Ctx          = context.Background()
	ResourcesTar = filepath.Join("github", "bin", "resources.tar")
	IsSetup      = false

	ResourcesDir string
	AppID        int
	AppClient    *github.Client
	SQS          *sqs.SQS

	ErrRepoNotEnabled = errors.New("App is installed for user but the repository is not enabled")
)

// Request is what we get from AWS Lambda.
type Request struct {
	// HTTP events.
	Method  string            `json:"httpMethod"`
	Headers map[string]string `json:"headers"`
	Body    string            `json:"body"`

	// SQS events.
	Records []events.SQSMessage
}

// Reponse is what we return from the handler.
type Response events.APIGatewayProxyResponse

type ChangelogRequest struct {
	User string `json:"user"`
	Repo string `json:"repo"`
	Tag  string `json:"tag"`
	Auth string `json:"auth"`
	PR   struct {
		User   string `json:"user"`
		Repo   string `json:"repo"`
		Number int    `json:"number"`
	} `json:"pr"`
}

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

	// Set up an AWS SQS client.
	sess, err := session.NewSession()
	if err != nil {
		fmt.Println("Session:", err)
	} else {
		SQS = sqs.New(sess)
	}

	IsSetup = true
}

func main() {
	lambda.Start(func(r Request) (resp Response, nilErr error) {
		resp = Response{StatusCode: http.StatusOK}
		defer func(r *Response) {
			fmt.Println(r.Body)
		}(&resp)

		var err error
		if len(r.Records) == 0 {
			err = r.HandleHTTP()
		} else {
			err = r.HandleSQS()
		}

		if err == nil {
			resp.Body = "No error"
		} else {
			resp.Body = err.Error()
		}

		return
	})
}

// HandleSQS handles events from SQS.
func (r Request) HandleHTTP() error {
	req := r.ToHTTP()

	payload, err := github.ValidatePayload(req, WebhookSecret)
	if err != nil {
		return errors.Wrap(err, "Validating payload")
	}

	event, err := github.ParseWebHook(github.WebHookType(req), payload)
	if err != nil {
		return errors.Wrap(err, "Parsing payload")
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
		return HandlePullRequest(event.(*github.PullRequestEvent), id)
	case *github.IssueCommentEvent:
		return HandleIssueComment(event.(*github.IssueCommentEvent), id)
	default:
		return errors.New("Unknown event type: " + github.WebHookType(req))
	}
}

// HandleSQS handles events from SQS.
func (r Request) HandleSQS() error {
	var ret error

	for _, r := range lr.Records {
		var cr *ChangelogRequest
		if err := json.Unmarshal([]byte(r.Body), cr); err != nil {
			ret = errors.Wrap(err, "Parsing record")
			continue
		}

		if err = cr.DeleteBody(); err != nil {
			ret = err
		}

		if err = cr.NotifyPR(); err != nil {
			ret = err
		}
	}

	return ret
}

// DeleteBody delete's the release's body.
func (cr ChangelogRequest) DeleteBody() error {
	client, err := GetInstallationClient(cr.User, cr.Repo)
	if err != nil {
		return errors.Wrap(err, "Installation client")
	}

	rel, _, err := client.Repositories.GetReleaseByTag(Ctx, cr.User, cr.Repo, cr.Tag)
	if err != nil {
		return errors.Wrap(err, "Getting release")
	}

	if b := rel.GetBody(); b != "" && b != WIPMessage {
		return errors.New("Release already has a custom body")
	}

	rel.Body = nil
	_, _, err = client.Repositories.EditRelease(Ctx, cr.User, cr.Repo, rel.GetID(), rel)
	if err != nil {
		return errors.Wrap(err, "Edit release")
	}

	return nil
}

// NotifyPR adds a comment to the registry PR indicating that changelog generation failed.
func (cr ChangelogRequest) NotifyPR() error {
	client, err := GetInstallationClient(cr.PR.User, cr.PR.Repo)
	if err != nil {
		return errors.Wrap(err, "Installation client")
	}

	c := &github.IssueComment{Body: github.String(FailureMsg)}
	_, _, err = client.Issues.CreateComment(Ctx, cr.PR.User, cr.PR.Repo, cr.PR.Number, c)
	if err != nil {
		return errors.Wrap(err, "Creating comment")
	}

	return nil
}

// ToHTTP converts a Lambda request to an HTTP request.
func (r Request) ToHTTP() *http.Request {
	req := &http.Request{
		Method: r.Method,
		Body:   ioutil.NopCloser(strings.NewReader(r.Body)),
	}
	for k, v := range r.Headers {
		req.Header.Add(k, v)
	}
	return req
}

// GetInstallationClient returns a client that can be used to interact with an installation.
func GetInstallationClient(owner, name string) (*github.Client, error) {
	i, resp, err := AppClient.Apps.FindRepositoryInstallation(Ctx, owner, name)
	if err != nil {
		if resp.StatusCode == http.StatusNotFound {
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
