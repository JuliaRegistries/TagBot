import hmac
import json
import os
import sys

from . import env
from . import get_in
from .sns import SNS


class Handler(SNS):
    """
    Handles webhook payloads from GitHub.
    Nothing happens here except signature validation, because we can't retry.
    The request body is forwarded to another stage without modification.
    """

    _secret = env.webhook_secret
    _topic = "prepare"

    def __init__(self, evt):
        self.body = evt.get("body", "")
        self.id, self.type, self.sha = [
            get_in(evt, "headers", k, default="")
            for k in ["X-GitHub-Delivery", "X-GitHub-Event", "X-Hub-Signature"]
        ]

    def do(self):
        if not self._verify_signature():
            return {"statusCode": 400}
        message = {"id": self.id, "type": self.type, "body": json.loads(self.body)}
        json.dump(message, sys.stdout, indent=2)
        self.publish(self._topic, message)
        return {"statusCode": 200}

    def _verify_signature(self):
        """Verify that a webhook payload comes from GitHub."""
        if "=" not in self.sha:
            return False
        alg, sig = self.sha.split("=")
        if alg != "sha1":
            return False
        mac = hmac.new(bytes(self._secret, "utf-8"), self.body.encode("utf-8"), "sha1")
        return hmac.compare_digest(mac.hexdigest(), self.sig)


def handler(evt, _ctx):
    Handler(evt).do()
