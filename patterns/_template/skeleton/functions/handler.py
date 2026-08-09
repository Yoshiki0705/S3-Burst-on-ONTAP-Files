"""Placeholder handler for a pattern scaffolded from `patterns/_template/`.

Replace the body. Keep the module name, the function name and the return shape:

* the file is `handler.py` and the entry point is `handler.handler`. A sibling repository used
  `index.py` in some patterns and `handler.py` in others, and the mismatch surfaces only at deploy
  time as a runtime import error, so the convention is fixed here rather than left to preference;
* the return is a dict. Returning `None` from a Lambda invoked by anything that inspects the result
  turns a wiring mistake into a silent success.

What this stub actually does is check its own wiring and say what it found. That is the first thing
anyone needs from a new pattern — proof the environment reached the function — and it means the
scaffolded pattern has a passing test before any real logic exists.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables the template always sets. A pattern that needs more should add them here so
# that a missing one is reported by this stub rather than by an AttributeError deep in the logic.
WIRING = (
    "PATTERN_NAME",
    "PATTERN_AXIS",
    "ENVIRONMENT",
    "FILE_SYSTEM_ID",
    "STORAGE_VIRTUAL_MACHINE_ID",
    "VOLUME_NAME",
    "S3_ACCESS_POINT_ALIAS",
)


def wiring_report(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Report which expected variables are set, without echoing their values.

    Values are omitted on purpose. A file system ID or an access point alias is not a secret, but
    logging identifiers by default is how they end up in a screenshot in a public issue.
    """
    env = os.environ if environ is None else environ
    present = sorted(name for name in WIRING if env.get(name))
    missing = sorted(name for name in WIRING if not env.get(name))
    return {"present": present, "missing": missing}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Entry point. Replace the body; keep the signature and the return shape."""
    report = wiring_report()
    result: dict[str, Any] = {
        "pattern": os.environ.get("PATTERN_NAME", "unset"),
        "axis": os.environ.get("PATTERN_AXIS", "unset"),
        "implemented": False,
        "wiring": report,
        "event_keys": sorted(event) if isinstance(event, dict) else None,
    }
    if report["missing"]:
        LOGGER.warning("unset environment variables: %s", ", ".join(report["missing"]))
    LOGGER.info("wiring check: %s", json.dumps(result, ensure_ascii=False))
    return result
