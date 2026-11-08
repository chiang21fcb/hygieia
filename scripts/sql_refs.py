"""Compatibility shim: the implementation moved to ``hygieia/sql_refs.py``."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hygieia.sql_refs import *  # noqa: F401,F403,E402
