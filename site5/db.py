from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS bid_notices (
    notice_key TEXT PRIMARY KEY,
    bid_ntce_no TEXT NOT NULL,
    bid_ntce_ord TEXT,
    ref_ntce_no TEXT,
    bid_ntce_nm TEXT,
    bid_ntce_sttus_nm TEXT,
    bsns_div_nm TEXT,
    cntrct_cncls_sttus_nm TEXT,
    cntrct_cncls_mthd_nm TEXT,
    bidwinr_dcsn_mthd_nm TEXT,
    ntce_instt_nm TEXT,
    ntce_instt_cd TEXT,
    dmnd_instt_nm TEXT,
    dmnd_instt_cd TEXT,
    bid_ntce_date TEXT,
    bid_ntce_bgn TEXT,
    bid_begin_date TEXT,
    bid_begin_tm TEXT,
    bid_clse_date TEXT,
    bid_clse_tm TEXT,
    openg_date TEXT,
    openg_tm TEXT,
    asign_bdgt_amt INTEGER,
    presmpt_prce INTEGER,
    rgn_lmt_yn TEXT,
    prtcpt_psbl_rgn_nm TEXT,
    indstryty_lmt_yn TEXT,
    bidprc_psbl_indstryty_nm TEXT,
    bid_ntce_url TEXT,
    data_bss_date TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notified_at TEXT,
    sheet_synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bid_notices_dates ON bid_notices(bid_ntce_date, bid_clse_date, openg_date);
CREATE INDEX IF NOT EXISTS idx_bid_notices_amount ON bid_notices(presmpt_prce, asign_bdgt_amt);
CREATE INDEX IF NOT EXISTS idx_bid_notices_business ON bid_notices(bsns_div_nm);

CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    keywords TEXT NOT NULL DEFAULT '',
    exclude_keywords TEXT NOT NULL DEFAULT '',
    business_types TEXT NOT NULL DEFAULT '',
    regions TEXT NOT NULL DEFAULT '',
    institutions TEXT NOT NULL DEFAULT '',
    min_amount INTEGER,
    max_amount INTEGER,
    require_region_limit TEXT NOT NULL DEFAULT 'any',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filter_id INTEGER NOT NULL,
    notice_key TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    response TEXT,
    error TEXT,
    UNIQUE(filter_id, notice_key)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    message TEXT,
    rows_count INTEGER DEFAULT 0
);
"""

BID_FIELD_MAP = {
    "bidNtceNo": "bid_ntce_no",
    "bidNtceOrd": "bid_ntce_ord",
    "refNtceNo": "ref_ntce_no",
    "bidNtceNm": "bid_ntce_nm",
    "bidNtceSttusNm": "bid_ntce_sttus_nm",
    "bsnsDivNm": "bsns_div_nm",
    "cntrctCnclsSttusNm": "cntrct_cncls_sttus_nm",
    "cntrctCnclsMthdNm": "cntrct_cncls_mthd_nm",
    "bidwinrDcsnMthdNm": "bidwinr_dcsn_mthd_nm",
    "ntceInsttNm": "ntce_instt_nm",
    "ntceInsttCd": "ntce_instt_cd",
    "dmndInsttNm": "dmnd_instt_nm",
    "dmndInsttCd": "dmnd_instt_cd",
    "bidNtceDate": "bid_ntce_date",
    "bidNtceBgn": "bid_ntce_bgn",
    "bidBeginDate": "bid_begin_date",
    "bidBeginTm": "bid_begin_tm",
    "bidClseDate": "bid_clse_date",
    "bidClseTm": "bid_clse_tm",
    "opengDate": "openg_date",
    "opengTm": "openg_tm",
    "asignBdgtAmt": "asign_bdgt_amt",
    "presmptPrce": "presmpt_prce",
    "rgnLmtYn": "rgn_lmt_yn",
    "prtcptPsblRgnNm": "prtcpt_psbl_rgn_nm",
    "indstrytyLmtYn": "indstryty_lmt_yn",
    "bidprcPsblIndstrytyNm": "bidprc_psbl_indstryty_nm",
    "bidNtceUrl": "bid_ntce_url",
    "dataBssDate": "data_bss_date",
}

INTEGER_FIELDS = {"asign_bdgt_amt", "presmpt_prce"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    digits = re.sub(r"[^0-9-]", "", str(value))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def notice_key(item: dict[str, Any]) -> str | None:
    bid_no = str(item.get("bidNtceNo") or "").strip()
    if not bid_no:
        return None
    bid_ord = str(item.get("bidNtceOrd") or "").strip()
    return f"{bid_no}:{bid_ord}"


def upsert_bid_notices(db_path: Path, items: Iterable[dict[str, Any]]) -> dict[str, int]:
    now = now_iso()
    inserted = 0
    updated = 0
    skipped = 0
    columns = [
        "notice_key",
        *BID_FIELD_MAP.values(),
        "raw_json",
        "fetched_at",
        "created_at",
        "updated_at",
    ]
    placeholders = ", ".join(["?"] * len(columns))
    update_columns = [c for c in columns if c not in {"notice_key", "created_at"}]
    update_sql = ", ".join([f"{c}=excluded.{c}" for c in update_columns])
    sql = f"""
        INSERT INTO bid_notices ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(notice_key) DO UPDATE SET {update_sql}
    """
    with connect(db_path) as conn:
        for item in items:
            key = notice_key(item)
            if not key:
                skipped += 1
                continue
            exists = conn.execute("SELECT 1 FROM bid_notices WHERE notice_key = ?", (key,)).fetchone()
            row: dict[str, Any] = {"notice_key": key}
            for src, dest in BID_FIELD_MAP.items():
                value = item.get(src)
                row[dest] = _to_int(value) if dest in INTEGER_FIELDS else (str(value).strip() if value is not None else None)
            row["raw_json"] = json.dumps(item, ensure_ascii=False, sort_keys=True)
            row["fetched_at"] = now
            row["created_at"] = now
            row["updated_at"] = now
            conn.execute(sql, [row.get(col) for col in columns])
            if exists:
                updated += 1
            else:
                inserted += 1
        conn.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def list_notices(db_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    page = max(1, int(params.get("page") or 1))
    page_size = min(100, max(1, int(params.get("page_size") or 25)))
    where = []
    values: list[Any] = []
    search = (params.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        where.append("(bid_ntce_nm LIKE ? OR ntce_instt_nm LIKE ? OR dmnd_instt_nm LIKE ? OR bidprc_psbl_indstryty_nm LIKE ?)")
        values.extend([like, like, like, like])
    business_type = (params.get("business_type") or "").strip()
    if business_type:
        where.append("bsns_div_nm = ?")
        values.append(business_type)
    region = (params.get("region") or "").strip()
    if region:
        where.append("prtcpt_psbl_rgn_nm LIKE ?")
        values.append(f"%{region}%")
    min_amount = params.get("min_amount")
    if min_amount not in (None, ""):
        where.append("COALESCE(presmpt_prce, asign_bdgt_amt, 0) >= ?")
        values.append(int(min_amount))
    max_amount = params.get("max_amount")
    if max_amount not in (None, ""):
        where.append("COALESCE(presmpt_prce, asign_bdgt_amt, 0) <= ?")
        values.append(int(max_amount))
    only_notified = params.get("only_notified") in {"1", "true", True}
    if only_notified:
        where.append("notified_at IS NOT NULL")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    offset = (page - 1) * page_size
    with connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM bid_notices {where_sql}", values).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT * FROM bid_notices
            {where_sql}
            ORDER BY bid_ntce_date DESC, bid_ntce_bgn DESC, updated_at DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def list_recent_notice_candidates(db_path: Path, limit: int = 500) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bid_notices
            ORDER BY created_at DESC, bid_ntce_date DESC, bid_ntce_bgn DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_sheet_rows(db_path: Path, limit: int = 1000) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bid_notices
            ORDER BY bid_ntce_date DESC, bid_ntce_bgn DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_sheet_synced(db_path: Path, notice_keys: Iterable[str]) -> None:
    keys = list(notice_keys)
    if not keys:
        return
    synced_at = now_iso()
    with connect(db_path) as conn:
        conn.executemany("UPDATE bid_notices SET sheet_synced_at = ? WHERE notice_key = ?", [(synced_at, key) for key in keys])
        conn.commit()


def list_filters(db_path: Path, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM filters"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY enabled DESC, id DESC"
    with connect(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def get_filter(db_path: Path, filter_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM filters WHERE id = ?", (filter_id,)).fetchone()
    return dict(row) if row else None


def save_filter(db_path: Path, payload: dict[str, Any], filter_id: int | None = None) -> dict[str, Any]:
    now = now_iso()
    data = {
        "name": str(payload.get("name") or "새 필터").strip(),
        "enabled": 1 if payload.get("enabled", True) else 0,
        "keywords": str(payload.get("keywords") or "").strip(),
        "exclude_keywords": str(payload.get("exclude_keywords") or "").strip(),
        "business_types": str(payload.get("business_types") or "").strip(),
        "regions": str(payload.get("regions") or "").strip(),
        "institutions": str(payload.get("institutions") or "").strip(),
        "min_amount": _to_int(payload.get("min_amount")),
        "max_amount": _to_int(payload.get("max_amount")),
        "require_region_limit": str(payload.get("require_region_limit") or "any").strip(),
    }
    with connect(db_path) as conn:
        if filter_id:
            conn.execute(
                """
                UPDATE filters SET
                    name = ?, enabled = ?, keywords = ?, exclude_keywords = ?, business_types = ?,
                    regions = ?, institutions = ?, min_amount = ?, max_amount = ?, require_region_limit = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    data["name"],
                    data["enabled"],
                    data["keywords"],
                    data["exclude_keywords"],
                    data["business_types"],
                    data["regions"],
                    data["institutions"],
                    data["min_amount"],
                    data["max_amount"],
                    data["require_region_limit"],
                    now,
                    filter_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO filters (
                    name, enabled, keywords, exclude_keywords, business_types, regions, institutions,
                    min_amount, max_amount, require_region_limit, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data["enabled"],
                    data["keywords"],
                    data["exclude_keywords"],
                    data["business_types"],
                    data["regions"],
                    data["institutions"],
                    data["min_amount"],
                    data["max_amount"],
                    data["require_region_limit"],
                    now,
                    now,
                ),
            )
            filter_id = int(cur.lastrowid)
        conn.commit()
    saved = get_filter(db_path, int(filter_id))
    if not saved:
        raise RuntimeError("filter save failed")
    return saved


def delete_filter(db_path: Path, filter_id: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM filters WHERE id = ?", (filter_id,))
        conn.commit()


def has_notification(db_path: Path, filter_id: int, key: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM notifications WHERE filter_id = ? AND notice_key = ?", (filter_id, key)).fetchone()
    return bool(row)


def record_notification(db_path: Path, filter_id: int, key: str, status: str, response: str = "", error: str = "") -> None:
    sent_at = now_iso()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO notifications(filter_id, notice_key, sent_at, status, response, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filter_id, key, sent_at, status, response, error),
        )
        if status == "sent":
            conn.execute("UPDATE bid_notices SET notified_at = ? WHERE notice_key = ?", (sent_at, key))
        conn.commit()


def start_job(db_path: Path, job_name: str) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO job_runs(job_name, started_at, status) VALUES (?, ?, ?)",
            (job_name, now_iso(), "running"),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_job(db_path: Path, job_id: int, status: str, message: str = "", rows_count: int = 0) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE job_runs SET finished_at = ?, status = ?, message = ?, rows_count = ? WHERE id = ?",
            (now_iso(), status, message, rows_count, job_id),
        )
        conn.commit()


def latest_jobs(db_path: Path, limit: int = 8) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM job_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def stats(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM bid_notices").fetchone()[0]
        filters = conn.execute("SELECT COUNT(*) FROM filters").fetchone()[0]
        enabled_filters = conn.execute("SELECT COUNT(*) FROM filters WHERE enabled = 1").fetchone()[0]
        notified = conn.execute("SELECT COUNT(*) FROM bid_notices WHERE notified_at IS NOT NULL").fetchone()[0]
        last_notice = conn.execute("SELECT MAX(updated_at) FROM bid_notices").fetchone()[0]
    return {
        "total_notices": total,
        "filters": filters,
        "enabled_filters": enabled_filters,
        "notified_notices": notified,
        "last_notice_update": last_notice,
    }
