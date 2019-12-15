import subprocess

from datetime import timedelta
from typing import Optional

DELTA = timedelta(days=3)
STATUS = 0


class Abort(Exception):
    pass


def debug(msg: str) -> None:
    """Write a debug message, which only shows up if the user opts into them."""
    print(f"::debug ::{msg}")


def info(msg: str) -> None:
    """Write an info message."""
    print(msg)


def warn(msg: str) -> None:
    """Write a warning message."""
    print(f"::warning ::{msg}")


def error(msg: str) -> None:
    """Write an error message, and set the exit code to be non-zero."""
    global STATUS
    STATUS += 1
    print(f"::error ::{msg}")


def git(*argv: str, repo: Optional[str] = None) -> str:
    """Run a Git command."""
    args = ["git"]
    if repo:
        args.extend(["-C", repo])
    args.extend(argv)
    cmd = " ".join(args)
    debug(f"Running {cmd}")
    p = subprocess.run(args, capture_output=True)
    out = p.stdout.decode("utf-8")
    if p.returncode:
        if out:
            info(out)
        if p.stderr:
            info(p.stderr.decode("utf-8"))
        raise Abort(f"Git command '{cmd}' failed")
    return out.strip()
