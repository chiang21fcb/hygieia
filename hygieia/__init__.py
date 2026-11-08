"""Hygieia: offline health check for semantic layers.

Public names live in :mod:`hygieia.engine`; this package re-exports them so
``import hygieia`` works for both the installed ``hygieia-sl`` distribution and
a repository checkout.
"""
from .engine import VERSION as __version__  # noqa: F401
from .engine import *  # noqa: F401,F403
