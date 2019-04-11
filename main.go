package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"regexp"
	"strconv"

	"tag-bot/ghinstallation"

	"github.com/google/go-github/v24/github"
)

var (
	pemFile             = os.Getenv("PRIVATE_KEY_FILE")
	registratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	registryBranch      = os.Getenv("REGISTRY_BRANCH")
	webhookSecret       = []byte(os.Getenv("WEBHOOK_SECRET"))
	repoRegex           = regexp.MustCompile("Repository: (.*)")
	repoPiecesRegex     = regexp.MustCompile("https://github.com/(.*)/(.*)")
	versionRegex        = regexp.MustCompile("Version: (v.*)")
	commitSHARegex      = regexp.MustCompile("Commit SHA: (.*)")
	ctx                 = context.Background()
	client              *github.Client
)

// webhook responds to webhook events.
func handleWebhook(w http.ResponseWriter, r *http.Request) {
	// Respond to the request right away, since it doesn't actually matter what we send back.
	w.WriteHeader(200)

	// Validate the payload with our webhook secret.
	payload, err := github.ValidatePayload(r, webhookSecret)
	if err != nil {
		log.Println("Payload validation:", err)
		return
	}

	// Parse the event.
	event, err := github.ParseWebHook(github.WebHookType(r), payload)
	if err != nil {
		log.Println("Payload parsing:", err)
		return
	}

	// React to the event.
	pre, ok := event.(*github.PullRequestEvent)
	if !ok {
		log.Println("Unknown event type")
		return
	}
	handlePullRequestEvent(pre)
}

// handlePullRequestEvent handles pull request merges.
func handlePullRequestEvent(pre *github.PullRequestEvent) {
	pr := pre.GetPullRequest()
	u := pr.GetUser()
	body := pr.GetBody()

	// Check that the event is a PR merge.
	if pre.GetAction() != "closed" || !pr.GetMerged() {
		log.Println("Not a merge event")
		return
	}

	// Check that the PR creator is Registrator.
	if u.GetLogin() != registratorUsername {
		log.Println("PR not created by Registrator")
		return
	}

	// Check that the base branch is the default.
	if pr.GetBase().GetRef() != registryBranch {
		log.Println("Base branch is not the default")
		return
	}

	// Get the repository URL.
	match := repoRegex.FindStringSubmatch(body)
	if match == nil {
		log.Println("No repo regex match")
		return
	}
	repoURL := match[1]
	log.Println("Extracted repo URL:", repoURL)

	// Get the repository owner and name.
	match = repoPiecesRegex.FindStringSubmatch(repoURL)
	if match == nil {
		log.Println("No repo pieces regex match")
		return
	}
	owner, name := match[1], match[2]
	log.Println("Extracted repo owner:", owner)
	log.Println("Extracted repo name:", name)

	// Get the package version.
	match = versionRegex.FindStringSubmatch(body)
	if match == nil {
		log.Println("No version regex match")
		return
	}
	version := match[1]
	log.Println("Extracted package version:", version)

	// Get the release commit SHA.
	match = commitSHARegex.FindStringSubmatch(body)
	if match == nil {
		log.Println("No commit SHA regex match")
		return
	}
	sha := match[1]
	log.Println("Extracted commit SHA:", sha)

	// Create the release
	release := &github.RepositoryRelease{TagName: &version, TargetCommitish: &sha}
	if _, _, err := client.Repositories.CreateRelease(ctx, owner, name, release); err != nil {
		log.Println("Creating release failed:", err)
		return
	}

	log.Printf("Created release %s for %s/%s at %s\n", version, owner, name, sha)
}

func init() {
	appID, err := strconv.Atoi(os.Getenv("APP_ID"))
	if err != nil {
		log.Fatal("App ID:", err)
	}

	installationID, err := strconv.Atoi(os.Getenv("INSTALLATION_ID"))
	if err != nil {
		log.Fatal("Installation ID:", err)
	}

	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, appID, installationID, pemFile)
	if err != nil {
		log.Fatal("Transport:", err)
	}

	client = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	http.HandleFunc("/webhook", handleWebhook)
	log.Fatal(http.ListenAndServe(":"+os.Getenv("PORT"), nil))
}
