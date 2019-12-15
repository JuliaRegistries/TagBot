import itertools
import re
import subprocess

from datetime import datetime
from tempfile import mkstemp
from typing import List, Optional

from github import Github

from . import DELTA, debug, info, warn


# https://github.com/github-changelog-generator/github-changelog-generator/blob/v1.15.0/lib/github_changelog_generator/generator/section.rb#L88-L102
ESCAPED = ["\\", "<", ">", "*", "_", "(", ")", "[", "]", "#"]
GCG_BIN = "github_changelog_generator"
RE_ACK = re.compile(r"(?i).*this changelog was automatically generated.*")
RE_COMPARE = re.compile(r"(?i)\[full changelog\]\((.*)/compare/(.*)\.\.\.(.*)\)")
RE_CUSTOM = re.compile("(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->")
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


def get_changelog(
    *, name: str, registry: str, repo: str, token: str, uuid: str, version: str
) -> Optional[str]:
    """Generate a changelog for the new version."""
    debug("Looking up custom release notes")
    custom = _custom_notes(
        name=name, registry=registry, token=token, uuid=uuid, version=version
    )
    if custom:
        info("Found custom release notes")
        return custom
    debug("Running changelog generator")
    output = _run_generator(repo, token)
    debug(f"Output:\n{output}")
    section = _find_section(output, version)
    if not section:
        warn(f"Changelog generation failed (couldn't find section for {version})")
        return None
    return _format_section(section)


def _custom_notes(
    *, name: str, registry: str, token: str, uuid: str, version: str
) -> Optional[str]:
    """Look up a version's custom release notes."""
    gh = Github(token)
    r = gh.get_repo(registry, lazy=True)
    prs = r.get_pulls(state="closed")
    now = datetime.now()
    head = f"registrator/{name.lower()}/{uuid[:8]}/{version}"
    body = None
    for pr in prs:
        if pr.merged and pr.head.ref == head:
            body = pr.body
            break
        if now - pr.closed_at > DELTA:
            break
    if not body:
        warn("No registry pull request was found for this version")
        return None
    m = RE_CUSTOM.search(body)
    # Remove the '> ' at the beginning of each line.
    return "\n".join(l[2:] for l in m[1].splitlines()).strip() if m else None


def _run_generator(repo: str, token: str) -> str:
    """Run the generator CLI."""
    user, project = repo.split("/")
    args = ["--user", user, "--project", project, "--token", token]
    _, output = mkstemp(prefix="tagbot_changelog_")
    args.extend(["--output", output])
    args.extend(["--header-label", ""])
    args.extend(["--breaking-labels", ""])
    args.extend(["--bug-labels", ""])
    args.extend(["--deprecated-labels", ""])
    args.extend(["--enhancement-labels", ""])
    args.extend(["--removed-labels", ""])
    args.extend(["--security-labels", ""])
    args.extend(["--summary-labels", ""])
    args.extend(["--exclude-labels", _exclude_labels()])
    debug(f"Command: {GCG_BIN} {' '.join(args)}")
    subprocess.run([GCG_BIN, *args], check=True)
    with open(output) as f:
        return f.read()


def _find_section(output: str, version: str) -> Optional[str]:
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
        warn("Changelog section was not found")
        return None
    return "\n".join(lines[start:stop]).strip()


def _format_section(section: str) -> str:
    """Format the release changelog."""
    section = RE_NUMBER.sub("(#\\1)", section)
    section = RE_ACK.sub("", section)
    section = RE_COMPARE.sub("[Diff since \\2](\\1/compare/\\2...\\3)", section)
    for e in ESCAPED:
        section = section.replace(f"\\{e}", e)
    return section.strip()


def _exclude_labels() -> str:
    """Compute the labels to be excluded from sections."""
    perms = [_permutations(s) for s in EXCLUDE_LABELS]
    return ",".join(set(itertools.chain.from_iterable(perms)))


def _permutations(s: str) -> List[str]:
    """Compute a bunch of different forms of the same string."""
    s = " ".join(w.capitalize() for w in s.split())
    hyphens = s.replace(" ", "-")
    underscores = s.replace(" ", "_")
    compressed = s.replace(" ", "")
    combined = [s, hyphens, underscores, compressed]
    return list({*combined, *[s.lower() for s in combined]})
