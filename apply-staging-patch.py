from pathlib import Path

PLAYZONE = Path('/app/playzone')
MAIN = PLAYZONE / 'backend' / 'app' / 'main.py'
DIST = PLAYZONE / 'frontend' / 'dist' / 'assets'

backend = MAIN.read_text(encoding='utf-8')

# Railway/web deployment: expose the embedded Voltra dashboard through the
# authenticated PlayZone origin. The internal Voltra HTTP server remains bound
# to 127.0.0.1:8086 and is never exposed directly.
if 'def issue_voltra_console_ticket(' not in backend:
    backend = backend.replace(
        'from fastapi import Depends, FastAPI, Header, HTTPException, Query\n',
        'from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request\n'
        'from fastapi.responses import RedirectResponse, Response\n',
        1,
    )
    if 'import httpx\n' not in backend:
        backend = backend.replace('import time as time_module\n', 'import time as time_module\nimport httpx\n', 1)

    proxy = r'''
_VOLTRA_CONSOLE_COOKIE = "playzone_voltra_console"
_VOLTRA_CONSOLE_TICKETS: dict[str, float] = {}
_VOLTRA_CONSOLE_SESSIONS: dict[str, float] = {}


def _cleanup_voltra_console(now: float) -> None:
    for store in (_VOLTRA_CONSOLE_TICKETS, _VOLTRA_CONSOLE_SESSIONS):
        for key, expires_at in list(store.items()):
            if expires_at <= now:
                store.pop(key, None)


@app.post("/api/voltra/console-ticket")
def issue_voltra_console_ticket(_: User = Depends(root_ready_user)):
    now = time_module.time()
    _cleanup_voltra_console(now)
    ticket = secrets.token_urlsafe(32)
    _VOLTRA_CONSOLE_TICKETS[ticket] = now + 60
    return {"url": f"/voltra/authorize?ticket={ticket}"}


@app.get("/voltra/authorize")
def authorize_voltra_console(request: Request, ticket: str = Query(...)):
    now = time_module.time()
    _cleanup_voltra_console(now)
    expires_at = _VOLTRA_CONSOLE_TICKETS.pop(ticket, None)
    if not expires_at or expires_at <= now:
        raise HTTPException(401, "Invalid or expired Voltra console ticket")

    session_id = secrets.token_urlsafe(32)
    _VOLTRA_CONSOLE_SESSIONS[session_id] = now + 1800
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    )
    response = RedirectResponse(url="/voltra", status_code=303)
    response.set_cookie(
        _VOLTRA_CONSOLE_COOKIE,
        session_id,
        max_age=1800,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/voltra",
    )
    return response


def _require_voltra_console(request: Request) -> None:
    now = time_module.time()
    _cleanup_voltra_console(now)
    session_id = request.cookies.get(_VOLTRA_CONSOLE_COOKIE)
    expires_at = _VOLTRA_CONSOLE_SESSIONS.get(session_id or "")
    if not expires_at or expires_at <= now:
        raise HTTPException(401, "Open Voltra from the ROOT dashboard")


async def _proxy_voltra_request(request: Request, path: str = "") -> Response:
    _require_voltra_console(request)
    target = "http://127.0.0.1:8086/voltra"
    if path:
        target += "/" + path
    if request.url.query:
        target += "?" + request.url.query

    headers: dict[str, str] = {}
    if request.headers.get("content-type"):
        headers["content-type"] = request.headers["content-type"]
    internal_token = os.getenv("VOLTRA_API_TOKEN", "").strip()
    if internal_token:
        headers["authorization"] = f"Bearer {internal_token}"

    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=headers,
                content=body if body else None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Voltra console unavailable: {exc}") from exc

    response_headers = {}
    content_type = upstream.headers.get("content-type")
    if content_type:
        response_headers["content-type"] = content_type
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


@app.api_route("/voltra", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_voltra_root(request: Request):
    return await _proxy_voltra_request(request)


@app.api_route("/voltra/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_voltra_path(path: str, request: Request):
    return await _proxy_voltra_request(request, path)
'''
    # os is already imported in v0.17 through the deployment patch path only if needed.
    if 'import os\n' not in backend:
        backend = backend.replace('import sqlite3\n', 'import sqlite3\nimport os\n', 1)
    marker = '# Production UI: when `npm run build` has created frontend/dist, FastAPI serves'
    if marker not in backend:
        raise RuntimeError('Could not locate frontend static mount marker')
    backend = backend.replace(marker, proxy + '\n\n' + marker, 1)
    MAIN.write_text(backend, encoding='utf-8')

js_files = list(DIST.glob('*.js'))
if len(js_files) != 1:
    raise RuntimeError(f'Expected one frontend JS asset, found {len(js_files)}')
js_path = js_files[0]
js = js_path.read_text(encoding='utf-8')
old = '(0,j.jsx)(`a`,{className:`button ghost`,href:`http://127.0.0.1:8086/voltra`,target:`_blank`,rel:`noreferrer`,children:`لوحة Voltra`})'
new = '(0,j.jsx)(`button`,{className:`button ghost`,onClick:()=>{let e=window.open(`about:blank`,`_blank`);e&&(e.opener=null),t(async()=>{try{let r=await n(`/voltra/console-ticket`,`POST`);e?e.location.replace(r.url):window.location.href=r.url}catch(r){e&&e.close();throw r}},!1)},children:`لوحة Voltra`})'
if old in js:
    js = js.replace(old, new, 1)
elif '/voltra/console-ticket' not in js:
    raise RuntimeError('Could not locate Voltra localhost dashboard link')
js_path.write_text(js, encoding='utf-8')
