import hmac
import json

from .. import env, stages
from ..mixins.aws import AWS


class Handler(AWS):
    """Handles webhook payloads from GitHub."""

    _secret = env.webhook_secret
    _next_step = stages.prepare

    def __init__(self, request: dict):
        self.body = request.get("body", "{}")
        headers = request.get("headers", {})
        self.id, self.type, self.sha = [
            headers.get(k, "")
            for k in ["X-GitHub-Delivery", "X-GitHub-Event", "X-Hub-Signature"]
        ]

    def do(self) -> dict:
        if not self._verify_signature():
            return {"statusCode": 400}
        message = {"id": self.id, "type": self.type, "payload": json.loads(self.body)}
        self.invoke(self._next_step, message)

        return {"statusCode": 200}

    def _verify_signature(self) -> bool:
        """Verify that a webhook payload comes from GitHub."""
        if "=" not in self.sha:
            return False
        alg, sig = self.sha.split("=")
        if alg != "sha1":
            return False
        mac = hmac.new(bytes(self._secret, "utf-8"), self.body.encode("utf-8"), "sha1")
        return hmac.compare_digest(mac.hexdigest(), sig)


def handler(request: dict, _ctx=None) -> None:
    Handler(request).do()