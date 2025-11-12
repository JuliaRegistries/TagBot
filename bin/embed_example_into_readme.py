"""Deprecated helper.

Historically this project embedded `example.yml` into the README with
`bin/embed_example_into_readme.py`. The repository has been simplified to
use a relative link to `example.yml` in the README instead. This file is kept
only for historical reference and no longer used by the project.
"""

import sys


def main() -> None:
    print("embed_example_into_readme.py is deprecated. README now links to example.yml.")
    sys.exit(0)


if __name__ == "__main__":
    main()
