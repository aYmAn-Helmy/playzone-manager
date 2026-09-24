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


# v0.19 PlayStation badge + English clock digits
js_files = list(DIST.glob('*.js'))
if len(js_files) != 1:
    raise RuntimeError(f'Expected one frontend JS asset for v0.18, found {len(js_files)}')
js_path = js_files[0]
js = js_path.read_text(encoding='utf-8')

old_station_icon = '(0,j.jsx)(`span`,{className:`station-icon`,children:(0,j.jsx)(_e,{size:23})})'
new_station_icon = '(0,j.jsx)(`span`,{className:`station-icon station-ps-icon`,children:(0,j.jsx)(`svg`,{className:`station-ps-logo`,viewBox:`0 0 24 24`,"aria-hidden":!0,focusable:`false`,children:(0,j.jsx)(`path`,{d:`M8.984 2.596v17.547l3.915 1.261V6.688c0-.69.304-1.151.794-.991.636.18.76.814.76 1.505v5.875c2.441 1.193 4.362-.002 4.362-3.152 0-3.237-1.126-4.675-4.438-5.827-1.307-.448-3.728-1.186-5.39-1.502zm4.656 16.241 6.296-2.275c.715-.258.826-.625.246-.818-.586-.192-1.637-.139-2.357.123l-4.205 1.5V14.98l.24-.085s1.201-.42 2.913-.615c1.696-.18 3.785.03 5.437.661 1.848.601 2.04 1.472 1.576 2.072-.465.6-1.622 1.036-1.622 1.036l-8.544 3.107V18.86zM1.807 18.6c-1.9-.545-2.214-1.668-1.352-2.32.801-.586 2.16-1.052 2.16-1.052l5.615-2.013v2.313L4.205 17c-.705.271-.825.632-.239.826.586.195 1.637.15 2.343-.12L8.247 17v2.074c-.12.03-.256.044-.39.073-1.939.331-3.996.196-6.038-.479z`})})})'
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
css_marker = '/* v0.19 PlayStation station mark */'
if css_marker not in css:
    css += '\n' + css_marker + '\n.station-ps-icon{color:#fff!important;background:#0070d1!important;border-color:#2a8bea!important;box-shadow:0 6px 16px #0070d133}.station-ps-logo{width:26px;height:26px;display:block;fill:#fff}.clock-card strong{unicode-bidi:isolate;direction:ltr;text-align:left}\n'
css_path.write_text(css, encoding='utf-8')

# Rename assets so browsers cannot keep the older v0.17 UI from cache.
index_path = PLAYZONE / 'frontend' / 'dist' / 'index.html'
index_html = index_path.read_text(encoding='utf-8')
new_js_path = js_path.with_name('index-v019.js')
new_css_path = css_path.with_name('index-v019.css')
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
