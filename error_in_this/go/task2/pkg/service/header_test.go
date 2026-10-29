package service

import "testing"

func TestBuildTagHeader(t *testing.T) {
    res := BuildTagHeader([]string{" golang ", "", "docker", "testing "})
    expected := "golang, docker, testing"
    if res != expected {
        t.Errorf("expected '%s', got '%s'", expected, res)
    }
}