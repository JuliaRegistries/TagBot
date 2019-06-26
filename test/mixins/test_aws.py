import json

from unittest.mock import Mock

from tagbot import Context, stages
from tagbot.mixins import AWS

mixin = AWS()
mixin._function_prefix = "prefix-"
mixin._lambda.invoke = Mock()


def test_invoke():
    mixin.invoke("fun", {"foo": "bar"})
    mixin._lambda.invoke.assert_called_once_with(
        FunctionName="prefix-fun", InvocationType="Event", Payload='{"foo": "bar"}'
    )
    mixin._lambda.invoke.reset_mock()


def test_invoke_notify():
    ctx = Context(
        registry="foo/bar",
        repo="bar/foo",
        version="v0.1.2",
        commit="abc",
        issue=1,
        id="id",
    )
    copied = Context(**ctx.__dict__.copy())
    copied.notification = "notification"
    mixin.invoke_notify(ctx, "notification")
    mixin._lambda.invoke.assert_called_once_with(
        FunctionName=f"prefix-{stages.notify}",
        InvocationType="Event",
        Payload=json.dumps(copied.__dict__),
    )
    # TODO: This is kind of an undesired side effect.
    assert ctx.notification == "notification"


def test_function():
    assert mixin._function("foo") == "prefix-foo"
