"""The product's version, from the VERSION file at the top of the repository (and of every
install bundle): MAJOR.MINOR.PATCH, see docs/releasing.md.

Shown to signed-in users only (the top bar, the report, ``netops-cli version``), never on
pages anyone can reach without signing in: an exact version tells an attacker which known
problems to try.
"""

import re
from pathlib import Path

_FILE = Path(__file__).resolve().parents[2] / "VERSION"
_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_ANY = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.]+)?$")  # also 2.1.0-dev.<date>.<commit>


def read(path: Path = _FILE) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"
    return text if _RE.match(text) else "dev"


def parse(text: str) -> tuple[int, int, int] | None:
    """'2.1.0' -> (2, 1, 0); None for anything else (a dev build, an old dated bundle)."""
    m = _ANY.match(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


VERSION = read()
