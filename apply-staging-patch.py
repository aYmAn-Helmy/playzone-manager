from pathlib import Path

BACKEND = Path("/app/playzone/backend/app/main.py")
DIST = Path("/app/playzone/frontend/dist/assets")

# Manual Voltra management is ROOT-only at the API layer.
backend = BACKEND.read_text(encoding="utf-8")
root_block = '''def root_user(user: User = Depends(current_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user
'''
root_ready = root_block + '''

def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user
'''
if "def root_ready_user(" not in backend:
    if root_block not in backend:
        raise RuntimeError("Could not locate root_user block")
    backend = backend.replace(root_block, root_ready, 1)

route_replacements = {
    "def sync_voltra_devices(actor: User = Depends(admin_user), db: Session = Depends(get_db)):": "def sync_voltra_devices(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def list_voltra_power(_: User = Depends(admin_user), db: Session = Depends(get_db)):": "def list_voltra_power(_: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def get_voltra_power(station_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):": "def get_voltra_power(station_id: int, _: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def change_voltra_power(station_id: int, action: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):": "def change_voltra_power(station_id: int, action: str, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
}
for old, new in route_replacements.items():
    if old not in backend:
        raise RuntimeError(f"Could not locate backend route: {old}")
    backend = backend.replace(old, new, 1)
BACKEND.write_text(backend, encoding="utf-8")

# Hide Voltra navigation/view for ADMIN. ROOT keeps the page.
js_files = list(DIST.glob("*.js"))
if len(js_files) != 1:
    raise RuntimeError(f"Expected one JS asset, found {len(js_files)}")
js_path = js_files[0]
js = js_path.read_text(encoding="utf-8")
js_replacements = {
    "t===\`voltra\`&&n&&[\`ROOT\`,\`ADMIN\`].includes(n.role)": "t===\`voltra\`&&n?.role===\`ROOT\`",
    "Ue=He?[\`home\`,\`stations\`,\`sessions\`,\`invoices\`,\`products\`,\`reports\`,\`users\`,\`voltra\`,\`settings\`]:[\`home\`,\`stations\`,\`sessions\`,\`invoices\`]": "Ue=He?[\`home\`,\`stations\`,\`sessions\`,\`invoices\`,\`products\`,\`reports\`,\`users\`,\`voltra\`,\`settings\`].filter(e=>e!==\`voltra\`||n?.role===\`ROOT\`):[\`home\`,\`stations\`,\`sessions\`,\`invoices\`]",
    "o===\`voltra\`&&He&&(0,j.jsx)(pt,{devices:ae,run:Le,api:A})": "o===\`voltra\`&&n?.role===\`ROOT\`&&(0,j.jsx)(pt,{devices:ae,run:Le,api:A})",
}
for old, new in js_replacements.items():
    if old not in js:
        raise RuntimeError(f"Could not locate frontend marker: {old[:80]}")
    js = js.replace(old, new, 1)
js_path.write_text(js, encoding="utf-8")

# Readability pass: enlarge only the tiny supporting text; keep layout/heads compact.
css_files = list(DIST.glob("*.css"))
if len(css_files) != 1:
    raise RuntimeError(f"Expected one CSS asset, found {len(css_files)}")
css_path = css_files[0]
css = css_path.read_text(encoding="utf-8")
readability = r'''
/* PlayZone readability pass v0.6 */
.brand small,.side-caption,.eyebrow,.page-heading p,.clock-card small,
.shift-chip b,.shift-chip small,.stat span,.mini-stat span,.section-title p,
.section-title>span,.status-pill,.station-title span,.grace-banner,
.station-actions .button,.rail-title small,.recent-row strong,.empty-state,
.system-row b,label,.muted,.security-message,.shift-warning span,.login-panel p,
.receipt-head p,.activation-notice span,.machine-card span,.machine-mismatch span,
.activation-status-badge{font-size:12px!important}
.mini-stat strong,.modal-line,.station-total,.text-button,table,.recent-row b,
.activation-settings-grid strong{font-size:12px!important}
.live-dot,.recent-row span,.system-row small{font-size:10px!important}
.activation-settings-grid span,.drawer-formula{font-size:11px!important}
'''
if "PlayZone readability pass v0.6" not in css:
    css += readability
css_path.write_text(css, encoding="utf-8")
