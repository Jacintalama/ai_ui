"""Run as `python -m flights_mcp`."""
import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())
