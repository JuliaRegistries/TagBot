import os.path

from tagbot import resources


def test_resource():
    assert resources.resource("foo") == os.path.join(resources._dir, "foo")
