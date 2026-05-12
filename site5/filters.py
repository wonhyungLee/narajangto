from __future__ import annotations

from typing import Any


def split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    terms: list[str] = []
    for chunk in value.replace("\n", ",").split(","):
        term = chunk.strip().lower()
        if term:
            terms.append(term)
    return terms


def _text_blob(notice: dict[str, Any]) -> str:
    fields = [
        "bid_ntce_nm",
        "bsns_div_nm",
        "ntce_instt_nm",
        "dmnd_instt_nm",
        "prtcpt_psbl_rgn_nm",
        "bidprc_psbl_indstryty_nm",
        "cntrct_cncls_mthd_nm",
        "bidwinr_dcsn_mthd_nm",
    ]
    return " ".join(str(notice.get(field) or "") for field in fields).lower()


def _amount(notice: dict[str, Any]) -> int:
    for field in ("presmpt_prce", "asign_bdgt_amt"):
        value = notice.get(field)
        if isinstance(value, int):
            return value
        if value not in (None, ""):
            try:
                return int(value)
            except ValueError:
                continue
    return 0


def matches_filter(notice: dict[str, Any], filter_row: dict[str, Any]) -> bool:
    if not filter_row.get("enabled"):
        return False

    blob = _text_blob(notice)
    keywords = split_terms(filter_row.get("keywords"))
    if keywords and not any(term in blob for term in keywords):
        return False

    excludes = split_terms(filter_row.get("exclude_keywords"))
    if excludes and any(term in blob for term in excludes):
        return False

    business_types = split_terms(filter_row.get("business_types"))
    if business_types:
        business = str(notice.get("bsns_div_nm") or "").lower()
        if not any(term == business or term in business for term in business_types):
            return False

    regions = split_terms(filter_row.get("regions"))
    if regions:
        region_blob = str(notice.get("prtcpt_psbl_rgn_nm") or "").lower()
        if not any(term in region_blob for term in regions):
            return False

    institutions = split_terms(filter_row.get("institutions"))
    if institutions:
        institution_blob = f"{notice.get('ntce_instt_nm') or ''} {notice.get('dmnd_instt_nm') or ''}".lower()
        if not any(term in institution_blob for term in institutions):
            return False

    amount = _amount(notice)
    min_amount = filter_row.get("min_amount")
    if min_amount not in (None, "") and amount < int(min_amount):
        return False
    max_amount = filter_row.get("max_amount")
    if max_amount not in (None, "") and amount > int(max_amount):
        return False

    region_limit = str(filter_row.get("require_region_limit") or "any").lower()
    notice_region_limit = str(notice.get("rgn_lmt_yn") or "").upper()
    if region_limit == "yes" and notice_region_limit != "Y":
        return False
    if region_limit == "no" and notice_region_limit == "Y":
        return False

    return True
