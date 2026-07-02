#!/usr/bin/env python3
"""
Global Entry Point for BaseMem CLI.
This script is path-aware and can be run from any directory.
"""

import sys
from pathlib import Path

# 1. Find the absolute path to this script (where BaseMem is installed)
BASE_DIR = Path(__file__).parent.absolute()

# 2. Add the 'src' directory to the Python path
sys.path.insert(0, str(BASE_DIR))

# 3. Import and run the CLI
try:
    from cli import cli
    if __name__ == '__main__':
        cli(prog_name='mem')
except ImportError as e:
    print(f"Error: Could not find BaseMem source in {BASE_DIR}")
    print(f"Details: {e}")
    sys.exit(1)
