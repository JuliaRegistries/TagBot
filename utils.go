package main

import (
	"net/http"
	"strings"

	"github.com/bradleyfalzon/ghinstallation"
	"github.com/google/go-github/v30/github"
)

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

	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, AppID, i.GetID(), PemFile)
	if err != nil {
		return nil, err
	}

	return github.NewClient(&http.Client{Transport: tr}), nil
}

// PreprocessBody preprocesses a GitHub body from a PR or comment.
func PreprocessBody(body string) string {
	return strings.TrimSpace(strings.Replace(body, "\r\n", "\n", -1))
}
