from pathlib import Path

PLAYZONE = Path('/app/playzone')
MAIN = PLAYZONE / 'backend' / 'app' / 'main.py'
DIST = PLAYZONE / 'frontend' / 'dist' / 'assets'

backend = MAIN.read_text(encoding='utf-8')
backend = backend.replace(
    'app = FastAPI(title="PlayZone Manager API", version="0.21.0")',
    'app = FastAPI(title="PlayZone Manager API", version="0.22.0")',
    1,
)
MAIN.write_text(backend, encoding='utf-8')

js_files = list(DIST.glob('*.js'))
if len(js_files) != 1:
    raise RuntimeError(f'Expected one frontend JS asset for v0.22, found {len(js_files)}')
js_path = js_files[0]
js = js_path.read_text(encoding='utf-8')

# Timed-session station cards accidentally render the raw Lucide timer icon
# definition object (ze) instead of its React component (Be). React crashes as
# soon as a TIMED session is visible, leaving only the dark app background.
bad = '(0,j.jsx)(ze,{size:15}),` + وقت`'
good = '(0,j.jsx)(Be,{size:15}),` + وقت`'
if bad in js:
    js = js.replace(bad, good, 1)
elif good not in js:
    raise RuntimeError('Could not locate timed-session extend icon reference')
js_path.write_text(js, encoding='utf-8')

css_files = list(DIST.glob('*.css'))
if len(css_files) != 1:
    raise RuntimeError(f'Expected one frontend CSS asset for v0.22, found {len(css_files)}')
css_path = css_files[0]

# Cache-bust the hotfix so browsers cannot keep the crashing v0.21 bundle.
index_path = PLAYZONE / 'frontend' / 'dist' / 'index.html'
index_html = index_path.read_text(encoding='utf-8')
new_js_path = js_path.with_name('index-v022.js')
new_css_path = css_path.with_name('index-v022.css')
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