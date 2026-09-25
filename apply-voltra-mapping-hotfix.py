from pathlib import Path

DASH = Path("/app/playzone/backend/voltra_local/dashboard.py")
s = DASH.read_text(encoding="utf-8")

old = "let data={strips:[],ps4_devices:[],mappings:{},summary:{}};let renameMac=null;let replaceOldMac=null;"
new = "let data={strips:[],ps4_devices:[],mappings:{},summary:{}};let renameMac=null;let replaceOldMac=null;const mappingDrafts={};const mappingDirty=new Set();const mappingSaving=new Set();"
if old in s:
    s = s.replace(old, new, 1)
elif "const mappingDrafts={}" not in s:
    raise RuntimeError("Could not patch Voltra mapping state")

css_old = ".mapping:last-child{border-bottom:0}"
css_new = ".mapping:last-child{border-bottom:0}.mapping.mapping-dirty{background:#102943;border:1px solid #2d78b5;border-radius:12px;margin:4px 0}.mapping-note{color:#ffd06a;font-size:12px;margin-top:5px}.mapping-actions{display:flex;gap:7px;align-items:center;flex-wrap:wrap}"
if css_old in s and ".mapping.mapping-dirty" not in s:
    s = s.replace(css_old, css_new, 1)

old_mapping = """function renderMappings(){const root=document.getElementById('mappings');if(!data.ps4_devices.length){root.innerHTML='<div class="empty">أجهزة PlayZone ستظهر هنا تلقائيًا بعد المزامنة.</div>';return}root.innerHTML=data.ps4_devices.map(p=>{const m=data.mappings[p.id];const strip=m?stripByMac(m.mac):null;return `<div class="mapping"><div><b>${esc(p.name)}</b><div class="muted">${esc(p.id)}</div>${m&&strip?.state==='disabled'?'<span class="status disabled">المشترك معطل — الربط محفوظ</span>':''}</div><select class="field" id="map-${encodeURIComponent(p.id)}">${availableOptions(p.id)}</select><button class="btn blue" onclick="saveMapping('${encodeURIComponent(p.id)}')">حفظ الربط</button></div>`}).join('');for(const p of data.ps4_devices){const m=data.mappings[p.id],el=document.getElementById(`map-${encodeURIComponent(p.id)}`);if(el&&m){const opt=[...el.options].find(o=>o.value===`${m.mac}:${m.outlet}`);if(opt)el.value=opt.value;else{const x=document.createElement('option');x.value=`${m.mac}:${m.outlet}`;x.textContent=`الربط الحالي: ${stripByMac(m.mac)?.name||m.mac} / Outlet ${m.outlet}`;el.prepend(x);el.value=x.value}}}}"""

new_mapping = """function savedMappingValue(id){const m=(data.mappings||{})[id];return m?`${m.mac}:${m.outlet}`:''}
function mappingEditorLocked(){const a=document.activeElement;return mappingDirty.size>0||!!(a&&a.matches&&a.matches('#mappings select'))}
function stageMapping(encoded){const id=decodeURIComponent(encoded),el=document.getElementById(`map-${encodeURIComponent(id)}`);if(!el)return;mappingDrafts[String(id)]=el.value;mappingDirty.add(String(id));const row=el.closest('.mapping');if(row){row.classList.add('mapping-dirty');const info=row.children[0];if(info&&!info.querySelector('.mapping-note')){const note=document.createElement('div');note.className='mapping-note';note.textContent='● تغيير غير محفوظ';info.appendChild(note)}const actions=row.querySelector('.mapping-actions'),b=row.querySelector('.mapping-save');if(b){b.textContent='حفظ التغيير';b.classList.remove('blue');b.classList.add('green')}if(actions&&!actions.querySelector('.mapping-cancel')){const c=document.createElement('button');c.type='button';c.className='btn ghost mapping-cancel';c.textContent='إلغاء';c.onclick=()=>cancelMapping(encodeURIComponent(id));actions.appendChild(c)}}}
function cancelMapping(encoded){const id=String(decodeURIComponent(encoded));delete mappingDrafts[id];mappingDirty.delete(id);renderMappings(true)}
function renderMappings(force=false){const root=document.getElementById('mappings');if(!force&&root.children.length&&mappingEditorLocked())return;if(!data.ps4_devices.length){root.innerHTML='<div class="empty">أجهزة PlayZone ستظهر هنا تلقائيًا بعد المزامنة.</div>';return}root.innerHTML=data.ps4_devices.map(p=>{const id=String(p.id),m=data.mappings[p.id],strip=m?stripByMac(m.mac):null,dirty=mappingDirty.has(id);return `<div class="mapping ${dirty?'mapping-dirty':''}" data-map-id="${esc(id)}"><div><b>${esc(p.name)}</b><div class="muted">${esc(p.id)}</div>${m&&strip?.state==='disabled'?'<span class="status disabled">المشترك معطل — الربط محفوظ</span>':''}${dirty?'<div class="mapping-note">● تغيير غير محفوظ</div>':''}</div><select class="field" id="map-${encodeURIComponent(p.id)}" onchange="stageMapping('${encodeURIComponent(p.id)}')">${availableOptions(p.id)}</select><div class="mapping-actions"><button class="btn ${dirty?'green':'blue'} mapping-save" onclick="saveMapping('${encodeURIComponent(p.id)}')">${dirty?'حفظ التغيير':'حفظ الربط'}</button>${dirty?`<button class="btn ghost" onclick="cancelMapping('${encodeURIComponent(p.id)}')">إلغاء</button>`:''}</div></div>`}).join('');for(const p of data.ps4_devices){const id=String(p.id),m=data.mappings[p.id],el=document.getElementById(`map-${encodeURIComponent(p.id)}`);if(!el)continue;let value=mappingDirty.has(id)?(mappingDrafts[id]??''):savedMappingValue(p.id);if(value){let opt=[...el.options].find(o=>o.value===value);if(!opt&&m&&value===`${m.mac}:${m.outlet}`){opt=document.createElement('option');opt.value=value;opt.textContent=`الربط الحالي: ${stripByMac(m.mac)?.name||m.mac} / Outlet ${m.outlet}`;el.prepend(opt)}if(opt)el.value=value}else el.value=''}}"""

if old_mapping in s:
    s = s.replace(old_mapping, new_mapping, 1)
elif "function mappingEditorLocked()" not in s:
    raise RuntimeError("Could not patch Voltra mapping editor")

old_save = """async function saveMapping(encoded){const id=decodeURIComponent(encoded),el=document.getElementById(`map-${encodeURIComponent(id)}`),v=el.value;try{if(!v)await api(`/voltra/api/ps4/${encodeURIComponent(id)}/power-mapping`,{method:'DELETE'});else{const [mac,outlet]=v.split(':');await api(`/voltra/api/ps4/${encodeURIComponent(id)}/power-mapping`,{method:'PUT',body:JSON.stringify({mac,outlet:Number(outlet)})})}await refresh();toast('تم حفظ الربط')}catch(e){toast(e.message,true)}}"""

new_save = """async function saveMapping(encoded){const id=String(decodeURIComponent(encoded)),el=document.getElementById(`map-${encodeURIComponent(id)}`);if(!el||mappingSaving.has(id))return;const v=el.value,row=el.closest('.mapping'),btn=row?.querySelector('.mapping-save');mappingSaving.add(id);el.disabled=true;if(btn){btn.disabled=true;btn.textContent='جاري الحفظ...'}try{if(!v)await api(`/voltra/api/ps4/${encodeURIComponent(id)}/power-mapping`,{method:'DELETE'});else{const cut=v.lastIndexOf(':'),mac=v.slice(0,cut),outlet=v.slice(cut+1);if(cut<1||!outlet)throw new Error('اختيار الربط غير صالح');await api(`/voltra/api/ps4/${encodeURIComponent(id)}/power-mapping`,{method:'PUT',body:JSON.stringify({mac,outlet:Number(outlet)})})}delete mappingDrafts[id];mappingDirty.delete(id);toast('تم حفظ الربط');await refresh()}catch(e){el.disabled=false;if(btn){btn.disabled=false;btn.textContent='حفظ التغيير'}toast(e.message,true)}finally{mappingSaving.delete(id)}}"""

if old_save in s:
    s = s.replace(old_save, new_save, 1)
elif "mappingSaving.has(id)" not in s:
    raise RuntimeError("Could not patch Voltra mapping save")

DASH.write_text(s, encoding="utf-8")
