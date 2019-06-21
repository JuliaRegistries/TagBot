import os.path
import tarfile
import tempfile

_dir = tempfile.mkdtemp()


def resource(path: str) -> str:
    """Get the path to a resource file."""
    return os.path.join(_dir, path)


has_gpg = False
if os.path.isfile("resources.tar"):
    with tarfile.TarFile("resources.tar") as tf:
        tf.extractall(_dir)
    _gpg = resource("gnupg")
    if os.path.isdir(_gpg):
        has_gpg = True
        os.environ["GNUPGHOME"] = _gpg
    else:
        print("GPG signing is disabled")
else:
    print("Resources file was not found")
