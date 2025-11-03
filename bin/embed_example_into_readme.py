"""
Embed the contents of example.yml into README.md between markers.

Usage: bin/embed_example_into_readme.py
This will replace the text between the markers
<!-- BEGIN EXAMPLE_WORKFLOW --> and <!-- END EXAMPLE_WORKFLOW --> with
the contents of example.yml formatted as a YAML fenced code block.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
EXAMPLE = ROOT / "example.yml"

BEGIN = "<!-- BEGIN EXAMPLE_WORKFLOW -->"
END = "<!-- END EXAMPLE_WORKFLOW -->"


def main() -> None:
    readme = README.read_text(encoding="utf8")
    example = EXAMPLE.read_text(encoding="utf8").strip()

    if BEGIN not in readme or END not in readme:
        raise SystemExit(f"Markers {BEGIN}/{END} not found in {README}")

    before, rest = readme.split(BEGIN, 1)
    _, after = rest.split(END, 1)

    new_block = f"{BEGIN}\n\n```yaml\n{example}\n```\n\n{END}"

    new_readme = before + new_block + after
    README.write_text(new_readme, encoding="utf8")
    print(f"Embedded {EXAMPLE} into {README}")


if __name__ == "__main__":
    main()
