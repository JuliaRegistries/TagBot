package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"sort"
	"strings"

	"github.com/bradleyfalzon/ghinstallation"
	"github.com/google/go-github/github"
)

var (
	AppID   = flag.Int("app", 0, "GitHub App ID")
	PemFile = flag.String("pem", "", "GitHub App private key file")

	Ctx       = context.Background()
	AppClient *github.Client
)

type Install struct {
	Name  string
	All   bool
	Repos []string
}

func init() {
	flag.Parse()
	if *AppID == 0 {
		log.Fatal("App ID is not set (-app)")
	}
	if *PemFile == "" {
		log.Fatal("Private key file is not set (-pem)")
	}

	tr, err := ghinstallation.NewAppsTransportKeyFromFile(http.DefaultTransport, *AppID, *PemFile)
	if err != nil {
		log.Fatal("Transport:", err)
	}
	AppClient = github.NewClient(&http.Client{Transport: tr})
}

func main() {
	installs, err := getInstalls()
	if err != nil {
		log.Fatal(err)
	}

	for _, i := range installs {
		fmt.Print(i.Name, ":")
		if i.All {
			fmt.Println(" All")
		} else if len(i.Repos) == 0 {
			fmt.Println(" None")
		} else {
			fmt.Println()
			for _, r := range i.Repos {
				fmt.Println("  -", r)
			}
		}
	}

	fmt.Println("Total installs:", len(installs))
}

// getInstalls gets all of the app's installs.
func getInstalls() ([]Install, error) {
	opts := &github.ListOptions{}
	installs := []Install{}

	for {
		is, resp, err := AppClient.Apps.ListInstallations(Ctx, opts)
		if err != nil {
			return nil, err
		}

		for _, i := range is {
			install := Install{Name: i.GetAccount().GetLogin()}

			if i.GetRepositorySelection() == "all" {
				install.All = true
			} else {
				if install.Repos, err = getRepos(int(i.GetID())); err != nil {
					return nil, err
				}
			}

			installs = append(installs, install)
		}

		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}

	sort.Slice(installs, func(i, j int) bool {
		return strings.ToLower(installs[i].Name) < strings.ToLower(installs[j].Name)
	})

	return installs, nil
}

// getRepos gets the names of all repos accessible to an installation.
func getRepos(id int) ([]string, error) {
	tr, err := ghinstallation.NewKeyFromFile(http.DefaultTransport, *AppID, id, *PemFile)
	if err != nil {
		return nil, err
	}
	client := github.NewClient(&http.Client{Transport: tr})

	opts := &github.ListOptions{}
	repos := []string{}

	for {
		rs, resp, err := client.Apps.ListRepos(Ctx, opts)
		if err != nil {
			return nil, err
		}

		for _, r := range rs {
			repos = append(repos, r.GetName())
		}

		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}

	sort.Slice(repos, func(i, j int) bool {
		return strings.ToLower(repos[i]) < strings.ToLower(repos[j])
	})

	return repos, nil
}
