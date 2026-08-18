"""Put the service's own modules on the path.

mcp-proxy runs with its source directory as the working directory, so its
modules are top-level imports. Tests live one level down.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
