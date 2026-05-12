from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import Settings

SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

HEADERS = [
    "공고번호",
    "차수",
    "공고명",
    "상태",
    "업무구분",
    "공고기관",
    "수요기관",
    "공고일자",
    "공고시각",
    "입찰개시",
    "입찰마감",
    "개찰",
    "배정예산",
    "추정가격",
    "지역제한",
    "참가가능지역",
    "업종제한",
    "투찰가능업종",
    "공고URL",
    "데이터기준일자",
    "DB갱신시각",
]


def _credentials(settings: Settings):
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SHEETS_SCOPE)
    if settings.google_service_account_file:
        return service_account.Credentials.from_service_account_file(settings.google_service_account_file, scopes=SHEETS_SCOPE)
    return None


def _access_token(settings: Settings) -> str | None:
    creds = _credentials(settings)
    if not creds:
        return None
    creds.refresh(Request())
    return creds.token


def _range(sheet_name: str, cell_range: str) -> str:
    return quote(f"'{sheet_name}'!{cell_range}", safe="!'")


def _row(notice: dict[str, Any]) -> list[Any]:
    return [
        notice.get("bid_ntce_no") or "",
        notice.get("bid_ntce_ord") or "",
        notice.get("bid_ntce_nm") or "",
        notice.get("bid_ntce_sttus_nm") or "",
        notice.get("bsns_div_nm") or "",
        notice.get("ntce_instt_nm") or "",
        notice.get("dmnd_instt_nm") or "",
        notice.get("bid_ntce_date") or "",
        notice.get("bid_ntce_bgn") or "",
        f"{notice.get('bid_begin_date') or ''} {notice.get('bid_begin_tm') or ''}".strip(),
        f"{notice.get('bid_clse_date') or ''} {notice.get('bid_clse_tm') or ''}".strip(),
        f"{notice.get('openg_date') or ''} {notice.get('openg_tm') or ''}".strip(),
        notice.get("asign_bdgt_amt") or "",
        notice.get("presmpt_prce") or "",
        notice.get("rgn_lmt_yn") or "",
        notice.get("prtcpt_psbl_rgn_nm") or "",
        notice.get("indstryty_lmt_yn") or "",
        notice.get("bidprc_psbl_indstryty_nm") or "",
        notice.get("bid_ntce_url") or "",
        notice.get("data_bss_date") or "",
        notice.get("updated_at") or "",
    ]


async def sync_bid_notices(settings: Settings, notices: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.google_spreadsheet_id:
        return {"status": "skipped", "message": "Google spreadsheet URL or ID is missing", "rows": 0}
    token = _access_token(settings)
    if not token:
        return {"status": "skipped", "message": "Google service account credentials are missing", "rows": 0}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    spreadsheet_url = f"{SHEETS_API}/{settings.google_spreadsheet_id}"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        meta = await client.get(f"{spreadsheet_url}?fields=sheets.properties.title", headers=headers)
        if meta.status_code >= 400:
            return {"status": "failed", "message": f"Sheets metadata error {meta.status_code}: {meta.text[:500]}", "rows": 0}
        titles = {sheet["properties"]["title"] for sheet in meta.json().get("sheets", [])}
        if settings.google_sheet_name not in titles:
            add = await client.post(
                f"{spreadsheet_url}:batchUpdate",
                headers=headers,
                json={"requests": [{"addSheet": {"properties": {"title": settings.google_sheet_name}}}]},
            )
            if add.status_code >= 400:
                return {"status": "failed", "message": f"Add sheet error {add.status_code}: {add.text[:500]}", "rows": 0}

        clear_range = _range(settings.google_sheet_name, "A:Z")
        clear = await client.post(f"{spreadsheet_url}/values/{clear_range}:clear", headers=headers, json={})
        if clear.status_code >= 400:
            return {"status": "failed", "message": f"Clear sheet error {clear.status_code}: {clear.text[:500]}", "rows": 0}

        values = [HEADERS, *[_row(notice) for notice in notices]]
        update_range = _range(settings.google_sheet_name, "A1")
        update = await client.put(
            f"{spreadsheet_url}/values/{update_range}?valueInputOption=USER_ENTERED",
            headers=headers,
            json={"majorDimension": "ROWS", "values": values},
        )
        if update.status_code >= 400:
            return {"status": "failed", "message": f"Update sheet error {update.status_code}: {update.text[:500]}", "rows": 0}
    return {"status": "ok", "message": "sheet synced", "rows": len(notices)}
