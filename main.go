package main

import (
	"log"
	"net/http"
	"os"
	"strconv"

	"tag-bot/ghinstallation"

	"github.com/google/go-github/v24/github"
)

var (
	pemFile        = os.Getenv("PRIVATE_KEY_FILE")
	webhookSecret  = os.Getenv("WEBHOOK_SECRET")
	appID          int
	installationID int
	client         *github.Client
)

// webhook responds to webhook events.
func webhook(w http.ResponseWriter, r *http.Request) {

}

func init() {
	var err error
	if appID, err = strconv.Atoi(os.Getenv("APP_ID")); err != nil {
		log.Fatal("AppID:", err)
	}
	if installationID, err = strconv.Atoi(os.Getenv("INSTALLATION_ID")); err != nil {
		log.Fatal("InstallationID:", err)
	}
	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, appID, installationID, pemFile)
	if err != nil {
		log.Fatal(err)
	}
	client = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	http.HandleFunc("/webhook", webhook)
	log.Fatal(http.ListenAndServe(":"+os.Getenv("PORT"), nil))
}
