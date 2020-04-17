package main

import (
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// IsActionEnabled checks whether or not TagBot is enabled as a GitHub Action.
func IsActionEnabled(user, repo string) (bool, error) {
	dest, err := ioutil.TempDir("", "")
	if err != nil {
		return false, err
	}

	cmd := exec.Command(
		"git", "clone", fmt.Sprintf("https://github.com/%s/%s", user, repo), dest,
		"--depth", "1",
	)
	if bs, err := cmd.CombinedOutput(); err != nil {
		s := string(bs)
		log.Println(s)
		if strings.Contains(s, "No space left on device") {
			err = ErrNoSpace
		}
		return false, err
	}
	defer os.RemoveAll(dest)

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
