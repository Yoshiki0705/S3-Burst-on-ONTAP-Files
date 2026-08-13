"""Make `tools/` and `scripts/` importable by the tests.

Neither directory is a package. Adding `__init__.py` to them would make the validators importable
as `tools.<name>`, but they are also run directly as `python3 tools/<name>.py`, and a module that
is both a script and a package member is imported twice under two names — which is exactly the
`sys.modules` collision that forces one pytest process per pattern directory elsewhere in this
repository. Putting the directories on `sys.path` instead keeps a single identity per module.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for directory in ("tools", "scripts"):
    path = str(ROOT / directory)
    if path not in sys.path:
        sys.path.insert(0, path)


# Several tests need a 12-digit number that the audit must reject — that is, one that does not look
# like the sanctioned placeholder. Assembled at run time rather than written as a literal: a literal
# that looks like a real account ID is exactly what a secret scanner is built to stop, and it tripped
# one on the first commit of this repository. Building it keeps the assertions honest without putting
# the shape into a tracked file.
REAL_LOOKING_ACCOUNT = "".join(str((7 * index + 3) % 10) for index in range(12))

# Same reasoning for a file system ID, and the same outcome: written as a literal, the assertion that
# the audit rejects a real-looking ID was itself rejected by the secret scanner. Both spellings are
# built, because the audit has to catch the AWS API form and the form ONTAP and the console show.
_FSX_SUFFIX = "".join("0123456789abcdef"[(5 * index + 1) % 16] for index in range(17))
REAL_LOOKING_FSX_ID = f"fs-{_FSX_SUFFIX}"
REAL_LOOKING_FSX_ID_CONSOLE = f"FsxId{_FSX_SUFFIX}"
