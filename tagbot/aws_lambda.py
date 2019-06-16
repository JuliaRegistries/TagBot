import boto3
import json

from typing import Union

from . import env
from .context import Context


class Lambda:
    """Allows invocation of AWS Lambda functions."""

    _lambda = boto3.client("lambda")
    _function_prefix = env.lambda_function_prefix

    def invoke(self, fn: str, msg: Union[dict, Context]) -> None:
        """Invoke an AWS Lambda function."""
        if isinstance(msg, Context):
            msg = msg.__dict__
        self._lambda.invoke(
            FunctionName=self._function(fn),
            InvocationType="Event",
            Payload=json.dumps(msg),
        )

    def _function(self, fn: str) -> str:
        """Get a Lambda function name."""
        return self._function_prefix + fn
