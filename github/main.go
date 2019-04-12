package main

import (
	"bytes"
	"context"
	"crypto/rsa"
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"sync"
	"time"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	jwt "github.com/dgrijalva/jwt-go"
	"github.com/google/go-github/github"
)

var (
	registratorUsername = os.Getenv("REGISTRATOR_USERNAME")
	registryBranch      = os.Getenv("REGISTRY_BRANCH")
	webhookSecret       = []byte(os.Getenv("GITHUB_WEBHOOK_SECRET"))
	repoRegex           = regexp.MustCompile("Repository: (.*)")
	repoPiecesRegex     = regexp.MustCompile("https://github.com/(.*)/(.*)")
	versionRegex        = regexp.MustCompile("Version: (v.*)")
	commitSHARegex      = regexp.MustCompile("Commit SHA: (.*)")
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
	tr, err := NewKeyFromFile(http.DefaultTransport, appID, installationID, pemFile)
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
	body := pr.GetBody()

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

	// Get the release commit SHA.
	match = commitSHARegex.FindStringSubmatch(body)
	if match == nil {
		return errors.New("No commit SHA regex match")
	}
	sha := match[1]
	log.Println("Extracted commit SHA:", sha)

	// Create the release.
	release := &github.RepositoryRelease{TagName: &version, TargetCommitish: &sha}
	if _, _, err := client.Repositories.CreateRelease(ctx, owner, name, release); err != nil {
		return err
	}

	log.Printf("Created release %s for %s/%s at %s\n", version, owner, name, sha)
	return nil
}

// The code below is not mine.
// https://github.com/wlynch/ghinstallation/tree/url-deprecation
// I should eventually figure out a nice way to include it but until then...

const (
	// acceptHeader is the GitHub Integrations Preview Accept header.
	acceptHeader = "application/vnd.github.machine-man-preview+json"
	apiBaseURL   = "https://api.github.com"
)

// transport.go starts here.

// Transport provides a http.RoundTripper by wrapping an existing
// http.RoundTripper and provides GitHub Apps authentication as an
// installation.
//
// Client can also be overwritten, and is useful to change to one which
// provides retry logic if you do experience retryable errors.
//
// See https://developer.github.com/apps/building-integrations/setting-up-and-registering-github-apps/about-authentication-options-for-github-apps/
type Transport struct {
	BaseURL        string            // baseURL is the scheme and host for GitHub API, defaults to https://api.github.com
	Client         Client            // Client to use to refresh tokens, defaults to http.Client with provided transport
	tr             http.RoundTripper // tr is the underlying roundtripper being wrapped
	integrationID  int               // integrationID is the GitHub Integration's Installation ID
	installationID int               // installationID is the GitHub Integration's Installation ID
	appsTransport  *AppsTransport

	mu    *sync.Mutex  // mu protects token
	token *accessToken // token is the installation's access token
}

// accessToken is an installation access token response from GitHub
type accessToken struct {
	Token     string    `json:"token"`
	ExpiresAt time.Time `json:"expires_at"`
}

var _ http.RoundTripper = &Transport{}

// NewKeyFromFile returns a Transport using a private key from file.
func NewKeyFromFile(tr http.RoundTripper, integrationID, installationID int, privateKeyFile string) (*Transport, error) {
	privateKey, err := ioutil.ReadFile(privateKeyFile)
	if err != nil {
		return nil, fmt.Errorf("could not read private key: %s", err)
	}
	return New(tr, integrationID, installationID, privateKey)
}

// Client is a HTTP client which sends a http.Request and returns a http.Response
// or an error.
type Client interface {
	Do(*http.Request) (*http.Response, error)
}

// New returns an Transport using private key. The key is parsed
// and if any errors occur the error is non-nil.
//
// The provided tr http.RoundTripper should be shared between multiple
// installations to ensure reuse of underlying TCP connections.
//
// The returned Transport's RoundTrip method is safe to be used concurrently.
func New(tr http.RoundTripper, integrationID, installationID int, privateKey []byte) (*Transport, error) {
	t := &Transport{
		tr:             tr,
		integrationID:  integrationID,
		installationID: installationID,
		BaseURL:        apiBaseURL,
		Client:         &http.Client{Transport: tr},
		mu:             &sync.Mutex{},
	}
	var err error
	t.appsTransport, err = NewAppsTransport(t.tr, t.integrationID, privateKey)
	if err != nil {
		return nil, err
	}
	return t, nil
}

// RoundTrip implements http.RoundTripper interface.
func (t *Transport) RoundTrip(req *http.Request) (*http.Response, error) {
	token, err := t.Token()
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "token "+token)
	req.Header.Add("Accept", acceptHeader) // We add to "Accept" header to avoid overwriting existing req headers.
	resp, err := t.tr.RoundTrip(req)
	return resp, err
}

// Token checks the active token expiration and renews if necessary. Token returns
// a valid access token. If renewal fails an error is returned.
func (t *Transport) Token() (string, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.token == nil || t.token.ExpiresAt.Add(-time.Minute).Before(time.Now()) {
		// Token is not set or expired/nearly expired, so refresh
		if err := t.refreshToken(); err != nil {
			return "", fmt.Errorf("could not refresh installation id %v's token: %s", t.installationID, err)
		}
	}

	return t.token.Token, nil
}

func (t *Transport) refreshToken() error {
	req, err := http.NewRequest("POST", fmt.Sprintf("%s/app/installations/%v/access_tokens", t.BaseURL, t.installationID), nil)
	if err != nil {
		return fmt.Errorf("could not create request: %s", err)
	}

	t.appsTransport.BaseURL = t.BaseURL
	t.appsTransport.Client = t.Client
	resp, err := t.appsTransport.RoundTrip(req)
	if err != nil {
		return fmt.Errorf("could not get access_tokens from GitHub API for installation ID %v: %v", t.installationID, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("received non 2xx response status %q when fetching %v", resp.Status, req.URL)
	}

	if err := json.NewDecoder(resp.Body).Decode(&t.token); err != nil {
		return err
	}

	return nil
}

// appsTransport.go starts here.

// AppsTransport provides a http.RoundTripper by wrapping an existing
// http.RoundTripper and provides GitHub Apps authentication as a
// GitHub App.
//
// Client can also be overwritten, and is useful to change to one which
// provides retry logic if you do experience retryable errors.
//
// See https://developer.github.com/apps/building-integrations/setting-up-and-registering-github-apps/about-authentication-options-for-github-apps/
type AppsTransport struct {
	BaseURL       string            // baseURL is the scheme and host for GitHub API, defaults to https://api.github.com
	Client        Client            // Client to use to refresh tokens, defaults to http.Client with provided transport
	tr            http.RoundTripper // tr is the underlying roundtripper being wrapped
	key           *rsa.PrivateKey   // key is the GitHub Integration's private key
	integrationID int               // integrationID is the GitHub Integration's Installation ID
}

// NewAppsTransportKeyFromFile returns a AppsTransport using a private key from file.
func NewAppsTransportKeyFromFile(tr http.RoundTripper, integrationID int, privateKeyFile string) (*AppsTransport, error) {
	privateKey, err := ioutil.ReadFile(privateKeyFile)
	if err != nil {
		return nil, fmt.Errorf("could not read private key: %s", err)
	}
	return NewAppsTransport(tr, integrationID, privateKey)
}

// NewAppsTransport returns a AppsTransport using private key. The key is parsed
// and if any errors occur the error is non-nil.
//
// The provided tr http.RoundTripper should be shared between multiple
// installations to ensure reuse of underlying TCP connections.
//
// The returned Transport's RoundTrip method is safe to be used concurrently.
func NewAppsTransport(tr http.RoundTripper, integrationID int, privateKey []byte) (*AppsTransport, error) {
	t := &AppsTransport{
		tr:            tr,
		integrationID: integrationID,
		BaseURL:       apiBaseURL,
		Client:        &http.Client{Transport: tr},
	}
	var err error
	t.key, err = jwt.ParseRSAPrivateKeyFromPEM(privateKey)
	if err != nil {
		return nil, fmt.Errorf("could not parse private key: %s", err)
	}
	return t, nil
}

// RoundTrip implements http.RoundTripper interface.
func (t *AppsTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	claims := &jwt.StandardClaims{
		IssuedAt:  time.Now().Unix(),
		ExpiresAt: time.Now().Add(time.Minute).Unix(),
		Issuer:    strconv.Itoa(t.integrationID),
	}
	bearer := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)

	ss, err := bearer.SignedString(t.key)
	if err != nil {
		return nil, fmt.Errorf("could not sign jwt: %s", err)
	}

	req.Header.Set("Authorization", "Bearer "+ss)
	req.Header.Set("Accept", acceptHeader)

	resp, err := t.tr.RoundTrip(req)
	return resp, err
}
