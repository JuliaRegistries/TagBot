package main

import (
	"io/ioutil"
	"strconv"
	"testing"
)

func TestLambdaToHttp(t *testing.T) {
	lr := LambdaRequest{"POST", map[string]string{"foo": "bar", "bar": "baz"}, "abc"}
	r, err := LambdaToHttp(lr)
	if err != nil {
		t.Fatalf("Expected err = nil, got %v", err)
	}

	if r.Method != "POST" {
		t.Errorf("Expected method = 'POST', got '%s'", r.Method)
	}

	if n := len(r.Header); n != 2 {
		t.Errorf("Expected length of headers = 2, got %d", n)
	}
	if h := r.Header.Get("foo"); h != "bar" {
		t.Errorf("Expected 'foo' header = 'bar', got '%s'", h)
	}
	if h := r.Header.Get("bar"); h != "baz" {
		t.Errorf("Expected 'bar' header = 'baz', got '%s'", h)
	}

	if b, err := ioutil.ReadAll(r.Body); err != nil {
		t.Errorf("Expected err = nil, got '%v'", err)
	} else if string(b) != "abc" {
		t.Errorf("Expected body = 'abc', got %s", b)
	}
}

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
