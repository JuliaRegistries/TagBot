from typing import Optional

prepare = "prepare"
tag = "tag"
changelog = "changelog"
release = "release"
notify = "notify"


def next(stage: str) -> Optional[str]:
    """Get the next stage after a given stage."""
    if stage == prepare:
        return tag
    elif stage == tag:
        return changelog
    elif stage == changelog:
        return release
    elif stage == release:
        return None
    elif stage == notify:
        return None
    else:
        print("Unknown stage:", stage)
        return None


def after_failure(stage: str) -> Optional[str]:
    """Get the next stage after a given stage has failed."""
    if stage == prepare:
        return None
    elif stage == tag:
        return next(stage)
    elif stage == changelog:
        return next(stage)
    elif stage == release:
        return None
    elif stage == notify:
        return next(stage)
    else:
        print("Unknown stage:", stage)
        return None


def action(stage: str) -> Optional[str]:
    """Get the action associated with a stage."""
    if stage == prepare:
        return "prepare a job context"
    elif stage == tag:
        return "create a Git tag"
    elif stage == changelog:
        return "generate a changelog"
    elif stage == release:
        return "create a GitHub release"
    elif stage == notify:
        return "send a notification"
    else:
        print("Unknown stage:", stage)
        return None
