from pathlib import Path

PLAYZONE = Path('/app/playzone')
MAIN = PLAYZONE / 'backend' / 'app' / 'main.py'
DIST = PLAYZONE / 'frontend' / 'dist' / 'assets'

backend = MAIN.read_text(encoding='utf-8')
imp = 'from .voltra import VoltraError, power_status as voltra_power_status, set_power as voltra_set_power, sync_stations as voltra_sync_stations\n'
ts_imp = 'from .tailscale_support import TailscaleSupportError, get_status as tailscale_status, reconnect as tailscale_reconnect\n'
if ts_imp not in backend:
    if imp not in backend:
        raise RuntimeError('Could not locate Voltra import for Tailscale support patch')
    backend = backend.replace(imp, imp + ts_imp, 1)

backend = backend.replace(
    'app = FastAPI(title="PlayZone Manager API", version="0.17.0")',
    'app = FastAPI(title="PlayZone Manager API", version="0.21.0")',
    1,
)

if '/api/root/tailscale/status' not in backend:
    marker = '''def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user


'''
    block = marker + '''@app.get("/api/root/tailscale/status")
def api_tailscale_status(_: User = Depends(root_ready_user)):
    return tailscale_status()


@app.post("/api/root/tailscale/reconnect")
def api_tailscale_reconnect(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    try:
        status = tailscale_reconnect()
    except TailscaleSupportError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "TAILSCALE_RECONNECT", "system", None, f"ip={status.get('ipv4') or '-'} state={status.get('state') or '-'}")
    db.commit()
    return status


'''
    if marker not in backend:
        raise RuntimeError('Could not locate ROOT dependency block for Tailscale support patch')
    backend = backend.replace(marker, block, 1)
MAIN.write_text(backend, encoding='utf-8')

js_files = list(DIST.glob('*.js'))
if len(js_files) != 1:
    raise RuntimeError(f'Expected one frontend JS asset for v0.21, found {len(js_files)}')
js_path = js_files[0]
js = js_path.read_text(encoding='utf-8')
component_marker = 'function ZtUi({config:e={},paymentMethods:pmt={},timedConfig:timed={},run:t,api:n})'
component = r'''function PzTailscaleSupport({api:e}){let[t,n]=(0,C.useState)(null),[r,i]=(0,C.useState)(!1),[a,o]=(0,C.useState)(``);async function s(){try{let t=await e(`/root/tailscale/status`);n(t),o(``)}catch(e){o(e.message)}}(0,C.useEffect)(()=>{s();let e=setInterval(s,1e4);return()=>clearInterval(e)},[]);async function c(){i(!0),o(``);try{let t=await e(`/root/tailscale/reconnect`,`POST`);n(t)}catch(e){o(e.message)}finally{i(!1)}}let l=t?.connected?`متصل وجاهز للدعم`:t?.needs_login?`يحتاج تهيئة`:t?.installed?`غير متصل`:`غير مثبت`,u=t?.connected?`online`:t?.needs_login?`warn`:`offline`;return(0,j.jsxs)(`section`,{className:`content-section tailscale-support-card`,children:[(0,j.jsxs)(`div`,{className:`section-title`,children:[(0,j.jsxs)(`div`,{children:[(0,j.jsx)(`h2`,{children:`الدعم الفني عن بُعد — Tailscale`}),(0,j.jsx)(`p`,{children:`قناة دعم دائمة خاصة بـ ROOT. تعمل في وضع Unattended وتظل متصلة بعد Restart أو Logoff.`})]}),(0,j.jsxs)(`span`,{className:`tailscale-status ${u}`,children:[(0,j.jsx)(`i`,{}),l]})]}),t?.supported===!1?(0,j.jsx)(`div`,{className:`tailscale-note`,children:`هذه الوظيفة مخصصة لنسخة PlayZone المحلية على Windows.`}):t?.installed?(0,j.jsxs)(j.Fragment,{children:[(0,j.jsxs)(`div`,{className:`tailscale-details`,children:[(0,j.jsxs)(`div`,{children:[(0,j.jsx)(`span`,{children:`حالة الاتصال`}),(0,j.jsx)(`strong`,{children:l})]}),(0,j.jsxs)(`div`,{children:[(0,j.jsx)(`span`,{children:`Tailscale IP`}),(0,j.jsx)(`code`,{dir:`ltr`,children:t.ipv4||`—`})]}),(0,j.jsxs)(`div`,{children:[(0,j.jsx)(`span`,{children:`اسم الجهاز`}),(0,j.jsx)(`strong`,{dir:`ltr`,children:t.dns_name||t.hostname||`—`})]}),(0,j.jsxs)(`div`,{children:[(0,j.jsx)(`span`,{children:`Always-On`}),(0,j.jsx)(`strong`,{children:t.always_on?`مفعّل`:`يحتاج مراجعة`})]})]}),t.needs_login?(0,j.jsx)(`div`,{className:`tailscale-note warn`,children:`الجهاز لم يتم ربطه بالـTailnet بعد. شغّل Setup-Tailscale-Support.bat مرة واحدة كمسؤول وأدخل مفتاح التفعيل one-off.`}):(0,j.jsxs)(`div`,{className:`tailscale-actions`,children:[(0,j.jsx)(`button`,{type:`button`,className:`button primary`,disabled:r,onClick:c,children:r?`جاري إعادة الاتصال...`:`إعادة الاتصال / إصلاح`}),(0,j.jsx)(`button`,{type:`button`,className:`text-button`,disabled:r,onClick:s,children:`تحديث الحالة`})]}),t.connected&&(0,j.jsx)(`p`,{className:`tailscale-privacy`,children:`الدعم متاح دائماً من أجهزة الدعم المسموح لها داخل Tailnet. لا يتم عرض هذه البيانات إلا لحساب ROOT.`})]}):(0,j.jsx)(`div`,{className:`tailscale-note warn`,children:`Tailscale غير مثبت. شغّل Setup-Tailscale-Support.bat مرة واحدة على جهاز العميل بواسطة IT.`}),a&&(0,j.jsx)(`p`,{className:`security-message`,children:a})]})}'''
if 'function PzTailscaleSupport(' not in js:
    if component_marker not in js:
        raise RuntimeError('Could not locate ROOT customization component for v0.21')
    js = js.replace(component_marker, component + component_marker, 1)

old = 'return(0,j.jsxs)(j.Fragment,{children:[(0,j.jsxs)(`section`,{className:`content-section ui-profile-intro`'
new = 'return(0,j.jsxs)(j.Fragment,{children:[(0,j.jsx)(PzTailscaleSupport,{api:n}),(0,j.jsxs)(`section`,{className:`content-section ui-profile-intro`'
if old in js:
    js = js.replace(old, new, 1)
elif 'PzTailscaleSupport,{api:n}' not in js:
    raise RuntimeError('Could not inject Tailscale support card into ROOT page')
js_path.write_text(js, encoding='utf-8')

css_files = list(DIST.glob('*.css'))
if len(css_files) != 1:
    raise RuntimeError(f'Expected one frontend CSS asset for v0.21, found {len(css_files)}')
css_path = css_files[0]
css = css_path.read_text(encoding='utf-8')
css_marker = '/* v0.21 ROOT-only Always-On Tailscale support */'
if css_marker not in css:
    css += '\n' + css_marker + '\n.tailscale-support-card{border:1px solid #2d68ff55;background:linear-gradient(180deg,#13223b,#101827);box-shadow:0 10px 28px #0000001f}.tailscale-status{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;font-weight:800;font-size:12px;background:#1b2433;border:1px solid #ffffff14;white-space:nowrap}.tailscale-status i{width:9px;height:9px;border-radius:50%;display:block;background:#7c8799}.tailscale-status.online{color:#9af0c3;border-color:#2fc87d55;background:#123326}.tailscale-status.online i{background:#2fd17e;box-shadow:0 0 0 4px #2fd17e22}.tailscale-status.warn{color:#ffd991;border-color:#f0ad3d55;background:#342713}.tailscale-status.warn i{background:#f0ad3d}.tailscale-status.offline{color:#c4ccda}.tailscale-details{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}.tailscale-details>div{display:flex;flex-direction:column;gap:6px;padding:13px 14px;border-radius:12px;background:#0c1421;border:1px solid #ffffff0d;min-width:0}.tailscale-details span{font-size:12px;color:#92a0b4}.tailscale-details strong,.tailscale-details code{font-size:13px;color:#edf4ff;overflow-wrap:anywhere}.tailscale-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:16px}.tailscale-note{margin-top:14px;padding:12px 14px;border-radius:10px;background:#101a2a;border:1px solid #ffffff12;color:#b9c4d4;line-height:1.7}.tailscale-note.warn{background:#302514;border-color:#e5a23a44;color:#f0d6a5}.tailscale-privacy{margin:12px 0 0;color:#91d8b5;font-size:12px}.tailscale-support-card .security-message{margin-top:12px}@media(max-width:900px){.tailscale-details{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.tailscale-details{grid-template-columns:1fr}}\n'
css_path.write_text(css, encoding='utf-8')

index_path = PLAYZONE / 'frontend' / 'dist' / 'index.html'
index_html = index_path.read_text(encoding='utf-8')
new_js_path = js_path.with_name('index-v021.js')
new_css_path = css_path.with_name('index-v021.css')
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
