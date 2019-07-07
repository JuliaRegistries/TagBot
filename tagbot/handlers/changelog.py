import itertools
import re
import subprocess
import tempfile

from typing import List, Optional

from .. import Context, stages
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Generates a release changelog."""

    _gcg_bin = "github_changelog_generator"
    _next_stage = stages.release
    _re_ack = re.compile("(?i).*this changelog was automatically generated.*")
    _re_compare = re.compile("(?i)^\[full changelog\]\((.*)/compare/(.*)\.\.\.(.*)\)$")
    _re_number = re.compile("\[\\#(\d+)\]\(.+?\)")
    _re_section_header = re.compile("^## \[.*\]\(.*\) \(.*\)$")

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self) -> None:
        changelog = self._get_changelog()
        if not changelog:
            tag_exists = self.tag_exists(self.ctx.repo, self.ctx.version)
            changelog = self._generate_changelog(tag_exists)
        self.ctx.changelog = changelog
        self._put_changelog()
        self.invoke(self._next_stage, self.ctx)

    def _get_changelog(self) -> Optional[str]:
        """Get an existing changelog."""
        return self.get_item(self.ctx.issue)

    def _put_changelog(self) -> None:
        """Store a generated changelog."""
        if not self.ctx.changelog:
            print("Changelog is empty, not storing")
            return
        return self.put_item(self.ctx.issue, self.ctx.changelog)

    def _generate_changelog(self, tag_exists: bool):
        """Generate the release changelog."""
        output = self.__run_generator(tag_exists)
        section = self.__find_section(output)
        if not section:
            return None
        return self.__format_section(section)

    def __run_generator(self, tag_exists: bool):
        """Run the generator CLI."""
        user, project = self.ctx.repo.split("/")
        token = self.auth_token(self.ctx.repo)
        args = ["--user", user, "--project", project, "--token", token]
        _, output = tempfile.mkstemp()
        args.extend(["--output", output])
        if not tag_exists:
            args.extend(["--future-release", self.ctx.version])
        args.extend(["--header-label", ""])
        args.extend(["--breaking-labels", ""])
        args.extend(["--bug-labels", ""])
        args.extend(["--deprecated-labels", ""])
        args.extend(["--enhancement-labels", ""])
        args.extend(["--removed-labels", ""])
        args.extend(["--security-labels", ""])
        args.extend(["--summary-labels", ""])
        args.extend(["--exclude-labels", self.__exclude_labels()])
        subprocess.run([self._gcg_bin, *args], check=True)
        with open(output) as f:
            return f.read()

    def __find_section(self, output: str) -> Optional[str]:
        """Search for a single release's section in the generated changelog."""
        lines = output.split("\n")
        start = None
        in_section = False
        this_version = re.compile(f"\\[{self.ctx.version}\\]")
        for i, line in enumerate(lines):
            if self._re_section_header.search(line):
                if in_section:
                    stop = i
                    break
                elif this_version.search(line):
                    start = i
                    in_section = True
        if start is None:
            print("Section was not found")
            return None
        return "\n".join(lines[start:stop])

    def __format_section(self, section: str) -> str:
        """Format the release changelog."""
        section = self._re_number.sub("(#\\1)", section)
        section = self._re_ack.sub("", section)
        section = self._re_compare.sub(
            "[Diff since \\2](\\1/compare/\\2...\\3)", section
        )
        return section.strip()

    def __exclude_labels(self):
        """Compute the labels to be excluded from sections."""
        excludes = [
            "changelog skip",
            "duplicate",
            "exclude from changelog",
            "invalid",
            "no changelog",
            "question",
            "wont fix",
        ]
        perms = [self.__permutations(s) for s in excludes]
        return ",".join(set(itertools.chain.from_iterable(perms)))

    def __permutations(self, s: str) -> List[str]:
        """Compute a bunch of different forms of the same string."""
        s = " ".join(w.capitalize() for w in s.split())
        hyphens = s.replace(" ", "-")
        underscores = s.replace(" ", "_")
        compressed = s.replace(" ", "")
        all = [s, hyphens, underscores, compressed]
        return list({*all, *[s.lower() for s in all]})


def handler(body: dict, _ctx=None) -> None:
    Handler(body).do()
