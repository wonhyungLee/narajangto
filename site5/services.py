from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .config import Settings
from .discord import send_notice
from .filters import matches_filter
from .g2b_client import fetch_bid_notices
from .sheets import sync_bid_notices

KST = ZoneInfo("Asia/Seoul")


def _error_message(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def collect_bid_notices(settings: Settings, lookback_hours: int | None = None) -> dict[str, int | str]:
    job_id = db.start_job(settings.db_path, "collect_bid_notices")
    hours = lookback_hours or settings.default_collect_lookback_hours
    try:
        end_at = datetime.now(KST)
        start_at = end_at - timedelta(hours=hours)
        items = await fetch_bid_notices(settings, start_at, end_at)
        result = db.upsert_bid_notices(settings.db_path, items)
        message = f"fetched={len(items)}, inserted={result['inserted']}, updated={result['updated']}, skipped={result['skipped']}"
        db.finish_job(settings.db_path, job_id, "ok", message, len(items))
        return {"status": "ok", "fetched": len(items), **result}
    except Exception as exc:
        db.finish_job(settings.db_path, job_id, "failed", _error_message(exc), 0)
        raise


async def process_notifications(settings: Settings) -> dict[str, int | str]:
    job_id = db.start_job(settings.db_path, "discord_notifications")
    sent = 0
    failed = 0
    matched = 0
    try:
        if not settings.has_discord_webhook:
            db.finish_job(settings.db_path, job_id, "skipped", "Discord webhook URL is missing", 0)
            return {"status": "skipped", "matched": 0, "sent": 0, "failed": 0}
        filters = db.list_filters(settings.db_path, enabled_only=True)
        notices = db.list_recent_notice_candidates(settings.db_path)
        for filter_row in filters:
            filter_id = int(filter_row["id"])
            filter_active_since = str(filter_row.get("updated_at") or filter_row.get("created_at") or "")
            for notice in notices:
                key = str(notice["notice_key"])
                if filter_active_since and str(notice.get("created_at") or "") < filter_active_since:
                    continue
                if db.has_notification(settings.db_path, filter_id, key):
                    continue
                if not matches_filter(notice, filter_row):
                    continue
                matched += 1
                ok, response = await send_notice(settings, filter_row, notice)
                if ok:
                    sent += 1
                    db.record_notification(settings.db_path, filter_id, key, "sent", response=response)
                else:
                    failed += 1
                    db.record_notification(settings.db_path, filter_id, key, "failed", error=response)
        status = "ok" if failed == 0 else "partial"
        db.finish_job(settings.db_path, job_id, status, f"matched={matched}, sent={sent}, failed={failed}", sent)
        return {"status": status, "matched": matched, "sent": sent, "failed": failed}
    except Exception as exc:
        db.finish_job(settings.db_path, job_id, "failed", _error_message(exc), sent)
        raise


async def sync_sheet(settings: Settings, limit: int = 1000) -> dict[str, int | str]:
    job_id = db.start_job(settings.db_path, "sheet_sync")
    try:
        notices = db.list_sheet_rows(settings.db_path, limit=limit)
        result = await sync_bid_notices(settings, notices)
        if result["status"] == "ok":
            db.mark_sheet_synced(settings.db_path, [str(notice["notice_key"]) for notice in notices])
        db.finish_job(settings.db_path, job_id, str(result["status"]), str(result["message"]), int(result["rows"]))
        return result
    except Exception as exc:
        db.finish_job(settings.db_path, job_id, "failed", _error_message(exc), 0)
        raise
