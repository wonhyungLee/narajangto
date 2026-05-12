from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


def _money(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,}원"


def build_notice_payload(filter_row: dict[str, Any], notice: dict[str, Any]) -> dict[str, Any]:
    title = str(notice.get("bid_ntce_nm") or "나라장터 입찰공고")[:250]
    url = notice.get("bid_ntce_url") or None
    fields = [
        {"name": "필터", "value": str(filter_row.get("name") or "-")[:1024], "inline": True},
        {"name": "업무구분", "value": str(notice.get("bsns_div_nm") or "-")[:1024], "inline": True},
        {"name": "추정가격", "value": _money(notice.get("presmpt_prce") or notice.get("asign_bdgt_amt")), "inline": True},
        {"name": "공고기관", "value": str(notice.get("ntce_instt_nm") or "-")[:1024], "inline": False},
        {"name": "수요기관", "value": str(notice.get("dmnd_instt_nm") or "-")[:1024], "inline": False},
        {"name": "입찰마감", "value": f"{notice.get('bid_clse_date') or '-'} {notice.get('bid_clse_tm') or ''}".strip(), "inline": True},
        {"name": "개찰", "value": f"{notice.get('openg_date') or '-'} {notice.get('openg_tm') or ''}".strip(), "inline": True},
        {"name": "지역제한", "value": str(notice.get("prtcpt_psbl_rgn_nm") or notice.get("rgn_lmt_yn") or "-")[:1024], "inline": False},
    ]
    embed = {
        "title": title,
        "url": url,
        "description": f"공고번호: `{notice.get('bid_ntce_no') or '-'}` / 차수: `{notice.get('bid_ntce_ord') or '-'}`",
        "color": 14728018,
        "fields": fields,
        "footer": {"text": "나라장터 Site5 Monitor"},
    }
    return {"content": "신규 필터 매칭 공고", "embeds": [embed], "allowed_mentions": {"parse": []}}


async def send_notice(settings: Settings, filter_row: dict[str, Any], notice: dict[str, Any]) -> tuple[bool, str]:
    if not settings.discord_webhook_url:
        return False, "Discord webhook URL is missing"
    payload = build_notice_payload(filter_row, notice)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(settings.discord_webhook_url, json=payload)
    if 200 <= response.status_code < 300:
        return True, str(response.status_code)
    return False, f"{response.status_code}: {response.text[:500]}"
