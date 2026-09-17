"""Install the call-center staff cartable as an integrated left sidebar.

The call-center dashboard already has a left appointment column. This module
reuses that column instead of creating floating rails/panels, so the cartable
never overlaps the lead workspace. It is injected only for call-center staff
through the existing role-scoped middleware.
"""

_DOCK_STYLE = r'''<style id="greenlife-call-center-dock-v2">
/* Retire all former floating chat/dock surfaces; the integrated sidebar owns them now. */
.cc-dock-rail,.cc-dock-panel,.cc-mini-chat{display:none!important}

@media (min-width:1100px){
  /* ---- Integrated left sidebar: no bleed, no overlap, no hidden panel peeking through. ---- */
  .cc-v5-stage.cc-side-v2-ready{
    grid-template-columns:minmax(0,1fr) 76px!important;
    gap:14px!important;align-items:start!important;isolation:isolate!important;
    transition:grid-template-columns .18s ease!important
  }
  .cc-v5-stage.cc-side-v2-ready.cc-side-v2-expanded{
    grid-template-columns:minmax(0,1fr) minmax(348px,370px)!important
  }
  .cc-v5-main{min-width:0!important;position:relative!important;z-index:1!important}
  .cc-v5-side.cc-side-v2{
    position:sticky!important;top:74px!important;min-width:0!important;width:100%!important;
    align-self:start!important;z-index:20!important;overflow:hidden!important;border-radius:18px!important;
    box-sizing:border-box!important
  }
  .cc-side-v2-shell{
    width:100%!important;max-width:100%!important;box-sizing:border-box!important;
    display:grid!important;grid-template-columns:76px!important;direction:ltr!important;
    border:1px solid #dde4ec!important;border-radius:18px!important;background:#fff!important;
    box-shadow:0 12px 30px rgba(35,47,67,.10)!important;overflow:hidden!important;
    contain:paint!important;transition:none!important
  }
  .cc-v5-stage.cc-side-v2-expanded .cc-side-v2-shell{
    grid-template-columns:76px minmax(0,1fr)!important
  }
  .cc-v5-stage:not(.cc-side-v2-expanded) .cc-side-v2-panel{display:none!important}
  .cc-side-v2-rail{
    width:76px!important;min-width:76px!important;max-width:76px!important;box-sizing:border-box!important;
    min-height:430px!important;padding:10px 8px!important;display:flex!important;flex-direction:column!important;
    align-items:center!important;gap:9px!important;background:linear-gradient(180deg,#fbfcfd,#f6f8fb)!important;
    border:0!important;border-right:1px solid #e7ecf2!important;direction:rtl!important;overflow:hidden!important
  }
  .cc-side-v2-main,.cc-side-v2-schedule,.cc-side-v2-fav,.cc-side-v2-add{
    width:58px!important;min-width:58px!important;max-width:58px!important;min-height:52px!important;
    box-sizing:border-box!important;border:1px solid #dde4ec!important;border-radius:13px!important;
    background:#fff!important;color:#344258!important;display:flex!important;flex-direction:column!important;
    align-items:center!important;justify-content:center!important;gap:3px!important;padding:5px!important;
    cursor:pointer!important;font-family:Tahoma,sans-serif!important;text-decoration:none!important;
    position:relative!important;box-shadow:none!important;line-height:1.35!important
  }
  .cc-side-v2-main{background:#edf8f2!important;border-color:#c7e2d5!important;color:#176d4c!important;font-weight:900!important}
  .cc-side-v2-schedule{margin-top:auto!important;background:#f5f0fb!important;border-color:#ddd1eb!important;color:#65448f!important;font-weight:900!important}
  .cc-side-v2-main:hover,.cc-side-v2-schedule:hover,.cc-side-v2-fav:hover,.cc-side-v2-add:hover{
    transform:none!important;box-shadow:0 5px 14px rgba(38,54,75,.09)!important;border-color:#cfd8e2!important
  }
  .cc-side-v2-main .ico,.cc-side-v2-schedule .ico{font-size:18px!important;line-height:1!important}
  .cc-side-v2-main .txt,.cc-side-v2-schedule .txt{font-size:9px!important;font-weight:900!important;line-height:1.3!important}
  .cc-side-v2-unread{
    position:absolute!important;top:-4px!important;right:-4px!important;min-width:20px!important;height:20px!important;padding:0 5px!important;
    border-radius:999px!important;background:#c6425e!important;color:#fff!important;border:2px solid #fff!important;
    display:grid!important;place-items:center!important;font:900 8px Tahoma!important
  }
  .cc-side-v2-favs{display:flex!important;flex-direction:column!important;align-items:center!important;gap:7px!important;width:100%!important;max-height:275px!important;overflow:auto!important;padding:2px 0!important}
  .cc-side-v2-fav{min-height:50px!important;overflow:hidden!important}
  .cc-side-v2-fav b{font-size:14px!important;color:#684793!important;line-height:1!important}
  .cc-side-v2-fav span{display:block!important;width:100%!important;font-size:8px!important;font-weight:900!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;text-align:center!important;color:#3e4e63!important}
  .cc-side-v2-add{min-height:44px!important;font-size:20px!important;font-weight:900!important;color:#7351a4!important;background:#faf8fc!important}
  .cc-side-v2-divider{width:36px!important;height:1px!important;background:#dde4eb!important;margin:2px 0!important}

  .cc-side-v2-panel{
    min-width:0!important;overflow:hidden!important;direction:rtl!important;background:#fff!important;
    opacity:1!important;box-sizing:border-box!important
  }
  .cc-side-v2-head{
    height:58px!important;padding:8px 10px!important;display:grid!important;
    grid-template-columns:minmax(0,1fr) 36px!important;gap:8px!important;align-items:center!important;
    border-bottom:1px solid #e7ecf2!important;background:#fbfcfe!important
  }
  .cc-side-v2-tabs{display:grid!important;grid-template-columns:1fr 1fr!important;gap:5px!important;background:#eef2f6!important;border-radius:11px!important;padding:3px!important}
  .cc-side-v2-tab{
    height:36px!important;min-height:36px!important;border:0!important;border-radius:8px!important;
    background:transparent!important;color:#55657a!important;box-shadow:none!important;padding:0 8px!important;
    font:900 10px Tahoma!important;cursor:pointer!important
  }
  .cc-side-v2-tab.is-active{background:#fff!important;color:#213249!important;box-shadow:0 2px 8px rgba(35,47,67,.10)!important}
  .cc-side-v2-collapse{
    width:36px!important;height:36px!important;min-height:36px!important;padding:0!important;border:1px solid #d9e1e9!important;
    border-radius:9px!important;background:#fff!important;color:#43546a!important;box-shadow:none!important;font:900 19px Tahoma!important;cursor:pointer!important
  }
  .cc-side-v2-tools{padding:10px 11px!important;border-bottom:1px solid #e9edf2!important;background:#fff!important}
  .cc-side-v2-tools-top{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:8px!important;margin-bottom:8px!important}
  .cc-side-v2-tools-title{font:900 10px Tahoma!important;color:#34445a!important}
  .cc-side-v2-star-current{
    min-height:32px!important;border:1px solid #d9cce8!important;background:#f7f2fb!important;color:#5e3e88!important;
    border-radius:9px!important;padding:6px 9px!important;box-shadow:none!important;cursor:pointer!important;font:900 9px Tahoma!important
  }
  .cc-side-v2-chips{display:flex!important;gap:5px!important;flex-wrap:wrap!important;min-height:26px!important}
  .cc-side-v2-chip{display:inline-flex!important;align-items:center!important;gap:4px!important;padding:5px 7px!important;border:1px solid #dfe5ec!important;border-radius:999px!important;background:#fafbfd!important;color:#3f4f64!important;font:900 9px Tahoma!important;cursor:pointer!important}
  .cc-side-v2-chip button{width:18px!important;height:18px!important;min-height:18px!important;padding:0!important;border:0!important;border-radius:50%!important;background:#e9edf2!important;color:#5c6878!important;box-shadow:none!important;cursor:pointer!important;font:900 11px Tahoma!important}
  .cc-side-v2-empty{color:#5e6d7f!important;font:800 9px Tahoma!important;padding:4px 1px!important}
  .cc-side-v2-body{min-width:0!important;max-height:calc(100vh - 145px)!important;overflow:auto!important;background:#fff!important}
  .cc-side-v2-view{display:none!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important}
  .cc-side-v2-view.is-active{display:block!important}
  .cc-side-v2-view>.cc-v5-section-head{display:none!important}
  .cc-side-v2-view.cc-v6-chat{background:#fff!important}
  .cc-side-v2-view .cc-v6-chat-feed{min-height:190px!important;max-height:315px!important;padding:10px 11px!important}
  .cc-side-v2-view .cc-v6-chat-item{padding:9px 0!important}
  .cc-side-v2-view .cc-v6-chat-copy strong{font-size:10px!important}
  .cc-side-v2-view .cc-v6-chat-copy p{font-size:9px!important;color:#46566b!important}
  .cc-side-v2-view .cc-v6-chat-copy small{font-size:8px!important;color:#657386!important}
  .cc-side-v2-view .cc-v6-chat-compose{padding:10px!important;border-top:1px solid #e9edf2!important}
  .cc-side-v2-view .cc-v6-chat-form{display:grid!important;grid-template-columns:1fr!important;gap:8px!important}
  .cc-side-v2-view .cc-v6-chat-form select,.cc-side-v2-view .cc-v6-chat-form textarea,.cc-side-v2-view .cc-v6-chat-form button{width:100%!important;font-size:11px!important}
  .cc-side-v2-view .cc-v6-chat-form select{height:40px!important}
  .cc-side-v2-view .cc-v6-chat-form textarea{min-height:70px!important;resize:vertical!important;padding:10px!important}
  .cc-side-v2-view .cc-v6-chat-form button{min-height:40px!important;background:#174f3d!important;color:#fff!important;border:0!important;border-radius:10px!important;font-weight:900!important}
  .cc-side-v2-view .cc-v5-schedule-note{margin:10px!important;font-size:9px!important}
  .cc-side-v2-view .cc-v5-slots{padding:0 8px 10px!important;max-height:520px!important;overflow:auto!important}
  .cc-side-v2-view .cc-v5-slot{grid-template-columns:48px 36px minmax(0,1fr) 14px!important;padding:8px 5px!important;gap:6px!important;min-height:44px!important}
  .cc-side-v2-view .cc-v5-slot-time{font-size:9px!important}
  .cc-side-v2-view .cc-v5-slot-person strong{font-size:10px!important}
  .cc-side-v2-view .cc-v5-slot-person small{font-size:9px!important;color:#69778a!important}
  .cc-side-v2-lower-single{grid-template-columns:1fr!important}

  /* ---- Whole page readability on wide operator monitors. ---- */
  .cc-v5{font-size:13px!important;color:#1b2b40!important}
  .cc-v5 p{font-size:12px!important;line-height:1.85!important;color:#4b5b70!important;font-weight:600!important}
  .cc-v5 small{font-size:11px!important;line-height:1.7!important;color:#56667a!important;font-weight:600!important}
  .cc-v5 .cc-v5-hero h1{font-size:26px!important;font-weight:900!important;color:#17253a!important}
  .cc-v5 .cc-v5-eyebrow{font-size:11px!important}
  .cc-v5 .cc-v5-motto strong{font-size:13px!important}
  .cc-v5 .cc-v6-flow-step strong{font-size:11px!important}
  .cc-v5 .cc-v6-flow-step small{font-size:9px!important}
  .cc-v5 .cc-v5-kpi-label{font-size:12px!important}
  .cc-v5 .cc-v5-kpi strong{font-size:33px!important}
  .cc-v5 .cc-v5-kpi small{font-size:10px!important;color:rgba(255,255,255,.94)!important}
  .cc-v5 .cc-v7-performance-head h2{font-size:15px!important}
  .cc-v5 .cc-v7-period{font-size:10px!important}
  .cc-v5 .cc-v7-metric span{font-size:10px!important;color:#46566b!important}
  .cc-v5 .cc-v7-metric strong{font-size:24px!important}
  .cc-v5 .cc-v7-metric small{font-size:9px!important;color:#627185!important}
  .cc-v5 .cc-v7-funnel-step span{font-size:9px!important;color:#536277!important}
  .cc-v5 .cc-v7-funnel-step b{font-size:17px!important}
  .cc-v5 .cc-v5-section-head h2,.cc-v5 .cc-v5-section-head h3{font-size:15px!important;font-weight:900!important;color:#1b2a3f!important}
  .cc-v5 .cc-v5-section-head p{font-size:10px!important;color:#59697c!important;font-weight:650!important}
  .cc-v5 .cc-v5-section-head a{font-size:10px!important;font-weight:900!important}
  .cc-v5 .cc-v5-search input,.cc-v5 .cc-v5-select{font-size:12px!important}
  .cc-v5 .cc-v5-quick button{font:900 10.5px Tahoma!important}
  .cc-v5 .cc-v5-chip{font-size:10.5px!important}
  .cc-v5 .cc-v5-group-label strong{font-size:11px!important}
  .cc-v5 .cc-v5-group-label small{font-size:9px!important}
  .cc-v5 .cc-v5-lead-new input,.cc-v5 .cc-v5-lead-new select{font:800 11.5px Tahoma!important}
  .cc-v5 .cc-v5-lead-new button{font:900 11px Tahoma!important}

  /* ---- Lead rows: stronger text hierarchy and a clean 2x2 action grid. ---- */
  .cc-v5 .cc-v5-patient{
    grid-template-columns:minmax(300px,1.55fr) minmax(120px,.72fr) 110px 128px 206px!important;
    gap:12px!important;padding:12px 14px!important;min-height:82px!important;border-color:#e5eaf0!important
  }
  .cc-v5 .cc-v5-person-copy strong{font-size:12.5px!important;font-weight:900!important;color:#18263a!important}
  .cc-v5 .cc-v5-person-meta{font-size:9.5px!important;color:#59687a!important;gap:5px!important;margin-top:5px!important}
  .cc-v5 .cc-v5-person-meta b{font-size:10px!important;color:#34445a!important}
  .cc-v5 .cc-v5-tag{font-size:8.5px!important;padding:4px 6px!important}
  .cc-v5 .cc-v5-service{font-size:11px!important;color:#33445a!important;font-weight:700!important}
  .cc-v5 .cc-v5-status{font-size:10px!important;padding:7px 9px!important;font-weight:900!important}
  .cc-v5 .cc-v5-follow{font-size:10px!important;color:#506075!important;font-weight:700!important}
  .cc-v5 .cc-v5-row-actions{
    width:206px!important;display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:6px!important;align-items:stretch!important;justify-self:end!important
  }
  .cc-v5 .cc-v5-row-actions a,.cc-v5 .cc-v5-row-actions button{
    width:100%!important;min-width:0!important;min-height:38px!important;height:38px!important;
    box-sizing:border-box!important;display:flex!important;align-items:center!important;justify-content:center!important;
    padding:0 8px!important;border-radius:10px!important;font:900 10.5px Tahoma!important;
    white-space:nowrap!important;text-align:center!important;box-shadow:none!important
  }
  .cc-v5 .cc-v5-call{background:#1e9f68!important;color:#fff!important;border:1px solid #1e9f68!important}
  .cc-v5 .cc-v5-open,.cc-v5 .cc-result-action{background:#f4effa!important;color:#62438b!important;border:1px solid #ded2eb!important}
  .cc-v5 .cc-whatsapp-action{background:#f0faf5!important;color:#19704e!important;border:1px solid #cce6d9!important}
  .cc-v5 .cc-contact-done{background:#143f33!important;color:#fff!important;border:1px solid #143f33!important}
  .cc-v5 .cc-v5-action{height:50px!important;font-size:12px!important;border-radius:12px!important}
}

@media (min-width:1100px) and (max-width:1320px){
  .cc-v5 .cc-v5-patient{grid-template-columns:minmax(255px,1.35fr) minmax(105px,.7fr) 100px 115px 190px!important;gap:9px!important}
  .cc-v5 .cc-v5-row-actions{width:190px!important}
  .cc-v5-stage.cc-side-v2-ready.cc-side-v2-expanded{grid-template-columns:minmax(0,1fr) 350px!important}
}

@media (max-width:1099px){
  .cc-side-v2-shell,.cc-side-v2-rail,.cc-side-v2-panel{display:none!important}
}
</style>'''


_DOCK_SCRIPT = r'''<script id="greenlife-call-center-dock-script-v2">
(function(){
  if(window.__greenlifeCallCenterDockInstalledV2)return;
  window.__greenlifeCallCenterDockInstalledV2=true;

  function boot(){
    if(window.innerWidth<1100)return;
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;

    var stage=document.querySelector('.cc-v5-stage');
    var side=document.querySelector('.cc-v5-side');
    var chat=document.querySelector('.cc-v6-chat');
    if(!stage||!side||!chat||side.querySelector('.cc-side-v2-shell'))return;

    var select=chat.querySelector('select[name="recipient"]');
    if(!select)return;
    var schedule=side.querySelector('.cc-v5-card');
    if(!schedule)return;

    /* Clean up anything left from the former floating version. */
    Array.prototype.slice.call(document.querySelectorAll('.cc-dock-rail,.cc-dock-panel')).forEach(function(el){
      if(el!==chat)el.remove();
    });
    chat.classList.remove('cc-dock-panel','is-expanded');

    var lower=chat.parentElement;
    if(lower)lower.classList.add('cc-side-v2-lower-single');

    stage.classList.add('cc-side-v2-ready');
    side.classList.add('cc-side-v2');

    var unreadNode=chat.querySelector('.cc-v5-count');
    var unread=unreadNode?(unreadNode.textContent||'').trim():'';

    var shell=document.createElement('div');
    shell.className='cc-side-v2-shell';
    var rail=document.createElement('div');
    rail.className='cc-side-v2-rail';
    rail.innerHTML='<button type="button" class="cc-side-v2-main" title="کارتابل"><span class="ico">✉</span><span class="txt">کارتابل</span>'+(unread?'<b class="cc-side-v2-unread">'+unread+'</b>':'')+'</button><div class="cc-side-v2-favs"></div><div class="cc-side-v2-divider"></div><button type="button" class="cc-side-v2-schedule" title="نوبت‌های امروز"><span class="ico">▣</span><span class="txt">نوبت</span></button>';

    var panel=document.createElement('div');
    panel.className='cc-side-v2-panel';
    panel.innerHTML='<div class="cc-side-v2-head"><div class="cc-side-v2-tabs"><button type="button" class="cc-side-v2-tab" data-view="messages">کارتابل</button><button type="button" class="cc-side-v2-tab" data-view="schedule">نوبت‌های امروز</button></div><button type="button" class="cc-side-v2-collapse" title="جمع کردن">‹</button></div><div class="cc-side-v2-tools"><div class="cc-side-v2-tools-top"><span class="cc-side-v2-tools-title">★ افراد پرکاربرد</span><button type="button" class="cc-side-v2-star-current">☆ افزودن فرد انتخاب‌شده</button></div><div class="cc-side-v2-chips"></div></div><div class="cc-side-v2-body"></div>';

    shell.appendChild(rail);shell.appendChild(panel);
    side.innerHTML='';side.appendChild(shell);

    var body=panel.querySelector('.cc-side-v2-body');
    schedule.classList.add('cc-side-v2-view','cc-side-v2-schedule-view');
    chat.classList.add('cc-side-v2-view','cc-side-v2-chat-view');
    body.appendChild(chat);body.appendChild(schedule);

    var tools=panel.querySelector('.cc-side-v2-tools');
    var chips=panel.querySelector('.cc-side-v2-chips');
    var starBtn=panel.querySelector('.cc-side-v2-star-current');
    var favsBox=rail.querySelector('.cc-side-v2-favs');
    var tabButtons=Array.prototype.slice.call(panel.querySelectorAll('.cc-side-v2-tab'));
    var favoriteKey='greenlife.callcenter.favoriteContacts.v1';
    var openKey='greenlife.callcenter.integratedSidebarOpen.v2';
    var viewKey='greenlife.callcenter.integratedSidebarView.v2';

    function allContacts(){
      return Array.prototype.slice.call(select.options).filter(function(o){return o.value;}).map(function(o){return {id:String(o.value),name:(o.textContent||'').trim()};});
    }
    function readFavs(){
      try{var value=JSON.parse(localStorage.getItem(favoriteKey)||'[]');return Array.isArray(value)?value.map(String):[];}catch(e){return [];}
    }
    function saveFavs(ids){try{localStorage.setItem(favoriteKey,JSON.stringify(ids.slice(0,6)));}catch(e){}}
    function contactById(id){
      var contacts=allContacts();
      for(var i=0;i<contacts.length;i++)if(contacts[i].id===String(id))return contacts[i];
      return null;
    }
    function shortName(name){
      var clean=String(name||'').split('·')[0].trim();
      var parts=clean.split(/\s+/);return parts.length>1?parts[0]:clean;
    }
    function initial(name){var s=shortName(name);return s?s.charAt(0):'؟';}
    function isExpanded(){return stage.classList.contains('cc-side-v2-expanded');}
    function setExpanded(open){
      stage.classList.toggle('cc-side-v2-expanded',!!open);
      try{localStorage.setItem(openKey,open?'1':'0');}catch(e){}
    }
    function showView(view,forceOpen){
      view=view==='schedule'?'schedule':'messages';
      chat.classList.toggle('is-active',view==='messages');
      schedule.classList.toggle('is-active',view==='schedule');
      tools.style.display=view==='messages'?'block':'none';
      tabButtons.forEach(function(btn){btn.classList.toggle('is-active',btn.dataset.view===view);});
      try{localStorage.setItem(viewKey,view);}catch(e){}
      if(forceOpen!==false)setExpanded(true);
    }
    function choose(id){
      select.value=String(id);
      select.dispatchEvent(new Event('change',{bubbles:true}));
      showView('messages',true);
      setTimeout(function(){var textarea=chat.querySelector('textarea[name="body"]');if(textarea)textarea.focus();},80);
    }
    function updateStarButton(){
      var id=String(select.value||'');
      starBtn.textContent=id&&readFavs().indexOf(id)>=0?'★ حذف از پرکاربردها':'☆ افزودن فرد انتخاب‌شده';
    }
    function renderFavs(){
      var raw=readFavs();
      var ids=raw.filter(function(id){return !!contactById(id);});
      if(ids.length!==raw.length)saveFavs(ids);
      favsBox.innerHTML='';chips.innerHTML='';

      if(!ids.length){
        var add=document.createElement('button');add.type='button';add.className='cc-side-v2-add';add.title='افزودن فرد پرکاربرد';add.textContent='＋';
        add.addEventListener('click',function(){showView('messages',true);select.focus();});favsBox.appendChild(add);
        chips.innerHTML='<span class="cc-side-v2-empty">یک همکار را انتخاب کنید و ستاره بزنید.</span>';
        updateStarButton();return;
      }

      ids.forEach(function(id){
        var c=contactById(id);if(!c)return;
        var fav=document.createElement('button');fav.type='button';fav.className='cc-side-v2-fav';fav.title=c.name;
        fav.innerHTML='<b>'+initial(c.name)+'</b><span>'+shortName(c.name)+'</span>';
        fav.addEventListener('click',function(){choose(id);});favsBox.appendChild(fav);

        var chip=document.createElement('span');chip.className='cc-side-v2-chip';
        chip.innerHTML='<span>'+c.name+'</span><button type="button" title="حذف">×</button>';
        chip.addEventListener('click',function(e){if(e.target.tagName!=='BUTTON')choose(id);});
        chip.querySelector('button').addEventListener('click',function(){saveFavs(readFavs().filter(function(x){return x!==id;}));renderFavs();});
        chips.appendChild(chip);
      });
      if(ids.length<6){
        var plus=document.createElement('button');plus.type='button';plus.className='cc-side-v2-add';plus.title='افزودن فرد دیگر';plus.textContent='＋';
        plus.addEventListener('click',function(){showView('messages',true);select.focus();});favsBox.appendChild(plus);
      }
      updateStarButton();
    }

    rail.querySelector('.cc-side-v2-main').addEventListener('click',function(){
      if(isExpanded()&&chat.classList.contains('is-active'))setExpanded(false);else showView('messages',true);
    });
    rail.querySelector('.cc-side-v2-schedule').addEventListener('click',function(){
      if(isExpanded()&&schedule.classList.contains('is-active'))setExpanded(false);else showView('schedule',true);
    });
    panel.querySelector('.cc-side-v2-collapse').addEventListener('click',function(){setExpanded(false);});
    tabButtons.forEach(function(btn){btn.addEventListener('click',function(){showView(btn.dataset.view,true);});});
    starBtn.addEventListener('click',function(){
      var id=String(select.value||'');if(!id){select.focus();return;}
      var ids=readFavs();var pos=ids.indexOf(id);if(pos>=0)ids.splice(pos,1);else ids.unshift(id);
      saveFavs(ids);renderFavs();
    });
    select.addEventListener('change',updateStarButton);

    renderFavs();
    var savedView='messages';var savedOpen=false;
    try{savedView=localStorage.getItem(viewKey)||'messages';savedOpen=localStorage.getItem(openKey)==='1';}catch(e){}
    showView(savedView,false);setExpanded(savedOpen);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>'''


def install_call_center_dock():
    """Extend the existing call-center-only response injection once per process."""
    from . import call_center_views

    if 'greenlife-call-center-dock-v2' in call_center_views._CALL_CENTER_STAFF_STYLE:
        return
    call_center_views._CALL_CENTER_STAFF_STYLE += _DOCK_STYLE
    call_center_views._CALL_TRACKING_SCRIPT += _DOCK_SCRIPT