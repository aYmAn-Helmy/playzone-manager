from __future__ import annotations

PLATFORM_ADMIN_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayZone Manager - Platform Admin</title>
<style>
:root{font-family:Segoe UI,Tahoma,Arial,sans-serif;color-scheme:dark;background:#07111f;color:#eef6ff}
*{box-sizing:border-box}body{margin:0;background:#07111f}.wrap{max-width:1180px;margin:auto;padding:18px}
h1,h2,h3{margin:.2em 0 .6em}.muted{color:#91a4ba}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.card{background:#0d1b2c;border:1px solid #1c3550;border-radius:16px;padding:16px;box-shadow:0 10px 30px #0004}
input,button{width:100%;padding:11px 12px;border-radius:10px;border:1px solid #294863;background:#091725;color:#fff;margin:5px 0}
button{background:#1473e6;border:0;font-weight:700;cursor:pointer}.danger{background:#a93232}.ghost{background:#15283b}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#16324b;font-size:12px}
.ok{color:#63e6a6}.bad{color:#ff8c8c}.code{font-family:Consolas,monospace;direction:ltr;text-align:center;font-size:20px;letter-spacing:1px;background:#06101b;padding:10px;border-radius:10px}
table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid #1a3149;text-align:right}
.hidden{display:none}@media(max-width:650px){.wrap{padding:10px}table{font-size:12px}.row{display:block}}
</style>
</head><body><div class="wrap">
<h1>PlayZone Manager <span class="muted">Platform Admin</span></h1>
<div id="login" class="card" style="max-width:420px;margin:30px auto">
<h2>دخول إدارة المنصة</h2><input id="u" placeholder="Username"><input id="p" type="password" placeholder="Password">
<button onclick="login()">دخول</button><div id="loginMsg" class="bad"></div></div>
<div id="app" class="hidden">
<div class="grid">
<div class="card"><h2>إضافة عميل</h2>
<input id="cname" placeholder="اسم العميل"><input id="owner" placeholder="Owner username">
<input id="ownerpass" type="password" placeholder="Owner temporary password (8+)">
<input id="ownername" placeholder="اسم المالك">
<button onclick="createCustomer()">إنشاء العميل</button><div id="createMsg"></div></div>
<div class="card"><h2>آخر Installation Code</h2><div id="installCode" class="code">—</div><div id="installMeta" class="muted"></div></div>
</div>
<div class="card" style="margin-top:14px"><div class="row"><h2>العملاء</h2><button class="ghost" onclick="refreshAll()">تحديث</button></div>
<div style="overflow:auto"><table><thead><tr><th>Code</th><th>العميل</th><th>Edge</th><th>الحالة</th><th></th></tr></thead><tbody id="customers"></tbody></table></div></div>
<div class="card" style="margin-top:14px"><h2>أجهزة Edge</h2><div style="overflow:auto"><table><thead><tr><th>Device</th><th>Tenant</th><th>Version</th><th>Last Seen</th><th>الحالة</th><th></th></tr></thead><tbody id="devices"></tbody></table></div></div>
</div></div>
<script>
let token=sessionStorage.getItem('pz_platform_token')||'';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function api(path,opt={}){const h={'Content-Type':'application/json',...(opt.headers||{})};if(token)h.Authorization='Bearer '+token;const r=await fetch(path,{...opt,headers:h});let b={};try{b=await r.json()}catch{}if(!r.ok)throw new Error(b.detail||('HTTP '+r.status));return b}
async function login(){try{const b=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:u.value,password:p.value})});token=b.token;sessionStorage.setItem('pz_platform_token',token);showApp();await refreshAll()}catch(e){loginMsg.textContent=e.message}}
function showApp(){login.classList.add('hidden');app.classList.remove('hidden')}
async function createCustomer(){try{const b=await api('/api/admin/tenants',{method:'POST',body:JSON.stringify({name:cname.value,owner_username:owner.value,owner_password:ownerpass.value,owner_display_name:ownername.value||null})});createMsg.innerHTML='<span class="ok">تم إنشاء '+esc(b.customer.code)+'</span>';await refreshAll()}catch(e){createMsg.innerHTML='<span class="bad">'+esc(e.message)+'</span>'}}
async function code(id){try{const b=await api('/api/admin/tenants/'+id+'/installation-codes',{method:'POST',body:JSON.stringify({expires_hours:24})});installCode.textContent=b.installation_code;installMeta.textContent=b.customer_code+' — صالح حتى '+new Date(b.expires_at).toLocaleString()}catch(e){alert(e.message)}}
async function revoke(id){if(!confirm('إلغاء ربط الجهاز؟'))return;try{await api('/api/admin/edge-devices/'+encodeURIComponent(id)+'/revoke',{method:'POST'});await refreshAll()}catch(e){alert(e.message)}}
async function refreshAll(){try{const [cs,ds]=await Promise.all([api('/api/admin/tenants'),api('/api/admin/edge-devices')]);customers.innerHTML=cs.customers.map(x=>'<tr><td>'+esc(x.code)+'</td><td>'+esc(x.name)+'</td><td>'+esc(x.edge_devices)+'</td><td><span class="pill">'+esc(x.status)+'</span></td><td><button onclick="code('+x.id+')">Installation Code</button></td></tr>').join('');devices.innerHTML=ds.devices.map(x=>'<tr><td>'+esc(x.device_name)+'<div class="muted">'+esc(x.id)+'</div></td><td>'+esc(x.tenant_id)+'</td><td>'+esc(x.app_version||'—')+'</td><td>'+esc(x.last_seen_at?new Date(x.last_seen_at).toLocaleString():'—')+'</td><td>'+esc(x.status)+'</td><td>'+(x.status==='ACTIVE'?'<button class="danger" onclick="revoke(\''+esc(x.id)+'\')">Revoke</button>':'')+'</td></tr>').join('')}catch(e){if(String(e.message).includes('401')){sessionStorage.removeItem('pz_platform_token');location.reload()}else alert(e.message)}}
if(token){showApp();refreshAll()}
</script></body></html>"""

CUSTOMER_PORTAL_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayZone Manager</title><style>
:root{font-family:Segoe UI,Tahoma,Arial,sans-serif;color-scheme:dark;background:#07111f;color:#eef6ff}*{box-sizing:border-box}body{margin:0}
.wrap{max-width:1050px;margin:auto;padding:14px}.card{background:#0d1b2c;border:1px solid #1c3550;border-radius:16px;padding:15px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.stat{font-size:26px;font-weight:800}.muted{color:#91a4ba;font-size:13px}
input,button{width:100%;padding:11px;border-radius:10px;border:1px solid #294863;background:#091725;color:#fff;margin:5px 0}button{background:#1473e6;border:0;font-weight:700}
.station,.session{border-bottom:1px solid #1a3149;padding:9px 0}.station:last-child,.session:last-child{border:0}.hidden{display:none}.online{color:#63e6a6}.offline{color:#ff8c8c}
</style></head><body><div class="wrap"><h1>PlayZone Manager</h1>
<div id="login" class="card"><h2>دخول العميل</h2><input id="code" placeholder="Customer Code مثال PZM-0001"><input id="u" placeholder="Username"><input id="p" type="password" placeholder="Password"><button onclick="login()">دخول</button><div id="msg"></div></div>
<div id="app" class="hidden"><div class="card"><h2 id="customer">—</h2><div id="branch" class="muted"></div></div>
<div class="grid"><div class="card"><div class="muted">إجمالي المبيعات</div><div id="sales" class="stat">0</div></div><div class="card"><div class="muted">الفواتير</div><div id="invoices" class="stat">0</div></div><div class="card"><div class="muted">Multi 3</div><div id="m3" class="stat">0h</div></div><div class="card"><div class="muted">Multi 4</div><div id="m4" class="stat">0h</div></div></div>
<div class="grid"><div class="card"><h3>الجلسات النشطة</h3><div id="sessions"></div></div><div class="card"><h3>الأجهزة / الطاقة</h3><div id="stations"></div></div></div>
<div class="card"><h3>Edge</h3><div id="edges"></div></div></div></div>
<script>
let token=sessionStorage.getItem('pz_customer_token')||'';const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));const hrs=s=>(Number(s||0)/3600).toFixed(2)+'h';const money=p=>(Number(p||0)/100).toLocaleString(undefined,{maximumFractionDigits:2})+' EGP';
async function api(path,opt={}){const h={'Content-Type':'application/json',...(opt.headers||{})};if(token)h.Authorization='Bearer '+token;const r=await fetch(path,{...opt,headers:h});let b={};try{b=await r.json()}catch{}if(!r.ok)throw new Error(b.detail||('HTTP '+r.status));return b}
async function login(){try{const b=await api('/api/auth/login',{method:'POST',body:JSON.stringify({customer_code:code.value,username:u.value,password:p.value})});token=b.token;sessionStorage.setItem('pz_customer_token',token);show();await refresh()}catch(e){msg.textContent=e.message}}
function show(){login.classList.add('hidden');app.classList.remove('hidden')}
async function refresh(){try{const b=await api('/api/customer/overview');customer.textContent=b.customer.name+' ('+b.customer.code+')';branch.textContent=b.branch?.name||'';sales.textContent=money(b.sales_summary.sales_piasters);invoices.textContent=b.sales_summary.invoice_count;m3.textContent=hrs(b.sales_summary.multi_3_seconds);m4.textContent=hrs(b.sales_summary.multi_4_seconds);sessions.innerHTML=b.active_sessions.length?b.active_sessions.map(x=>'<div class="session"><b>'+esc(x.station_code||x.station_id)+'</b> — '+esc(x.status)+'<div class="muted">'+esc(x.session_type||'')+' • '+esc(x.controller_count)+' دراعات • '+esc(x.started_at?new Date(x.started_at).toLocaleString():'')+'</div></div>').join(''):'<div class="muted">لا توجد جلسات نشطة</div>';stations.innerHTML=b.stations.length?b.stations.map(x=>'<div class="station"><b>'+esc(x.code||x.source_station_id)+'</b> <span class="'+(x.power_state==='ON'?'online':'muted')+'">'+esc(x.power_state||'—')+'</span></div>').join(''):'<div class="muted">لا توجد بيانات أجهزة بعد</div>';edges.innerHTML=b.edge_devices.map(x=>'<div><b>'+esc(x.device_name)+'</b> — '+esc(x.status)+'<div class="muted">Version '+esc(x.app_version||'—')+' • Last seen '+esc(x.last_seen_at?new Date(x.last_seen_at).toLocaleString():'—')+'</div></div>').join('')}catch(e){if(String(e.message).includes('401')){sessionStorage.removeItem('pz_customer_token');location.reload()}}}
if(token){show();refresh();setInterval(refresh,5000)}
</script></body></html>"""
