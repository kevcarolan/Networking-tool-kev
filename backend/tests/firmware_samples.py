"""Moved to app/demo/samples.py (also used by demo mode); this name is kept for the tests."""

import sys

from app.demo import samples as _module

sys.modules[__name__] = _module
