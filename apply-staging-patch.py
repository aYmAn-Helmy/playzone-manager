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


# v0.18 dashboard identity + English clock digits
js_files = list(DIST.glob('*.js'))
if len(js_files) != 1:
    raise RuntimeError(f'Expected one frontend JS asset for v0.18, found {len(js_files)}')
js_path = js_files[0]
js = js_path.read_text(encoding='utf-8')

old_station_icon = '(0,j.jsx)(`span`,{className:`station-icon`,children:(0,j.jsx)(_e,{size:23})})'
new_station_icon = '(0,j.jsx)(`span`,{className:`station-icon station-ps-icon`,children:(0,j.jsxs)(`svg`,{className:`station-ps-logo`,viewBox:`0 0 64 64`,"aria-hidden":!0,focusable:`false`,children:[(0,j.jsx)(`path`,{d:`M24 7c9 1 18 4 21 9 2 4 1 9-3 12-3 2-8 3-13 2v-8c4 .7 7 0 7-3 0-2-3-4-7-4v28l-8 2V8l3-1Z`}),(0,j.jsx)(`path`,{d:`M17 43c9-3 23-6 32-4 7 1 8 5 2 9-8 5-26 9-38 6-7-2-8-6-1-9 4-2 10-3 15-4v6c-5 1-9 2-10 3 6 2 19 0 28-3 4-1 6-3 4-4-2-1-7 0-12 1l-7 2v-8Z`})]})})'
if old_station_icon in js:
    js = js.replace(old_station_icon, new_station_icon, 1)
elif 'station-ps-logo' not in js:
    raise RuntimeError('Could not locate station gamepad icon for v0.18')

old_clock = '(0,j.jsx)(`strong`,{children:new Intl.DateTimeFormat(`ar-EG`,{timeZone:`Africa/Cairo`,hour:`2-digit`,minute:`2-digit`,second:`2-digit`}).format(new Date)})'
new_clock = '(0,j.jsx)(`strong`,{dir:`ltr`,lang:`en`,children:new Intl.DateTimeFormat(`en-US`,{timeZone:`Africa/Cairo`,hour:`2-digit`,minute:`2-digit`,second:`2-digit`,hour12:!0}).format(new Date)})'
if old_clock in js:
    js = js.replace(old_clock, new_clock, 1)
elif 'Intl.DateTimeFormat(`en-US`' not in js:
    raise RuntimeError('Could not locate dashboard clock for v0.18')

js_path.write_text(js, encoding='utf-8')

css_files = list(DIST.glob('*.css'))
if len(css_files) != 1:
    raise RuntimeError(f'Expected one frontend CSS asset for v0.18, found {len(css_files)}')
css_path = css_files[0]
css = css_path.read_text(encoding='utf-8')
css_marker = '/* v0.18 PlayStation station mark */'
if css_marker not in css:
    css += '\n' + css_marker + '\n.station-ps-icon{color:#57a8ff}.station-ps-logo{width:25px;height:25px;display:block;fill:currentColor}.clock-card strong{unicode-bidi:isolate;direction:ltr;text-align:left}\n'
css_path.write_text(css, encoding='utf-8')

# Rename assets so browsers cannot keep the older v0.17 UI from cache.
index_path = PLAYZONE / 'frontend' / 'dist' / 'index.html'
index_html = index_path.read_text(encoding='utf-8')
new_js_path = js_path.with_name('index-v018.js')
new_css_path = css_path.with_name('index-v018.css')
if js_path != new_js_path:
    if new_js_path.exists():
        new_js_path.unlink()
    js_path.rename(new_js_path)
    index_html = index_html.replace(js_path.name, new_js_path.name)
if css_path != new_css_path:
    if new_css_path.exists():
        new_css_path.unlink()
    css_path.rename(new_css_path)
    index_html = index_html.replace(css_path.name, new_css_path.name)
index_path.write_text(index_html, encoding='utf-8')
