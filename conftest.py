"""Pytest configuration - ensure src is on path."""
import sys
from pathlib import Path

root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
