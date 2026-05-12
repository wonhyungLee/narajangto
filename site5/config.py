from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

ROOT_DIR = Path(__file__).resolve().parents[1]
API_INFO_FILE = ROOT_DIR / "공공데이터api.txt"
DISCORD_INFO_FILE = ROOT_DIR / "디스코드웹훅주소.txt"
DEFAULT_ENDPOINT = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp949")
    except FileNotFoundError:
        return ""


def _line_after(label: str, text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]
    for idx, line in enumerate(lines):
        if label in line:
            for value in lines[idx + 1 :]:
                if value:
                    return value
    return None


def _extract_endpoint(text: str) -> str:
    match = re.search(r"https?://apis\.data\.go\.kr/[^\s]+", text)
    if match:
        return match.group(0).strip().rstrip("/")
    return DEFAULT_ENDPOINT


def _normalize_service_key(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    # Public Data Portal examples usually require the encoded key in the raw URL.
    # If an unencoded key is supplied, encode it once for safe query construction.
    if "%" in value:
        return value
    return quote(value, safe="")


def _extract_service_key(text: str) -> str:
    env_value = os.getenv("G2B_SERVICE_KEY")
    if env_value:
        return _normalize_service_key(env_value)
    encoded = _line_after("일반 인증키(Encoding)", text)
    decoded = _line_after("일반 인증키(Decoding)", text)
    return _normalize_service_key(encoded or decoded)


def _extract_discord_webhook(text: str) -> str:
    env_value = os.getenv("DISCORD_WEBHOOK_URL")
    if env_value:
        return env_value.strip()
    match = re.search(r"https://(?:discord(?:app)?\.com)/api/webhooks/[^\s]+", text)
    return match.group(0).strip() if match else ""


def _extract_sheet_url(text: str) -> str:
    env_value = os.getenv("GOOGLE_SHEET_URL")
    if env_value:
        return env_value.strip()
    match = re.search(r"https://docs\.google\.com/spreadsheets/d/[^\s]+", text)
    return match.group(0).strip() if match else ""


def _extract_spreadsheet_id(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    return match.group(1) if match else ""


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _session_secret() -> str:
    env_value = os.getenv("SITE5_SESSION_SECRET")
    if env_value:
        return env_value.strip()
    secret_file = ROOT_DIR / "data" / ".site5_session_secret"
    try:
        return secret_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        secret_file.write_text(value, encoding="utf-8")
        secret_file.chmod(0o600)
        return value


@dataclass(frozen=True)
class Settings:
    api_endpoint: str
    service_key: str = field(repr=False)
    discord_webhook_url: str = field(repr=False)
    google_sheet_url: str = field(repr=False)
    google_spreadsheet_id: str = field(repr=False)
    google_sheet_name: str
    google_service_account_file: str = field(repr=False)
    google_service_account_json: str = field(repr=False)
    db_path: Path
    collect_interval_seconds: int
    sheet_sync_interval_seconds: int
    notify_interval_seconds: int
    default_collect_lookback_hours: int
    request_timeout_seconds: float
    enable_scheduler: bool
    login_username: str = field(repr=False)
    login_password: str = field(repr=False)
    session_secret: str = field(repr=False)

    @property
    def has_google_credentials(self) -> bool:
        return bool(self.google_service_account_file or self.google_service_account_json)

    @property
    def has_discord_webhook(self) -> bool:
        return bool(self.discord_webhook_url)

    @property
    def has_api_credentials(self) -> bool:
        return bool(self.api_endpoint and self.service_key)


def load_settings() -> Settings:
    api_text = _read_text(API_INFO_FILE)
    discord_text = _read_text(DISCORD_INFO_FILE)
    endpoint = os.getenv("G2B_API_ENDPOINT", _extract_endpoint(api_text)).strip().rstrip("/")
    sheet_url = _extract_sheet_url(discord_text)
    return Settings(
        api_endpoint=endpoint,
        service_key=_extract_service_key(api_text),
        discord_webhook_url=_extract_discord_webhook(discord_text),
        google_sheet_url=sheet_url,
        google_spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", _extract_spreadsheet_id(sheet_url)),
        google_sheet_name=os.getenv("GOOGLE_SHEET_NAME", "입찰공고"),
        google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
        db_path=Path(os.getenv("SITE5_DB_PATH", str(ROOT_DIR / "data" / "site5.db"))),
        collect_interval_seconds=_int_env("SITE5_COLLECT_INTERVAL_SECONDS", 600),
        sheet_sync_interval_seconds=_int_env("SITE5_SHEET_SYNC_INTERVAL_SECONDS", 3600),
        notify_interval_seconds=_int_env("SITE5_NOTIFY_INTERVAL_SECONDS", 300),
        default_collect_lookback_hours=_int_env("SITE5_DEFAULT_LOOKBACK_HOURS", 24),
        request_timeout_seconds=float(os.getenv("SITE5_REQUEST_TIMEOUT_SECONDS", "30")),
        enable_scheduler=_bool_env("SITE5_ENABLE_SCHEDULER", True),
        login_username=os.getenv("SITE5_LOGIN_USERNAME", "won2781"),
        login_password=os.getenv("SITE5_LOGIN_PASSWORD", "lee37535"),
        session_secret=_session_secret(),
    )
