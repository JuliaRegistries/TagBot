import boto3
import json

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

    def get_changelog(self, id: str) -> Optional[str]:
        """Retrieve a stored changelog if it exists."""
        pass  # TODO

    def put_changelog(self, id: str, changelog: str) -> None:
        """Store a changelog."""
        pass  # TODO
