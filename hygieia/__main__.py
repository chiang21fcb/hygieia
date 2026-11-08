"""``python -m hygieia`` entry point."""
import sys

from .engine import main

if __name__ == "__main__":
    sys.exit(main())
