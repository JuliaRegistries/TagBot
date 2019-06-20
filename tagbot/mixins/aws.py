import boto3
import json
import time

from typing import Optional, Union

from .. import env
from ..context import Context
from ..enums import stages


class AWS:
    """Provides access to AWS Lambda and DynamoDB."""

    _lambda = boto3.client("lambda")
    _dynamodb = boto3.client("dynamodb")
    _function_prefix = env.lambda_function_prefix
    _table = env.dynamodb_table_name

    def invoke_function(self, fn: str, msg: Union[dict, Context]) -> None:
        """Invoke an AWS Lambda function."""
        if isinstance(msg, Context):
            msg = msg.__dict__
        msg["stage"] = fn
        self._lambda.invoke(
            FunctionName=self._function(fn),
            InvocationType="Event",
            Payload=json.dumps(msg),
        )

    def invoke_notify(self, ctx: Context, notification: str):
        """Invokes the notify function."""
        ctx.notification = notification
        self.invoke_function(stages.notify, ctx)

    def get_item(self, key: str) -> Optional[str]:
        resp = self._dynamodb.get_item(
            TableName=self._table, Key={"id": {"S": key}}, AttributesToGet=["val"]
        )
        return resp["Item"]["val"]["S"] if "Item" in resp else None

    def put_item(self, key: str, val: str) -> None:
        expires_at = int(time.time()) + 7200  # 2 hours.
        self._dynamodb.put_item(
            TableName=self._table,
            Item={"id": {"S": key}, "ttl": {"N": expires_at}, "val": {"S": val}},
        )

    def _function(self, fn: str) -> str:
        """Get a Lambda function name."""
        return self._function_prefix + fn
