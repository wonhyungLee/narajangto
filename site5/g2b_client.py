from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from .config import Settings

KST = ZoneInfo("Asia/Seoul")
BID_OPERATION = "getDataSetOpnStdBidPblancInfo"


class PublicDataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"PublicData API error {code}: {message}")
        self.code = code
        self.message = message


def _as_items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, str, str]:
    response = payload.get("response") or payload
    header = response.get("header") or {}
    body = response.get("body") or {}
    code = str(header.get("resultCode") or body.get("resultCode") or "")
    message = str(header.get("resultMsg") or body.get("resultMsg") or "")
    if code and code not in {"00", "03"}:
        raise PublicDataError(code, message)
    raw_items = (body.get("items") or {}).get("item") if isinstance(body.get("items"), dict) else body.get("items")
    if raw_items is None:
        items: list[dict[str, Any]] = []
    elif isinstance(raw_items, list):
        items = [item for item in raw_items if isinstance(item, dict)]
    elif isinstance(raw_items, dict):
        items = [raw_items]
    else:
        items = []
    try:
        total_count = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total_count = len(items)
    return items, total_count, code, message


def _request_url(settings: Settings, operation: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    separator = "&" if query else ""
    return f"{settings.api_endpoint}/{operation}?{query}{separator}ServiceKey={settings.service_key}"


def _with_endpoint(settings: Settings, endpoint: str, operation: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    separator = "&" if query else ""
    return f"{endpoint.rstrip('/')}/{operation}?{query}{separator}ServiceKey={settings.service_key}"


def _endpoint_candidates(endpoint: str) -> list[str]:
    parts = urlsplit(endpoint)
    alternate_http = urlunsplit(("http", parts.netloc, parts.path.rstrip("/"), "", ""))
    alternate_https = urlunsplit(("https", parts.netloc, parts.path.rstrip("/"), "", ""))
    if parts.scheme == "https" and parts.netloc == "apis.data.go.kr":
        # The public-data host is documented with HTTP in the guide and HTTPS can
        # hang from some server networks. Prefer HTTP while still keeping HTTPS.
        candidates = [alternate_http, endpoint.rstrip("/")]
    elif parts.scheme == "https":
        candidates = [endpoint.rstrip("/"), alternate_http]
    elif parts.scheme == "http":
        candidates = [endpoint.rstrip("/"), alternate_https]
    else:
        candidates = [endpoint.rstrip("/")]
    return list(dict.fromkeys(candidates))


def _format_dt(value: datetime) -> str:
    return value.astimezone(KST).strftime("%Y%m%d%H%M")


async def fetch_bid_notices(
    settings: Settings,
    start_at: datetime,
    end_at: datetime,
    *,
    num_of_rows: int = 50,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    if not settings.has_api_credentials:
        raise PublicDataError("CONFIG", "G2B API endpoint or service key is missing")
    if end_at < start_at:
        raise ValueError("end_at must be after start_at")
    if end_at - start_at > timedelta(days=31):
        raise ValueError("bid notice query window must be 31 days or shorter")

    collected: list[dict[str, Any]] = []
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    endpoints = _endpoint_candidates(settings.api_endpoint)
    active_endpoint: str | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        page_no = 1
        while page_no <= max_pages:
            params = {
                "numOfRows": num_of_rows,
                "pageNo": page_no,
                "type": "json",
                "bidNtceBgnDt": _format_dt(start_at),
                "bidNtceEndDt": _format_dt(end_at),
            }
            last_error: Exception | None = None
            response: httpx.Response | None = None
            page_endpoints = [active_endpoint, *endpoints] if active_endpoint else endpoints
            page_endpoints = [endpoint for endpoint in dict.fromkeys(page_endpoints) if endpoint]
            for endpoint in page_endpoints:
                url = _with_endpoint(settings, endpoint, BID_OPERATION, params)
                for attempt in range(3):
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        active_endpoint = endpoint
                        break
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        response = None
                        if exc.response.status_code < 500:
                            break
                    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                        last_error = exc
                        response = None
                    await asyncio.sleep(0.35 * (attempt + 1))
                if response is not None:
                    break
            if response is None:
                if last_error:
                    raise last_error
                raise PublicDataError("NETWORK", "request failed")
            payload = response.json()
            items, total_count, _, _ = _as_items(payload)
            collected.extend(items)
            if not items or len(collected) >= total_count:
                break
            page_no += 1
            await asyncio.sleep(0.05)
    return collected
