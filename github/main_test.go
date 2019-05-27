package main

import (
	"io/ioutil"
	"testing"
)

func TestToHTTP(t *testing.T) {
	r := Request{
		Method:  "POST",
		Headers: map[string]string{"foo": "bar", "bar": "baz"},
		Body:    "abc",
	}.toHTTP()

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
