import os
import tarfile
import tempfile


def resource(path: str) -> str:
    """Get the path to a resource file."""
    return os.path.join(_dir, path)


has_gpg = False
_link = os.path.join(tempfile.gettempdir(), "tagbot-resources")
if os.path.islink(_link):
    _dir = os.readlink(_link)
else:
    _dir = tempfile.mkdtemp(prefix="tagbot-resources-")
    os.symlink(_dir, _link)
    if os.path.isfile("resources.tar"):
        with tarfile.TarFile("resources.tar") as tf:
            tf.extractall(_dir)
    else:
        print("Resources file was not found")
_gpg = resource("gnupg")
if os.path.isdir(_gpg):
    has_gpg = True
    os.environ["GNUPGHOME"] = _gpg
else:
    print("GPG signing is disabled")
