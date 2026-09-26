from __future__ import annotations

ADMIN_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayZone Manager — Platform Admin</title>
<style>
:root{font-family:Inter,system-ui,"Segoe UI",Tahoma,sans-serif;color:#e8eef7;background:#0a1018}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#0a1018,#0d1724);min-height:100vh}
.wrap{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px}
h1{margin:0;font-size:25px}.muted{color:#8da1b8}.card{background:#111d2b;border:1px solid #23354a;border-radius:16px;padding:18px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.stat{background:#0d1723;border:1px solid #1f344a;border-radius:14px;padding:14px}
.big{font-size:25px;font-weight:700;margin-top:7px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input,button{border-radius:10px;border:1px solid #2b4159;padding:11px 12px;font:inherit}input{background:#0c1621;color:#fff;min-width:180px}
button{background:#1777d2;color:#fff;cursor:pointer;font-weight:600}button.secondary{background:#192b3d}.danger{background:#9b2f39}
table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px;border-bottom:1px solid #23354a;font-size:14px}
.badge{display:inline-block;padding:4px 9px;border-radius:999px;background:#153956;color:#8ed0ff;font-size:12px}.ok{background:#183c2c;color:#8ce2aa}.off{background:#3b2730;color:#ffb0bd}
#login{max-width:430px;margin:12vh auto}.hide{display:none}.code{direction:ltr;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:#09111a;padding:10px;border-radius:10px}
@media(max-width:760px){.grid{grid-template-columns:1fr}.wrap{padding:14px}.top{align-items:flex-start;flex-direction:column}table{display:block;overflow:auto}}
</style>
</head>
<body>
<div class="wrap">
<section id="login" class="card">
<h1>PlayZone Manager</h1><p class="muted">Platform Admin</p>
<div class="row"><input id="u" placeholder="Username"><input id="p" type="password" placeholder="Password"><button onclick="login()">دخول</button></div>
<p id="loginErr" class="muted"></p>
</section>
<section id="app" class="hide">
<div class="top"><div><h1>PlayZone Manager — Admin</h1><div class="muted">إدارة العملاء وأجهزة Edge</div></div><button class="secondary" onclick="logout()">خروج</button></div>
<div class="grid">
<div class="stat"><div class="muted">العملاء</div><div id="tenantCount" class="big">—</div></div>
<div class="stat"><div class="muted">أجهزة Edge</div><div id="edgeCount" class="big">—</div></div>
<div class="stat"><div class="muted">أجهزة تم الاتصال بها</div><div id="seenCount" class="big">—</div></div>
</div>
<div class="card"><h3>إضافة عميل</h3><div class="row">
<input id="name" placeholder="اسم العميل"><input id="owner" placeholder="Owner username"><input id="ownerPass" type="password" placeholder="Owner password (8+)">
<button onclick="createTenant()">إنشاء العميل</button></div><p id="createMsg" class="muted"></p></div>
<div class="card"><div class="row" style="justify-content:space-between"><h3>العملاء</h3><button class="secondary" onclick="refresh()">تحديث</button></div>
<table><thead><tr><th>الكود</th><th>العميل</th><th>الحالة</th><th>Edge</th><th>Installation Code</th></tr></thead><tbody id="tenants"></tbody></table></div>
<div class="card"><h3>أجهزة Edge</h3><table><thead><tr><th>Device ID</th><th>Tenant</th><th>الاسم</th><th>Version</th><th>Last seen</th><th>الحالة</th></tr></thead><tbody id="edges"></tbody></table></div>
<div id="codeBox" class="card hide"><h3>Installation Code</h3><div id="codeText" class="code"></div><p class="muted">الكود يستخدم مرة واحدة فقط.</p></div>
</section></div>
<script>
let token=sessionStorage.getItem('pz_admin_token')||'';
const api=async(path,opt={})=>{const h={'Content-Type':'application/json',...(opt.headers||{})};if(token)h.Authorization='Bearer '+token;const r=await fetch(path,{...opt,headers:h});let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.detail||j.error||('HTTP '+r.status));return j}
function showApp(){document.getElementById('login').classList.add('hide');document.getElementById('app').classList.remove('hide')}
async function login(){try{const j=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:u.value,password:p.value})});if(j.user.role!=='PLATFORM_ADMIN')throw new Error('الحساب ليس Platform Admin');token=j.token;sessionStorage.setItem('pz_admin_token',token);showApp();await refresh()}catch(e){loginErr.textContent=e.message}}
function logout(){sessionStorage.removeItem('pz_admin_token');location.reload()}
async function createTenant(){try{const j=await api('/api/admin/tenants',{method:'POST',body:JSON.stringify({name:name.value,owner_username:owner.value,owner_password:ownerPass.value})});createMsg.textContent='تم إنشاء '+j.customer.name+' — '+j.customer.code;name.value=owner.value=ownerPass.value='';await refresh()}catch(e){createMsg.textContent=e.message}}
async function installationCode(id){try{const j=await api('/api/admin/tenants/'+id+'/installation-codes',{method:'POST',body:JSON.stringify({expires_hours:24})});codeText.textContent=j.installation_code;codeBox.classList.remove('hide');codeBox.scrollIntoView({behavior:'smooth'})}catch(e){alert(e.message)}}
async function refresh(){try{const [t,e]=await Promise.all([api('/api/admin/tenants'),api('/api/admin/edge-devices')]);tenantCount.textContent=t.customers.length;edgeCount.textContent=e.devices.length;seenCount.textContent=e.devices.filter(x=>x.last_seen_at).length;tenants.innerHTML=t.customers.map(x=>'<tr><td><span class="badge">'+x.code+'</span></td><td>'+esc(x.name)+'</td><td><span class="badge '+(x.status==='ACTIVE'?'ok':'off')+'">'+x.status+'</span></td><td>'+x.edge_devices+'</td><td><button onclick="installationCode('+x.id+')">إصدار كود</button></td></tr>').join('');edges.innerHTML=e.devices.map(x=>'<tr><td class="code">'+esc(x.id)+'</td><td>'+x.tenant_id+'</td><td>'+esc(x.device_name)+'</td><td>'+esc(x.app_version||'—')+'</td><td>'+esc(x.last_seen_at||'—')+'</td><td><span class="badge '+(x.status==='ACTIVE'?'ok':'off')+'">'+x.status+'</span></td></tr>').join('')}catch(e){if(String(e.message).includes('401')||String(e.message).includes('authentication'))logout();else alert(e.message)}}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
if(token){showApp();refresh()}
</script></body></html>"""
