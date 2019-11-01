import json
import os
import subprocess
import sys


def read_event():
    path = os.environ["GITHUB_EVENT_PATH"]
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    print(sys.argv)
    for k, v in sorted(os.environ.items()):
        print(f"{k} = {v}")
    print(json.dumps(read_event(), indent=2))
