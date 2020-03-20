package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"

	"github.com/bradleyfalzon/ghinstallation"
	"github.com/google/go-github/v30/github"
)

var (
	WebhookSecret = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))
	PemFile       = os.Getenv("GITHUB_PEM")

	Ctx = context.Background()

	AppID     int64
	Port      int
	AppClient *github.Client
)

func init() {
	// Load the app ID from the environment.
	app, err := strconv.Atoi(os.Getenv("GITHUB_APP_ID"))
	if err != nil {
		log.Fatal("App ID:", err)
	}
	AppID = int64(app)

	// Load the port number.
	Port, err = strconv.Atoi(os.Getenv("PORT"))
	if err != nil {
		log.Fatal("Port:", err)
	}

	// Load the private GitHub key for our app.
	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, int64(AppID), PemFile)
	if err != nil {
		log.Fatal("Transport:", err)
		return
	}
	AppClient = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	http.HandleFunc("/github", HandleWebhook)
	http.ListenAndServe(":"+strconv.Itoa(Port), nil)
}

// HandleWebhook handles events from SQS.
func HandleWebhook(w http.ResponseWriter, r *http.Request) {
	payload, err := github.ValidatePayload(r, WebhookSecret)
	if err != nil {
		log.Println("Validating payload:", err)
		return
	}

	event, err := github.ParseWebHook(github.WebHookType(r), payload)
	if err != nil {
		log.Println("Parsing payload:", err)
		return
	}

	id := github.DeliveryID(r)
	log.Println("Delivery ID:", id)

	switch event.(type) {
	case *github.PullRequestEvent:
		err = HandlePullRequest(event.(*github.PullRequestEvent), id)
	case *github.IssueCommentEvent:
		err = HandleIssueComment(event.(*github.IssueCommentEvent), id)
	default:
		err = fmt.Errorf("Unknown event type: %s", github.WebHookType(r))
	}

	log.Println("Error:", err)
}
