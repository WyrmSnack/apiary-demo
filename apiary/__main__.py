"""`python -m apiary ...`: the CLI, for when the `apiary` script is not on PATH (common on Windows)."""
import sys

from .cli import main

sys.exit(main())
