"""Every published sibling must have local directory names recorded.

`check_links.PUBLISHED_REPOS` and `check_outgoing_probes.LOCAL_NAMES` are deliberately two sources,
not one: the first says which repositories of this owner are published, the second says what each is
called on this filesystem. They are kept separate on purpose -- merging them is a different concern
and out of scope -- but when one gains a repository the other does not, `check_blog_links.root_for()`
returns "has no local directory names recorded; add it to LOCAL_NAMES" as a hard failure, which is
exactly the break that six missing entries caused. This test closes that gap without merging the two.

The comparison is case-insensitive because `root_for()` resolves `LOCAL_NAMES` keys that way, and
this repository itself is excluded because it resolves to its own ROOT rather than a sibling checkout.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The names `check_blog_links._THIS_REPO` carries, lower-cased. This repository is not a sibling: it
# resolves to ROOT, never through LOCAL_NAMES, so it is not expected there.
THIS_REPO_LOWER = {"s3-burst-on-ontap-files", "s3-burst-on-ontap-files".lower()}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_links = _load("check_links")
check_outgoing_probes = _load("check_outgoing_probes")


def _registered(published: str, local_names: dict) -> bool:
    return any(canonical.lower() == published.lower() for canonical in local_names)


def test_every_published_sibling_is_in_local_names() -> None:
    local_names = check_outgoing_probes.LOCAL_NAMES
    missing = sorted(
        name
        for name in check_links.PUBLISHED_REPOS
        if name.lower() not in THIS_REPO_LOWER and not _registered(name, local_names)
    )
    assert not missing, (
        "these published repositories have no entry in check_outgoing_probes.LOCAL_NAMES, so "
        "check_blog_links.root_for() fails hard for any blog link that names one: "
        f"{missing}. Add each to LOCAL_NAMES with its local directory names."
    )


def test_the_check_is_not_vacuous() -> None:
    """Removing a required entry must make the assertion above fail.

    A test that passes against an empty LOCAL_NAMES would catch nothing. This proves it reacts: with
    one published sibling dropped from a copy of the mapping, the same logic reports it missing.
    """
    local_names = dict(check_outgoing_probes.LOCAL_NAMES)
    siblings = [
        name
        for name in check_links.PUBLISHED_REPOS
        if name.lower() not in THIS_REPO_LOWER
    ]
    assert siblings, "no sibling repositories to check against"
    dropped = siblings[0]
    # Remove whichever LOCAL_NAMES key matches the dropped sibling case-insensitively.
    for canonical in list(local_names):
        if canonical.lower() == dropped.lower():
            del local_names[canonical]
    assert not _registered(dropped, local_names)
