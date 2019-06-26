import boto3
import json
import time

from typing import Optional, Union

from .. import Context, env, stages


class AWS:
    """Provides access to AWS."""

    _dynamodb = boto3.client("dynamodb")
    _function_prefix = env.lambda_function_prefix
    _lambda = boto3.client("lambda")
    _table_name = env.dynamodb_table_name

    def invoke(self, fn: str, msg: Union[dict, Context]) -> None:
        """Invoke an AWS Lambda function."""
        if isinstance(msg, Context):
            msg = msg.__dict__
        self._lambda.invoke(
            FunctionName=self._function(fn),
            InvocationType="Event",
            Payload=json.dumps(msg),
        )

    def invoke_notify(self, ctx: Context, notification: str):
        """Invokes the notify function."""
        ctx.notification = notification
        self.invoke(stages.notify, ctx)

    def _function(self, fn: str) -> str:
        """Get a Lambda function name."""
        return self._function_prefix + fn

    def get_item(self, key: int) -> Optional[str]:
        """Retrieve a stored item if it exists."""
        resp = self._dynamodb.get_item(
            TableName=self._table_name, Key={"id": {"N": key}}
        )
        return None if "Item" not in resp else resp["Item"]["val"]["S"]

    def put_item(self, key: int, val: str) -> None:
        """Store an item."""
        ttl = round(time.time() * 1000)
        self._dynamodb.put_item(
            TableName=self._table_name,
            Item={"id": {"N": key}, "val": {"S": val}, "ttl": {"N": ttl}},
        )
