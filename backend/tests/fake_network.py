"""Moved to app/demo/simnet.py (also used by demo mode); this name is kept for the tests."""

import sys

from app.demo import simnet as _module

sys.modules[__name__] = _module
