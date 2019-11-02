from . import *

event = read_event(env.EVENT_PATH)
validate(event)
try:
    data = parse_body(event["comment"]["body"])
except:
    die(error, "Invalid comment body", 1)
info(data)
version = data["version"]
if not version.startswith("v"):
    version = f"v{version}"
sha = data["sha"]
if release_exists(version):
    die(warn, f"Release {version} already exists", 0)
create_tag(version, sha)
changelog = get_changelog(version)
create_release(version, sha, changelog)
