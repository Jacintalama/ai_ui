"""n8n workflow automation client."""
import httpx
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class N8NClient:
    """Client for triggering n8n workflows via webhook nodes."""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = 120.0  # n8n workflows can be slow (AI review takes 60-90s)

    async def trigger_workflow(
        self,
        webhook_path: str,
        payload: dict[str, Any] = None
    ) -> Optional[dict[str, Any]]:
        """
        Trigger an n8n workflow via its webhook node.

        n8n webhook URLs follow the pattern:
        {base_url}/webhook/{webhook_path}

        Args:
            webhook_path: The webhook path configured in n8n (e.g., 'github-issue')
            payload: JSON payload to send to the workflow

        Returns:
            Workflow response dict, or None on error
        """
        url = f"{self.base_url}/webhook/{webhook_path}"
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload or {},
                    headers=headers
                )
                response.raise_for_status()

                text = response.text.strip()
                if text:
                    result = response.json()
                else:
                    # Empty body with responseNode mode means workflow errored
                    # before reaching the Respond node (e.g. credential issue)
                    logger.warning(
                        f"n8n webhook '{webhook_path}' returned empty body "
                        f"(HTTP {response.status_code}) — workflow likely errored"
                    )
                    result = {"status": "error", "error": "Workflow returned empty response — check n8n execution log"}
                logger.info(f"n8n workflow triggered: {webhook_path}")
                return result

        except httpx.HTTPStatusError as e:
            logger.error(
                f"n8n error for {webhook_path}: "
                f"{e.response.status_code} - {e.response.text}"
            )
            return None
        except httpx.TimeoutException:
            logger.error(f"Timeout triggering n8n workflow: {webhook_path}")
            return None
        except Exception as e:
            logger.error(f"Error triggering n8n workflow: {e}")
            return None

    async def trigger_workflow_by_id(
        self,
        workflow_id: str,
        payload: dict[str, Any] = None
    ) -> Optional[dict[str, Any]]:
        """
        Trigger an n8n workflow via the API (requires API key).

        Args:
            workflow_id: n8n workflow ID
            payload: JSON payload

        Returns:
            Execution result dict, or None on error
        """
        if not self.api_key:
            logger.error("n8n API key required for workflow-by-id execution")
            return None

        url = f"{self.base_url}/api/v1/workflows/{workflow_id}/execute"
        headers = {
            "Content-Type": "application/json",
            "X-N8N-API-KEY": self.api_key
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json={"data": payload or {}},
                    headers=headers
                )
                response.raise_for_status()

                result = response.json()
                logger.info(f"n8n workflow {workflow_id} executed via API")
                return result

        except Exception as e:
            logger.error(f"Error executing n8n workflow {workflow_id}: {e}")
            return None

    async def get_recent_executions(self, limit: int = 50) -> list[dict]:
        """Get recent workflow executions via the n8n API."""
        if not self.api_key:
            logger.warning("n8n API key not set — cannot fetch executions")
            return []

        headers = {
            "X-N8N-API-KEY": self.api_key,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Fetch workflow names for ID-to-name resolution
                wf_resp = await client.get(
                    f"{self.base_url}/api/v1/workflows",
                    headers=headers,
                )
                wf_names = {}
                if wf_resp.status_code == 200:
                    wf_data = wf_resp.json()
                    wf_list = wf_data.get("data", wf_data) if isinstance(wf_data, dict) else wf_data
                    if isinstance(wf_list, list):
                        wf_names = {w.get("id"): w.get("name", "unnamed") for w in wf_list}

                # Fetch executions
                response = await client.get(
                    f"{self.base_url}/api/v1/executions",
                    headers=headers,
                    params={"limit": limit},
                )
                response.raise_for_status()
                data = response.json()

            executions = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(executions, list):
                executions = []

            return [
                {
                    "id": ex.get("id"),
                    "workflow_name": (
                        (ex.get("workflowData") or {}).get("name")
                        or wf_names.get(ex.get("workflowId"))
                        or f"workflow-{ex.get('workflowId', 'unknown')}"
                    ),
                    "status": ex.get("status", "unknown"),
                    "started": ex.get("startedAt", ""),
                    "finished": ex.get("stoppedAt", ""),
                }
                for ex in executions
            ]

        except Exception as e:
            logger.error(f"Error fetching n8n executions: {e}")
            return []
