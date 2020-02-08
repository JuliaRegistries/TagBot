package main

import (
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const DeprecationNotice = `
---

### IMPORTANT: TagBot as a GitHub App is deprecated

[TagBot as a GitHub App is deprecated](https://github.com/apps/julia-tagbot); you should now migrate to [TagBot as a GitHub Action](https://github.com/marketplace/actions/julia-tagbot).
Your repository should have received a pull request doing this for you, but if you did not receive this pull request, then see [here](https://github.com/marketplace/actions/julia-tagbot#setup) for instructions.
For more information about this deprecation, please see [this Discourse post](https://discourse.julialang.org/t/ann-the-tagbot-github-app-is-deprecated-in-favour-of-the-tagbot-github-action/34344).
`

// IsActionEnabled checks whether or not TagBot is enabled as a GitHub Action.
func IsActionEnabled(user, repo, sha string) (bool, error) {
	dest, err := ioutil.TempDir("", "")
	if err != nil {
		return false, err
	}

	cmd := exec.Command("git", "clone", fmt.Sprintf("https://github.com/%s/%s", user, repo), dest)
	if err = cmd.Run(); err != nil {
		return false, err
	}
	if err := exec.Command("git", "-C", dest, "checkout", sha).Run(); err != nil {
		return false, err
	}

	dir := filepath.Join(dest, ".github", "workflows")
	fs, err := ioutil.ReadDir(dir)
	if os.IsNotExist(err) {
		return false, nil
	} else if err != nil {
		return false, err
	}

	for _, f := range fs {
		bs, err := ioutil.ReadFile(filepath.Join(dir, f.Name()))
		if err != nil {
			return false, err
		}
		if strings.Contains(string(bs), "uses: JuliaRegistries/TagBot") {
			return true, nil
		}
	}

	return false, nil
}
