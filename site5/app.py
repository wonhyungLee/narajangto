from __future__ import annotations

import asyncio
import hmac
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import db
from .config import ROOT_DIR, Settings, load_settings
from .services import collect_bid_notices, process_notifications, sync_sheet

settings = load_settings()
templates = Environment(
    loader=FileSystemLoader(str(ROOT_DIR / "site5" / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)
SESSION_AUTH_KEY = "site5_authenticated"


def json_ok(data: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)


def json_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "message": message}, status_code=status_code)


def error_message(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _request_target(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/site5"
    split = urlsplit(value.strip())
    if split.scheme or split.netloc or not split.path.startswith("/site5") or split.path.startswith("//"):
        return "/site5"
    if split.path.startswith("/site5/login") or split.path.startswith("/site5/static"):
        return "/site5"
    return urlunsplit(("", "", split.path, split.query, ""))


def _is_authenticated(request: Request) -> bool:
    return request.session.get(SESSION_AUTH_KEY) is True


def _login_redirect(request: Request) -> Response:
    next_url = _safe_next_url(_request_target(request))
    if request.url.path.startswith("/site5/api/"):
        return json_error("로그인이 필요합니다.", 401)
    return RedirectResponse(url=f"/site5/login?{urlencode({'next': next_url})}", status_code=303)


def require_login(endpoint: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
    async def wrapped(request: Request) -> Response:
        if not _is_authenticated(request):
            return _login_redirect(request)
        return await endpoint(request)

    return wrapped


def _form_value(values: dict[str, list[str]], key: str) -> str:
    return values.get(key, [""])[0]


async def login_page(request: Request) -> Response:
    next_url = _safe_next_url(request.query_params.get("next"))
    if _is_authenticated(request):
        return RedirectResponse(url=next_url, status_code=303)
    template = templates.get_template("login.html")
    return HTMLResponse(template.render(request=request, error="", next_url=next_url))


async def login_submit(request: Request) -> Response:
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw_body, keep_blank_values=True)
    username = _form_value(form, "username")
    password = _form_value(form, "password")
    next_url = _safe_next_url(_form_value(form, "next"))

    username_ok = hmac.compare_digest(username, settings.login_username)
    password_ok = hmac.compare_digest(password, settings.login_password)
    if username_ok and password_ok:
        request.session.clear()
        request.session[SESSION_AUTH_KEY] = True
        return RedirectResponse(url=next_url, status_code=303)

    template = templates.get_template("login.html")
    html = template.render(
        request=request,
        error="아이디 또는 비밀번호가 올바르지 않습니다.",
        next_url=next_url,
    )
    return HTMLResponse(html, status_code=401)


async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/site5/login", status_code=303)


async def home(request: Request) -> HTMLResponse:
    template = templates.get_template("index.html")
    html = template.render(
        request=request,
        has_api_credentials=settings.has_api_credentials,
        has_discord_webhook=settings.has_discord_webhook,
        has_google_sheet=bool(settings.google_spreadsheet_id),
        has_google_credentials=settings.has_google_credentials,
        collect_interval=settings.collect_interval_seconds,
        sheet_interval=settings.sheet_sync_interval_seconds,
    )
    return HTMLResponse(html)


async def redirect_root(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/site5")


async def api_status(request: Request) -> JSONResponse:
    return json_ok(
        {
            "status": "ok",
            "config": {
                "api_endpoint": settings.api_endpoint,
                "has_service_key": settings.has_api_credentials,
                "has_discord_webhook": settings.has_discord_webhook,
                "has_google_sheet": bool(settings.google_spreadsheet_id),
                "has_google_credentials": settings.has_google_credentials,
                "google_sheet_name": settings.google_sheet_name,
                "db_path": str(settings.db_path),
                "collect_interval_seconds": settings.collect_interval_seconds,
                "sheet_sync_interval_seconds": settings.sheet_sync_interval_seconds,
                "enable_scheduler": settings.enable_scheduler,
            },
            "stats": db.stats(settings.db_path),
            "jobs": db.latest_jobs(settings.db_path),
        }
    )


async def api_notices(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    try:
        result = db.list_notices(settings.db_path, params)
    except Exception as exc:
        return json_error(error_message(exc), 400)
    return json_ok(result)


async def api_filters(request: Request) -> JSONResponse:
    if request.method == "GET":
        return json_ok({"items": db.list_filters(settings.db_path)})
    payload = await request.json()
    saved = db.save_filter(settings.db_path, payload)
    return json_ok({"item": saved}, 201)


async def api_filter_detail(request: Request) -> JSONResponse:
    filter_id = int(request.path_params["filter_id"])
    if request.method == "DELETE":
        db.delete_filter(settings.db_path, filter_id)
        return json_ok({"status": "ok"})
    payload = await request.json()
    saved = db.save_filter(settings.db_path, payload, filter_id=filter_id)
    return json_ok({"item": saved})


async def api_collect(request: Request) -> JSONResponse:
    payload: dict[str, Any] = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
    lookback_hours = payload.get("lookback_hours") or request.query_params.get("lookback_hours")
    try:
        result = await collect_bid_notices(settings, int(lookback_hours) if lookback_hours else None)
        return json_ok(result)
    except Exception as exc:
        return json_error(error_message(exc), 500)


async def api_notify(request: Request) -> JSONResponse:
    try:
        result = await process_notifications(settings)
        return json_ok(result)
    except Exception as exc:
        return json_error(error_message(exc), 500)


async def api_sheet_sync(request: Request) -> JSONResponse:
    try:
        result = await sync_sheet(settings)
        return json_ok(result)
    except Exception as exc:
        return json_error(error_message(exc), 500)


async def _periodic_loop(
    app: Starlette,
    name: str,
    interval_seconds: int,
    job: Callable[[], Awaitable[dict[str, Any]]],
    initial_delay: int,
) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Errors are persisted in job_runs by each service. Keep scheduler alive.
            pass
        await asyncio.sleep(interval_seconds)


async def on_startup() -> None:
    db.init_db(settings.db_path)
    if not settings.enable_scheduler:
        app.state.tasks = []
        return
    app.state.tasks = [
        asyncio.create_task(
            _periodic_loop(
                app,
                "collect_bid_notices",
                settings.collect_interval_seconds,
                lambda: collect_bid_notices(settings),
                5,
            )
        ),
        asyncio.create_task(
            _periodic_loop(
                app,
                "discord_notifications",
                settings.notify_interval_seconds,
                lambda: process_notifications(settings),
                20,
            )
        ),
        asyncio.create_task(
            _periodic_loop(
                app,
                "sheet_sync",
                settings.sheet_sync_interval_seconds,
                lambda: sync_sheet(settings),
                45,
            )
        ),
    ]


async def on_shutdown() -> None:
    for task in getattr(app.state, "tasks", []):
        task.cancel()
    if getattr(app.state, "tasks", None):
        await asyncio.gather(*app.state.tasks, return_exceptions=True)


site_routes = [
    Route("/", require_login(home), methods=["GET"]),
    Route("/login", login_page, methods=["GET"]),
    Route("/login", login_submit, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/api/status", require_login(api_status), methods=["GET"]),
    Route("/api/notices", require_login(api_notices), methods=["GET"]),
    Route("/api/filters", require_login(api_filters), methods=["GET", "POST"]),
    Route("/api/filters/{filter_id:int}", require_login(api_filter_detail), methods=["PUT", "DELETE"]),
    Route("/api/jobs/collect", require_login(api_collect), methods=["POST"]),
    Route("/api/jobs/notify", require_login(api_notify), methods=["POST"]),
    Route("/api/jobs/sync-sheet", require_login(api_sheet_sync), methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(ROOT_DIR / "site5" / "static")), name="static"),
]

app = Starlette(
    routes=[Route("/", redirect_root, methods=["GET"]), Mount("/site5", routes=site_routes)],
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
    middleware=[
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            session_cookie="site5_session",
            same_site="lax",
            path="/site5",
        )
    ],
)
