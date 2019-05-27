package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
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
	PemName = "tag-bot.pem"
	GPGDir  = "gnupg"
)

var (
	WebhookSecret = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))

	Ctx          = context.Background()
	ResourcesTar = filepath.Join("github", "bin", "resources.tar")
	IsSetup      = false

	ResourcesDir string
	AppID        int
	AppClient    *github.Client
	SQS          *sqs.SQS
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
	req := r.toHTTP()

	payload, err := github.ValidatePayload(req, WebhookSecret)
	if err != nil {
		return errors.Wrap(err, "Validating payload")
	}

	event, err := github.ParseWebHook(github.WebHookType(req), payload)
	if err != nil {
		return errors.Wrap(err, "Parsing payload")
	}

	id := github.DeliveryID(req)
	fmt.Println("Delivery ID:", id)

	switch event.(type) {
	case *github.PullRequestEvent:
		return HandlePullRequest(event.(*github.PullRequestEvent), id)
	case *github.IssueCommentEvent:
		return HandleIssueComment(event.(*github.IssueCommentEvent), id)
	default:
		return fmt.Errorf("Unknown event type: %s", github.WebHookType(req))
	}
}

// HandleSQS handles events from SQS.
func (r Request) HandleSQS() error {
	var ret error

	for _, r := range r.Records {
		var cr ChangelogRequest
		if err := json.Unmarshal([]byte(r.Body), &cr); err != nil {
			ret = errors.Wrap(err, "Parsing record")
			continue
		}

		if err := cr.Receive(); err != nil {
			ret = err
		}
	}

	return ret
}

// toHTTP converts a Lambda request to an HTTP request.
func (r Request) toHTTP() *http.Request {
	req := &http.Request{
		Method: r.Method,
		Body:   ioutil.NopCloser(strings.NewReader(r.Body)),
		Header: make(http.Header),
	}
	for k, v := range r.Headers {
		req.Header.Add(k, v)
	}
	return req
}
