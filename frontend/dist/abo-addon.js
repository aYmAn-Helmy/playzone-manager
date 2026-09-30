(() => {
  const qs=(s,r=document)=>r.querySelector(s), qsa=(s,r=document)=>[...r.querySelectorAll(s)];
  const money=p=>(Number(p||0)/100).toLocaleString('ar-EG',{minimumFractionDigits:0,maximumFractionDigits:2})+' ج.م';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const drinkTime=value=>{if(!value)return '—';try{return new Intl.DateTimeFormat('ar-EG',{timeZone:'Africa/Cairo',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true}).format(new Date(value))}catch{return String(value)}};
  const apiBase=location.port==='5173'?'http://127.0.0.1:8000':'';
  let view=null,state=null,products=[],refreshTimer=null,lastMount=null;

  async function api(path,opt={}){
    const token=localStorage.getItem('playzone_token')||'';
    const r=await fetch(apiBase+path,{...opt,headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json',...(opt.headers||{})}});
    if(r.status===401)throw new Error('انتهت صلاحية الجلسة');
    if(!r.ok){let x={};try{x=await r.json()}catch{}throw new Error(typeof x.detail==='string'?x.detail:'تعذر تنفيذ العملية')}
    return r.status===204?null:r.json();
  }
  const toast=(msg,bad=false)=>{const t=qs('#abo-drink-toast',view||document);if(!t)return;t.textContent=msg;t.classList.toggle('bad',bad);t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3600)};

  function mountSidebar(){
    const side=qs('.sidebar'); if(side)side.classList.add('abo-auto-sidebar');
  }

  function makeView(){
    const el=document.createElement('section');
    el.id='abo-drinks-page'; el.className='content-section abo-drinks-native'; el.dir='rtl';
    el.innerHTML=`<div class="abo-drinks-shell">
      <div class="abo-drinks-head"><div><h2>☕ حسابات المشاريب</h2><p>المشاريب والأسعار مرتبطة بصفحة المنتجات. كل إضافة تحفظ وقتها تلقائيًا.</p></div><button id="abo-refresh-drinks" class="button ghost" type="button">تحديث</button></div>
      <div id="abo-drink-summary" class="abo-drink-summary"></div>
      <section class="abo-drink-create"><div><h2>فتح حساب عميل</h2><p>الحساب يفضل مفتوح وتقدر تضيف عليه طوال اليوم لحد التحصيل.</p></div><form id="abo-open-customer"><input id="abo-customer-name" maxlength="100" placeholder="اسم العميل" autocomplete="off" required><button>+ فتح الحساب</button></form></section>
      <div id="abo-product-warning" class="abo-product-warning"></div>
      <div class="abo-drink-section-title"><div><h2>الحسابات المفتوحة</h2><span id="abo-open-count"></span></div></div>
      <div id="abo-open-tabs" class="abo-open-tabs"></div>
      <div class="abo-drink-section-title"><div><h2>فواتير اليوم</h2><span>الحسابات التي تم تحصيلها اليوم</span></div></div>
      <div id="abo-paid-tabs" class="abo-paid-tabs"></div>
    </div><div id="abo-drink-toast" class="abo-drink-toast"></div><div id="abo-receipt-modal" class="abo-receipt-modal"></div>`;
    qs('#abo-refresh-drinks',el).onclick=()=>refresh();
    qs('#abo-open-customer',el).onsubmit=async e=>{e.preventDefault();let name=qs('#abo-customer-name',el).value.trim();if(!name)return;try{let r=await api('/api/drinks/tabs',{method:'POST',body:JSON.stringify({customer_name:name})});qs('#abo-customer-name',el).value='';toast(r.created?'تم فتح حساب العميل':'الحساب مفتوح بالفعل');await refresh();}catch(err){toast(err.message,true)}};
    return el;
  }

  async function mountDrinksIfNeeded(){
    mountSidebar();
    const mount=qs('#abo-drinks-mount');
    if(!mount){
      if(refreshTimer){clearInterval(refreshTimer);refreshTimer=null}
      view=null;lastMount=null;return;
    }
    if(mount!==lastMount || !qs('#abo-drinks-page',mount)){
      lastMount=mount;view=makeView();mount.replaceChildren(view);await refresh();
      clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(document.body.contains(view))refresh(true)},15000);
    }
  }

  async function refresh(silent=false){
    if(!view)return;
    try{
      const [drinkData,productData]=await Promise.all([api('/api/drinks/today'),api('/api/products')]);
      state=drinkData;products=(productData||[]).filter(x=>x.is_active!==false);render();
    }catch(e){if(!silent)toast(e.message,true)}
  }

  function render(){if(!state||!view)return;const s=state.summary||{};
    qs('#abo-drink-summary',view).innerHTML=`
      <div><span>عملاء مفتوحين</span><b>${s.open_customers||0}</b></div>
      <div><span>رصيد غير محصل</span><b>${money(s.open_balance_piasters)}</b></div>
      <div><span>تم تحصيله اليوم</span><b>${money(s.collected_today_piasters)}</b></div>
      <div><span>فواتير اليوم</span><b>${s.paid_customers_today||0}</b></div>`;
    const warning=qs('#abo-product-warning',view);
    if(!products.length){warning.classList.add('show');warning.innerHTML='<b>مفيش منتجات مفعّلة.</b> أضف المشاريب وأسعارها من صفحة <b>المنتجات</b> الأول.'}else{warning.classList.remove('show');warning.innerHTML=''}
    qs('#abo-open-count',view).textContent=`${(state.open_tabs||[]).length} حساب`;
    const open=qs('#abo-open-tabs',view);open.innerHTML=(state.open_tabs||[]).length?state.open_tabs.map(tabCard).join(''):'<div class="abo-empty">لا توجد حسابات مشاريب مفتوحة حاليًا.</div>';
    wireOpenCards();
    const paid=qs('#abo-paid-tabs',view);paid.innerHTML=(state.paid_tabs||[]).length?state.paid_tabs.map(paidRow).join(''):'<div class="abo-empty">لا توجد فواتير مشاريب محصلة اليوم.</div>';
    qsa('[data-receipt-id]',paid).forEach(b=>b.onclick=()=>{const t=state.paid_tabs.find(x=>String(x.id)===b.dataset.receiptId);if(t)showReceipt(t)});
  }

  function productOptions(){
    if(!products.length)return '<option value="">لا توجد منتجات مفعّلة</option>';
    return '<option value="">اختر المنتج</option>'+products.map(p=>`<option value="${p.id}">${esc(p.name)} — ${money(p.price_piasters)}</option>`).join('');
  }

  function itemHtml(i){
    return `<div class="abo-tab-item"><div class="abo-item-main"><b>${esc(i.drink_name)}</b><span>${i.quantity} × ${money(i.unit_price_piasters)}</span><span class="abo-item-time">🕒 ${drinkTime(i.added_at)}</span></div><div><strong>${money(i.line_total_piasters)}</strong><button data-remove-item="${i.id}" title="حذف">×</button></div></div>`;
  }

  function tabCard(t){const items=t.items||[];return `<article class="abo-tab-card" data-tab-id="${t.id}">
    <header><div><h3>${esc(t.customer_name)}</h3><span>مفتوح ${drinkTime(t.opened_at)}</span></div><strong>${money(t.total_piasters)}</strong></header>
    <div class="abo-tab-items">${items.length?items.map(itemHtml).join(''):'<div class="abo-no-items">لسه مفيش مشاريب على الحساب.</div>'}</div>
    <form class="abo-add-drink"><select class="drink-product" required ${products.length?'':'disabled'}>${productOptions()}</select><div class="abo-selected-price">السعر: <b>—</b></div><input class="drink-qty" type="number" min="1" max="100" value="1" required><button ${products.length?'':'disabled'}>+ إضافة</button></form>
    <div class="abo-tab-checkout"><select class="checkout-method"><option value="CASH">كاش</option><option value="INSTAPAY">InstaPay</option><option value="VISA">Visa</option></select><button class="checkout-btn" ${items.length?'':'disabled'}>تحصيل الفاتورة</button></div>
  </article>`}

  function wireOpenCards(){
    qsa('.abo-tab-card',view).forEach(card=>{
      const id=Number(card.dataset.tabId),productSelect=qs('.drink-product',card),priceBox=qs('.abo-selected-price b',card),addForm=qs('.abo-add-drink',card),addButton=qs('.abo-add-drink button',card);
      const updatePrice=()=>{const p=products.find(x=>String(x.id)===String(productSelect?.value||''));priceBox.textContent=p?money(p.price_piasters):'—'};
      productSelect?.addEventListener('change',updatePrice);updatePrice();
      addForm.onsubmit=async e=>{e.preventDefault();const productId=Number(productSelect.value),quantity=Number(qs('.drink-qty',card).value||1);if(!productId)return toast('اختار منتج من صفحة المنتجات',true);addButton.disabled=true;try{await api(`/api/drinks/tabs/${id}/items`,{method:'POST',body:JSON.stringify({product_id:productId,quantity})});productSelect.value='';qs('.drink-qty',card).value='1';updatePrice();toast('تمت إضافة المنتج لحساب العميل');await refresh()}catch(err){toast(err.message,true)}finally{addButton.disabled=false}};
      qsa('[data-remove-item]',card).forEach(b=>b.onclick=async()=>{if(!confirm('حذف المشروب ده من حساب العميل؟'))return;try{await api(`/api/drinks/tabs/${id}/items/${b.dataset.removeItem}`,{method:'DELETE'});await refresh()}catch(err){toast(err.message,true)}});
      qs('.checkout-btn',card).onclick=async()=>{if(!confirm(`تحصيل حساب ${qs('h3',card).textContent} وإغلاقه؟`))return;try{const r=await api(`/api/drinks/tabs/${id}/checkout`,{method:'POST',body:JSON.stringify({payment_method:qs('.checkout-method',card).value})});await refresh();showReceipt(r.tab)}catch(err){toast(err.message,true)}};
    });
  }

  function paidRow(t){return `<div class="abo-paid-row"><div><b>${esc(t.customer_name)}</b><span>${esc(t.invoice_number||'')}</span></div><div class="abo-paid-items">${(t.items||[]).map(x=>`${esc(x.drink_name)} × ${x.quantity} <small>${drinkTime(x.added_at)}</small>`).join(' • ')}</div><div><b>${money(t.total_piasters)}</b><span>${t.payment_method||''}</span></div><button data-receipt-id="${t.id}">الفاتورة</button></div>`}

  function showReceipt(t){
    const m=qs('#abo-receipt-modal',view);m.classList.add('show');
    m.innerHTML=`<div class="abo-receipt-box"><div id="abo-print-receipt" class="abo-print-receipt"><h2>abo_aYmAn</h2><p>فاتورة مشاريب</p><hr><div class="rline"><span>رقم الفاتورة</span><b>${esc(t.invoice_number||'—')}</b></div><div class="rline"><span>العميل</span><b>${esc(t.customer_name)}</b></div><div class="rline"><span>التاريخ</span><b>${esc(t.business_date)}</b></div><hr>${(t.items||[]).map(i=>`<div class="rline"><span>${esc(i.drink_name)} × ${i.quantity}<small class="abo-receipt-time">${drinkTime(i.added_at)}</small></span><b>${money(i.line_total_piasters)}</b></div>`).join('')}<hr><div class="rline total"><span>الإجمالي</span><b>${money(t.total_piasters)}</b></div><div class="rline"><span>الدفع</span><b>${t.payment_method||''}</b></div></div><div class="abo-receipt-actions"><button id="abo-print-btn">طباعة</button><button id="abo-close-receipt">إغلاق</button></div></div>`;
    qs('#abo-close-receipt',m).onclick=()=>m.classList.remove('show');qs('#abo-print-btn',m).onclick=()=>window.print();m.onclick=e=>{if(e.target===m)m.classList.remove('show')};
  }

  const observer=new MutationObserver(()=>mountDrinksIfNeeded());
  observer.observe(document.documentElement,{childList:true,subtree:true});
  mountDrinksIfNeeded();
})();

/* abo_aYmAn v0.33 — responsive mobile/tablet shell */
(() => {
  const tabletQuery=window.matchMedia('(max-width: 1100px)');
  const handsetQuery=window.matchMedia('(max-width: 768px)');
  let framePending=false;

  function closeDrawer(){ document.body?.classList.remove('abo-sidebar-open'); }
  function toggleDrawer(){ document.body?.classList.toggle('abo-sidebar-open'); }

  function ensureMobileChrome(){
    const topbar=document.querySelector('.topbar');
    const sidebar=document.querySelector('.sidebar');
    if(!topbar||!sidebar)return;

    let button=document.getElementById('abo-mobile-menu');
    if(!button){
      button=document.createElement('button');
      button.id='abo-mobile-menu';
      button.type='button';
      button.className='abo-mobile-menu icon-button';
      button.setAttribute('aria-label','فتح القائمة الرئيسية');
      button.setAttribute('aria-controls','abo-main-sidebar');
      button.innerHTML='<span aria-hidden="true">☰</span>';
      button.addEventListener('click',toggleDrawer);
      document.body.appendChild(button);
    }
    sidebar.id='abo-main-sidebar';

    let shade=document.getElementById('abo-mobile-sidebar-backdrop');
    if(!shade){
      shade=document.createElement('div');
      shade.id='abo-mobile-sidebar-backdrop';
      shade.setAttribute('aria-hidden','true');
      shade.addEventListener('click',closeDrawer);
      document.body.appendChild(shade);
    }
  }

  function annotateTables(){
    document.querySelectorAll('.table-scroll table, .content-section table').forEach(table=>{
      table.classList.add('abo-responsive-table');
      const heads=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim());
      if(!heads.length)return;
      table.querySelectorAll('tbody tr').forEach(row=>{
        [...row.children].forEach((cell,index)=>{
          if(cell.tagName==='TD'&&!cell.dataset.label)cell.dataset.label=heads[index]||'';
        });
      });
    });
  }

  function applyResponsiveState(){
    if(!document.body)return;
    document.body.classList.toggle('abo-mobile-layout',tabletQuery.matches);
    document.body.classList.toggle('abo-handset-layout',handsetQuery.matches);
    if(!tabletQuery.matches)closeDrawer();
    ensureMobileChrome();
    annotateTables();
  }

  function schedule(){
    if(framePending)return;
    framePending=true;
    requestAnimationFrame(()=>{framePending=false;applyResponsiveState()});
  }

  document.addEventListener('click',e=>{
    if(!tabletQuery.matches)return;
    const nav=e.target.closest('.sidebar .nav-item');
    if(nav)closeDrawer();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});
  tabletQuery.addEventListener?.('change',schedule);
  handsetQuery.addEventListener?.('change',schedule);
  window.addEventListener('orientationchange',schedule);
  window.addEventListener('resize',schedule,{passive:true});
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});else schedule();
})();
