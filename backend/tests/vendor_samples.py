"""Moved to app/demo/vendor_samples.py (also used by demo mode); this name is kept for the tests."""

import sys

from app.demo import vendor_samples as _module

sys.modules[__name__] = _module
