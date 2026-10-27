"""Allow `python -m silica ...` to behave exactly like the `silica` command."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
