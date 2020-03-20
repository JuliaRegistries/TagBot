package main

import (
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
