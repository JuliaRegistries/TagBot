package main

import (
	"io/ioutil"
	"os"
	"strconv"
	"testing"
)

func TestPreprocessBody(t *testing.T) {
	cases := []string{
		"a \r\n b \r\n c",
		"\r\n a \r\n b \r\n c \r\n",
		"\n a \n b \n c \n",
		"a \n b \r\n c \n",
	}
	expected := "a \n b \n c"

	for i, in := range cases {
		if out := PreprocessBody(in); out != expected {
			t.Errorf("Case %d: Expected %s, got %s", i, strconv.Quote(expected), strconv.Quote(out))
		}
	}
}

func TestDoCmd(t *testing.T) {
	dir, err := ioutil.TempDir("", "")
	if err != nil {
		t.Skip("Temp dir:", err)
	}

	f, err := ioutil.TempFile(dir, "")
	if err != nil {
		t.Skip("Temp file:", err)
	}
	f.Close()

	path := f.Name()

	if err = DoCmd("rm", path); err != nil {
		t.Errorf("rm: Expected err == nil, got %v", err)
	}

	if _, err = os.Stat(path); !os.IsNotExist(err) {
		t.Errorf("stat: Expected os.IsNotExist(err), got %v", err)
	}

	if err = DoCmd("touch", path); err != nil {
		t.Errorf("touch: Expected err == nil, got %v", err)
	}

	if _, err = os.Stat(path); os.IsNotExist(err) {
		t.Errorf("stat: Expected !os.IsNotExist(err), got %v", err)
	}

}
