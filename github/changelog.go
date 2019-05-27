package main

import (
	"encoding/json"
	"os"

	"github.com/aws/aws-sdk-go/service/sqs"
	"github.com/google/go-github/v25/github"
	"github.com/pkg/errors"
)

const FailureMsg = "I tried to create a changelog but failed, you may want to edit the release yourself."

var SQSQueue = os.Getenv("SQS_QUEUE")

// ChangelogRequest gets sent to or received from SQS.
type ChangelogRequest struct {
	User string `json:"user"`
	Repo string `json:"repo"`
	Tag  string `json:"tag"`
	Auth string `json:"auth"`
	PR   struct {
		User   string `json:"user"`
		Repo   string `json:"repo"`
		Number int    `json:"number"`
	} `json:"pr"`
}

// Send sends a changelog request to SQS.
func (cr ChangelogRequest) Send() error {
	if SQS == nil {
		return ErrNoSQSClient
	}

	b, err := json.Marshal(cr)
	if err != nil {
		return errors.Wrap(err, "Encoding queue input")
	}

	body := string(b)

	_, err = SQS.SendMessage(&sqs.SendMessageInput{
		QueueUrl:    &SQSQueue,
		MessageBody: &body,
	})
	if err != nil {
		return errors.Wrap(err, "Sending queue message")
	}

	return nil
}

// Receive handles a request received from SQS.
func (cr ChangelogRequest) Receive() error {
	var ret error

	if err := cr.deleteBody(); err != nil {
		ret = err
	}

	if err := cr.notifyPR(); err != nil {
		ret = err
	}

	return ret
}

// deleteBody delete's the release's body.
func (cr ChangelogRequest) deleteBody() error {
	client, err := GetInstallationClient(cr.User, cr.Repo)
	if err != nil {
		return errors.Wrap(err, "Installation client")
	}

	rel, _, err := client.Repositories.GetReleaseByTag(Ctx, cr.User, cr.Repo, cr.Tag)
	if err != nil {
		return errors.Wrap(err, "Getting release")
	}

	if b := rel.GetBody(); b != "" && b != WIPMessage {
		return ErrCustomBody
	}

	rel.Body = nil
	_, _, err = client.Repositories.EditRelease(Ctx, cr.User, cr.Repo, rel.GetID(), rel)
	if err != nil {
		return errors.Wrap(err, "Edit release")
	}

	return nil
}

// notifyPR adds a comment to the registry PR indicating that changelog generation failed.
func (cr ChangelogRequest) notifyPR() error {
	client, err := GetInstallationClient(cr.PR.User, cr.PR.Repo)
	if err != nil {
		return errors.Wrap(err, "Installation client")
	}

	c := &github.IssueComment{Body: github.String(FailureMsg)}
	_, _, err = client.Issues.CreateComment(Ctx, cr.PR.User, cr.PR.Repo, cr.PR.Number, c)
	if err != nil {
		return errors.Wrap(err, "Creating comment")
	}

	return nil
}
