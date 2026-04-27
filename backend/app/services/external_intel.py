from typing import Any

import httpx

from app.core.config import get_settings
from app.models.records import Incident


def fetch_external_intel_context(incident: Incident | None, enabled: bool) -> dict[str, Any]:
    settings = get_settings()
    if not enabled:
        return {"enabled": False, "status": "skipped", "items": []}
    if not settings.serper_api_key:
        return {"enabled": True, "status": "not_configured", "items": []}
    if not incident:
        return {"enabled": True, "status": "no_incident", "items": []}

    query = f"{incident.title} SaaS status incident"
    try:
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 3},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"enabled": True, "status": "failed", "items": [], "error": str(exc)}

    items = [
        {
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet"),
        }
        for item in payload.get("organic", [])[:3]
    ]
    return {"enabled": True, "status": "ok", "query": query, "items": items}

