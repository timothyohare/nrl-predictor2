import json

import boto3
from langchain_core.tools import tool
from tavily import TavilyClient


class ToolError(Exception):
    pass


def _get_client():
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId="nrl-predictor/tavily-api-key"
    )
    raw = secret["SecretString"]
    api_key = json.loads(raw) if raw.startswith("{") else raw
    return TavilyClient(api_key=api_key)


def _web_search(query: str, client=None) -> list[str]:
    try:
        c = client or _get_client()
        response = c.search(query)
        return [r["content"] for r in response.get("results", [])]
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Web search failed: {e}") from e


@tool
def web_search(query: str) -> list[str]:
    """Live web search for breaking news not yet in the local corpus."""
    return _web_search(query=query)
