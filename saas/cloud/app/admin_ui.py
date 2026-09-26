ADMIN_UI = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayZone Manager — Platform Admin</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,Tahoma,sans-serif;background:#08111f;color:#edf5ff}
*{box-sizing:border-box}body{margin:0}button,input{font:inherit}
.wrap{max-width:1180px;margin:auto;padding:22px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:24px;margin:0}.muted{color:#91a5bd}.card{background:#101d2e;border:1px solid #20364e;border-radius:16px;padding:18px;margin-top:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.stat{padding:14px;background:#0b1726;border-radius:12px}.stat b{display:block;font-size:25px;margin-top:6px}
.row{display:flex;gap:10px;flex-wrap:wrap}.field{background:#091523;border:1px solid #294661;color:white;border-radius:10px;padding:11px;min-width:170px}
.btn{border:0;border-radius:10px;padding:10px 14px;cursor:pointer;background:#2678ff;color:white}.btn.ghost{background:#18304a}.btn.bad{background:#8b2532}
table{width:100%;border-collapse:collapse;margin-top:8px}th,td{text-align:right;padding:10px;border-bottom:1px solid #21364c;font-size:14px}
.badge{display:inline-block;border-radius:99px;padding:4px 8px;background:#17324d}.ok{color:#62d28b}.off{color:#ff8a8a}
#login{max-width:430px;margin:9vh auto}.hide{display:none}.code{font-family:ui-monospace,Consolas,monospace;background:#07101c;padding:9px;border-radius:9px;word-break:break-all}
@media(max-width:650px){.wrap{padding:12px}table{display:block;overflow-x:auto}.field{width:100%}}
</style></head>
<body>
<div id="login" class="card">
<h1>PlayZone Manager</h1><p class="muted">Platform Admin</p>
<div class="row"><input id="u" class="field" placeholder="Username"><input id="p" class="field" type="password" placeholder="Password"></div>
<p><button class="btn" onclick="login()">دخول</button></p><div id="loginErr" class="off"></div>
</div>
<div id="app" class="wrap hide">
<div class="top"><div><h1>PlayZone Manager — Admin</h1><div class="muted">إدارة عملاء المنصة وأجهزة الـEdge</div></div><button class="btn ghost" onclick="logout()">خروج</button></div>
<div class="grid" id="stats"></div>
<div class="card">
<h3>إضافة عميل</h3>
<div class="row"><input id="cn" class="field" placeholder="اسم العميل"><input id="ou" class="field" placeholder="Owner username"><input id="op" class="field" type="password" placeholder="Owner password (8+)"></div>
<p><button class="btn" onclick="createCustomer()">إنشاء العميل</button></p><div id="createMsg"></div>
</div>
<div class="card"><div class="top"><h3>العملاء</h3><button class="btn ghost" onclick="refresh()">تحديث</button></div>
<table><thead><tr><th>الكود</th><th>العميل</th><th>الحالة</th><th>Edge</th><th>إجراء</th></tr></thead><tbody id="customers"></tbody></table>
</div>
<div class="card"><h3>أجهزة Edge</h3><table><thead><tr><th>Device ID</th><th>Tenant</th><th>الجهاز</th><th>الإصدار</th><th>آخر اتصال</th><th>الحالة</th></tr></thead><tbody id="edges"></tbody></table></div>
<div id="modal" class="card hide"><div class="top"><h3>Installation Code</h3><button class="btn ghost" onclick="document.getElementById('modal').classList.add('hide')">إغلاق</button></div><div id="installCode" class="code"></div><p class="muted" id="installExpiry"></p></div>
</div>
<script>
let token=localStorage.pzPlatformToken||'';
function H(){return {'Authorization':'Bearer '+token,'Content-Type':'application/json'}}
async function api(path,opt={}){const r=await fetch(path,{...opt,headers:{...H(),...(opt.headers||{})}});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||b.error||('HTTP '+r.status));return b}
async function login(){document.getElementById('loginErr').textContent='';try{const b=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:u.value,password:p.value})});if(b.user.role!=='PLATFORM_ADMIN')throw new Error('هذا الحساب ليس Platform Admin');token=b.token;localStorage.pzPlatformToken=token;show();await refresh()}catch(e){loginErr.textContent=e.message}}
function logout(){localStorage.removeItem('pzPlatformToken');token='';location.reload()}
function show(){login.classList.add('hide');app.classList.remove('hide')}
async function refresh(){try{const [t,e]=await Promise.all([api('/api/admin/tenants'),api('/api/admin/edge-devices')]);const cs=t.customers||[],ds=e.devices||[];stats.innerHTML=[['العملاء',cs.length],['أجهزة Edge',ds.length],['Active',cs.filter(x=>x.status==='ACTIVE').length],['Seen',ds.filter(x=>x.last_seen_at).length]].map(x=>`<div class="stat"><span class="muted">${x[0]}</span><b>${x[1]}</b></div>`).join('');
customers.innerHTML=cs.map(x=>`<tr><td><span class="badge">${x.code}</span></td><td>${esc(x.name)}</td><td class="${x.status==='ACTIVE'?'ok':'off'}">${x.status}</td><td>${x.edge_devices||0}</td><td><button class="btn" onclick="install(${x.id})">Installation Code</button></td></tr>`).join('');
edges.innerHTML=ds.map(x=>`<tr><td class="code">${x.id}</td><td>${x.tenant_id}</td><td>${esc(x.device_name)}</td><td>${esc(x.app_version||'-')}</td><td>${x.last_seen_at?new Date(x.last_seen_at).toLocaleString('ar-EG'):'-'}</td><td>${x.status}</td></tr>`).join('')}catch(e){if(String(e.message).includes('401'))logout();else alert(e.message)}}
async function createCustomer(){try{const b=await api('/api/admin/tenants',{method:'POST',body:JSON.stringify({name:cn.value,owner_username:ou.value,owner_password:op.value})});createMsg.innerHTML=`<span class="ok">تم: ${b.customer.code}</span>`;cn.value=ou.value=op.value='';await refresh()}catch(e){createMsg.innerHTML=`<span class="off">${esc(e.message)}</span>`}}
async function install(id){try{const b=await api('/api/admin/tenants/'+id+'/installation-codes',{method:'POST',body:JSON.stringify({expires_hours:24})});installCode.textContent=b.installation_code;installExpiry.textContent='صالح حتى: '+new Date(b.expires_at).toLocaleString('ar-EG');modal.classList.remove('hide');modal.scrollIntoView({behavior:'smooth'})}catch(e){alert(e.message)}}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
if(token){show();refresh()}
</script></body></html>"""
