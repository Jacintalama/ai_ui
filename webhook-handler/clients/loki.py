"""Loki API client for querying container logs."""
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class LokiClient:
    """Client for Loki log queries."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.timeout = 15.0

    async def query_error_logs(
        self,
        container_name: str = "",
        minutes: int = 5,
        limit: int = 50,
    ) -> list[str]:
        """
        Query Loki for recent error logs.

        Args:
            container_name: Container to query. Empty string = all containers.
            minutes: How many minutes back to search.
            limit: Max log lines to return.

        Returns:
            List of log line strings, newest first.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=minutes)

        # Build LogQL query
        if container_name:
            selector = f'{{container_name="{container_name}"}}'
        else:
            selector = '{container_name=~".+"}'

        query = f'{selector} |~ "(?i)(error|exception|fatal|panic|traceback)"'

        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "end": str(int(now.timestamp() * 1_000_000_000)),
            "limit": str(limit),
            "direction": "backward",
        }

        url = f"{self.base_url}/loki/api/v1/query_range"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            # Parse Loki response: data.result[].values[][1]
            lines = []
            for stream in data.get("data", {}).get("result", []):
                container = stream.get("stream", {}).get("container_name", "unknown")
                for value in stream.get("values", []):
                    log_line = value[1] if len(value) > 1 else ""
                    # Prefix with container name if querying all
                    if not container_name:
                        lines.append(f"[{container}] {log_line}")
                    else:
                        lines.append(log_line)

            logger.info(f"Loki query returned {len(lines)} error lines for '{container_name or 'all'}'")
            return lines[:limit]

        except httpx.HTTPStatusError as e:
            logger.error(f"Loki HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Loki query failed: {e}")
            return []
