#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatible entry point: ``python scripts/hygieia.py ...``.

All logic lives in the ``hygieia`` package (``hygieia/engine.py``); this file is
a thin wrapper so existing scripts and docs keep working.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hygieia.engine import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
