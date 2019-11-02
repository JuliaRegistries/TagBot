import itertools
import re
import subprocess
import tempfile

from typing import List, Optional

from . import env

GCG_BIN = "github_changelog_generator"
RE_ACK = re.compile(r"(?i).*this changelog was automatically generated.*")
RE_COMPARE = re.compile(r"(?i)\[full changelog\]\((.*)/compare/(.*)\.\.\.(.*)\)")
RE_NUMBER = re.compile(r"\[\\#(\d+)\]\(.+?\)")
RE_SECTION_HEADER = re.compile(r"^## \[.*\]\(.*\) \(.*\)$")
EXCLUDE_LABELS = [
    "changelog skip",
    "duplicate",
    "exclude from changelog",
    "invalid",
    "no changelog",
    "question",
    "wont fix",
]


def get_changelog(version: str) -> Optional[str]:
    """Generate a changelog for the new version."""
    output = run_generator()
    section = find_section(output, version)
    if not section:
        return None
    return format_section(section)


def run_generator() -> str:
    """Run the generator CLI."""
    user, project = env.REPO.split("/")
    args = ["--user", user, "--project", project, "--token", env.TOKEN]
    _, output = tempfile.mkstemp()
    args.extend(["--output", output])
    args.extend(["--header-label", ""])
    args.extend(["--breaking-labels", ""])
    args.extend(["--bug-labels", ""])
    args.extend(["--deprecated-labels", ""])
    args.extend(["--enhancement-labels", ""])
    args.extend(["--removed-labels", ""])
    args.extend(["--security-labels", ""])
    args.extend(["--summary-labels", ""])
    args.extend(["--exclude-labels", exclude_labels()])
    subprocess.run([GCG_BIN, *args], check=True)
    with open(output) as f:
        return f.read()


def find_section(output: str, version: str) -> Optional[str]:
    """Search for a single release's section in the generated changelog."""
    lines = output.split("\n")
    start = None
    in_section = False
    this_version = re.compile(f"\\[{version}\\]")
    for i, line in enumerate(lines):
        if RE_SECTION_HEADER.search(line):
            if in_section:
                stop = i
                break
            elif this_version.search(line):
                start = i
                in_section = True
    else:
        stop = i
    if start is None:
        print("Section was not found")
        return None
    return "\n".join(lines[start:stop]).strip()


def format_section(section: str) -> str:
    """Format the release changelog."""
    section = RE_NUMBER.sub("(#\\1)", section)
    section = RE_ACK.sub("", section)
    section = RE_COMPARE.sub("[Diff since \\2](\\1/compare/\\2...\\3)", section)
    return section.strip()


def exclude_labels() -> str:
    """Compute the labels to be excluded from sections."""
    perms = [permutations(s) for s in EXCLUDE_LABELS]
    return ",".join(set(itertools.chain.from_iterable(perms)))


def permutations(s: str) -> List[str]:
    """Compute a bunch of different forms of the same string."""
    s = " ".join(w.capitalize() for w in s.split())
    hyphens = s.replace(" ", "-")
    underscores = s.replace(" ", "_")
    compressed = s.replace(" ", "")
    combined = [s, hyphens, underscores, compressed]
    return list({*combined, *[s.lower() for s in combined]})
