"""A link to one of this owner's repositories must name a published repository.

Found by `make links-external`: eighteen links across the README, `SECURITY.md`, `llms.txt` and five
reference documents pointed at `github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns` and
`.../fsxn-adoption-playbook`. Both repositories are public; neither is called that. Those are the
names of the working directories on the author's machine, and they reached a public repository as
citations a reader could not open -- which puts every claim resting on them back to unconfirmed.

Nothing caught it. The internal link checker only resolves relative paths, and the external probe
needs a network, so it is not in the commit gate. The check this file covers closes that: the
repository name is verified offline, against the list of names GitHub actually knows, so it fails on
the machine that wrote it.

The list is a maintenance cost, deliberately. Publishing a new sibling means adding it here, and that
is the point at which someone confirms the name rather than assuming it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import check_links as links
import pytest

ROOT = Path(__file__).resolve().parent.parent


# This file's own fixtures are the shape the corpus check forbids, the same situation the audit
# handles with a file-level allowance. Excluded by path rather than by pattern, so that a real link
# added to it would still be a fixture and never a citation.
SELF = Path(__file__).name


def tracked_text_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in listing if not name.endswith(SELF)]


def test_the_published_list_is_not_empty() -> None:
    """An empty list would make the check accept everything instead of nothing."""
    assert links.PUBLISHED_REPOS
    assert "s3-burst-on-ontap-files" in links.PUBLISHED_REPOS, (
        "this repository's own name must be in the list or every self-link fails"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Yoshiki0705/s3-burst-on-ontap-files",
        "https://github.com/Yoshiki0705/s3-burst-on-ontap-files/blob/main/README.md",
        "https://github.com/Yoshiki0705/s3-burst-on-ontap-files/security/advisories/new",
        "https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook",
        "https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/s3ap-compatibility-notes.md",
    ],
)
def test_a_published_repository_passes(url: str) -> None:
    assert links.check_owner_repo(url) is None, url


@pytest.mark.parametrize(
    "url",
    [
        # The two directory names that actually shipped.
        "https://github.com/Yoshiki0705/fsxn-adoption-playbook",
        "https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns/blob/main/docs/s3ap-authorization-model.md",
        "https://github.com/Yoshiki0705/s3-burst-on-ontap-file",
    ],
)
def test_an_unpublished_name_is_rejected(url: str) -> None:
    problem = links.check_owner_repo(url)
    assert problem is not None, url
    assert "not a repository name" in problem


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/aws-samples/serverless-patterns",
        "https://github.com/awslabs/aws-solutions-constructs",
        "https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html",
    ],
)
def test_another_owner_is_not_this_check_s_business(url: str) -> None:
    """Only this owner's repositories are known; a third party's name cannot be validated offline."""
    assert links.check_owner_repo(url) is None, url


def test_no_tracked_file_links_to_an_unpublished_repository() -> None:
    """The corpus, not just the function. A link in a file the checker skips is still published."""
    pattern = links.OWNER_URL
    problems: list[str] = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in pattern.finditer(line):
                if match.group(1) not in links.PUBLISHED_REPOS:
                    rel = path.relative_to(ROOT)
                    problems.append(f"{rel}:{lineno}: {match.group(1)}")
    assert not problems, (
        "these links name a repository that is not published: "
        + "; ".join(problems)
        + ". A local working directory name is not a repository name."
    )
