"""Install the call-center staff cartable as an integrated left sidebar.

The call-center dashboard already has a left appointment column.  This module
reuses that column instead of creating floating rails/panels, so the cartable
never overlaps the lead workspace.  It is injected only for call-center staff
through the existing role-scoped middleware.
"""

_DOCK_STYLE = r'''<style id="greenlife-call-center-dock-v2">
/* Retire the old floating dock completely. */
.cc-dock-rail,.cc-dock-panel{display:none!important}

@media (min-width:1100px){
  .cc-v5-stage.cc-side-v2-ready{
    grid-template-columns:minmax(0,1fr) 72px!important;
    gap:14px!important;align-items:start!important;
    transition:grid-template-columns .18s ease
  }
  .cc-v5-stage.cc-side-v2-ready.cc-side-v2-expanded{
    grid-template-columns:minmax(0,1fr) minmax(330px,360px)!important
  }
  .cc-v5-side.cc-side-v2{
    position:sticky!important;top:74px!important;min-width:0!important;width:100%!important;
    align-self:start!important;z-index:10!important;overflow:visible!important
  }
  .cc-side-v2-shell{
    width:100%;display:grid;grid-template-columns:72px minmax(0,1fr);direction:ltr;
    border:1px solid #e0e6ed;border-radius:18px;background:#fff;
    box-shadow:0 12px 30px rgba(35,47,67,.08);overflow:hidden;
    transition:grid-template-columns .18s ease
  }
  .cc-v5-stage:not(.cc-side-v2-expanded) .cc-side-v2-shell{grid-template-columns:72px 0}
  .cc-side-v2-rail{
    width:72px;min-height:420px;padding:9px 7px;display:flex;flex-direction:column;align-items:center;
    gap:8px;background:linear-gradient(180deg,#fbfcfd,#f6f8fb);border-right:1px solid #e8ecf1;direction:rtl
  }
  .cc-side-v2-main,.cc-side-v2-schedule,.cc-side-v2-fav,.cc-side-v2-add{
    width:54px;min-height:52px;border:1px solid #dfe5ec;border-radius:14px;background:#fff;color:#344258;
    display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:5px;
    cursor:pointer;font-family:Tahoma,sans-serif;text-decoration:none!important;position:relative;box-shadow:none
  }
  .cc-side-v2-main{background:#eef8f3;border-color:#cfe5da;color:#1f7252;font-weight:900}
  .cc-side-v2-schedule{margin-top:auto;background:#f6f1fb;border-color:#dfd4ec;color:#684793;font-weight:900}
  .cc-side-v2-main:hover,.cc-side-v2-schedule:hover,.cc-side-v2-fav:hover,.cc-side-v2-add:hover{transform:translateY(-1px);box-shadow:0 6px 15px rgba(38,54,75,.09)}
  .cc-side-v2-main .ico,.cc-side-v2-schedule .ico{font-size:17px;line-height:1}
  .cc-side-v2-main .txt,.cc-side-v2-schedule .txt{font-size:8px;font-weight:900;line-height:1.3}
  .cc-side-v2-unread{
    position:absolute;top:-5px;right:-5px;min-width:19px;height:19px;padding:0 5px;border-radius:999px;
    background:#c6425e;color:#fff;border:2px solid #fff;display:grid;place-items:center;font:900 8px Tahoma
  }
  .cc-side-v2-favs{display:flex;flex-direction:column;align-items:center;gap:7px;width:100%;max-height:270px;overflow:auto;padding:2px 0}
  .cc-side-v2-fav{min-height:50px;overflow:hidden}
  .cc-side-v2-fav b{font-size:14px;color:#684793;line-height:1}
  .cc-side-v2-fav span{display:block;width:100%;font-size:7px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center;color:#4e5c70}
  .cc-side-v2-add{min-height:44px;font-size:20px;font-weight:900;color:#7351a4;background:#faf8fc}
  .cc-side-v2-divider{width:34px;height:1px;background:#e2e7ed;margin:2px 0}

  .cc-side-v2-panel{
    min-width:0;overflow:hidden;direction:rtl;background:#fff;opacity:1;transition:opacity .12s ease
  }
  .cc-v5-stage:not(.cc-side-v2-expanded) .cc-side-v2-panel{opacity:0;pointer-events:none}
  .cc-side-v2-head{
    height:54px;padding:8px 10px;display:grid;grid-template-columns:minmax(0,1fr) 34px;gap:8px;align-items:center;
    border-bottom:1px solid #e9edf2;background:#fbfcfe
  }
  .cc-side-v2-tabs{display:grid;grid-template-columns:1fr 1fr;gap:5px;background:#f0f3f7;border-radius:10px;padding:3px}
  .cc-side-v2-tab{height:32px;border:0;border-radius:8px;background:transparent;color:#667489;font:900 9px Tahoma;cursor:pointer}
  .cc-side-v2-tab.is-active{background:#fff;color:#26374d;box-shadow:0 2px 8px rgba(35,47,67,.09)}
  .cc-side-v2-collapse{width:34px;height:34px;border:1px solid #dfe5ec;border-radius:9px;background:#fff;color:#536277;font:900 18px Tahoma;cursor:pointer}
  .cc-side-v2-tools{padding:9px 10px;border-bottom:1px solid #edf0f4;background:#fff}
  .cc-side-v2-tools-top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}
  .cc-side-v2-tools-title{font:900 9px Tahoma;color:#45536a}
  .cc-side-v2-star-current{border:1px solid #ded3eb;background:#f7f3fb;color:#65458f;border-radius:9px;padding:6px 8px;cursor:pointer;font:900 8px Tahoma}
  .cc-side-v2-chips{display:flex;gap:5px;flex-wrap:wrap;min-height:25px}
  .cc-side-v2-chip{display:inline-flex;align-items:center;gap:4px;padding:5px 7px;border:1px solid #e1e6ed;border-radius:999px;background:#fafbfd;color:#46546b;font:900 8px Tahoma;cursor:pointer}
  .cc-side-v2-chip button{width:17px;height:17px;padding:0;border:0;border-radius:50%;background:#eceff4;color:#6a7482;cursor:pointer;font:900 10px Tahoma}
  .cc-side-v2-empty{color:#7b8798;font:800 8px Tahoma;padding:4px 1px}
  .cc-side-v2-body{min-width:0;max-height:calc(100vh - 145px);overflow:auto;background:#fff}
  .cc-side-v2-view{display:none!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important}
  .cc-side-v2-view.is-active{display:block!important}
  .cc-side-v2-view>.cc-v5-section-head{display:none!important}
  .cc-side-v2-view.cc-v6-chat{background:#fff!important}
  .cc-side-v2-view .cc-v6-chat-feed{min-height:180px!important;max-height:310px!important;padding:10px!important}
  .cc-side-v2-view .cc-v6-chat-compose{padding:10px!important;border-top:1px solid #edf0f4!important}
  .cc-side-v2-view .cc-v6-chat-form{display:grid!important;grid-template-columns:1fr!important;gap:7px!important}
  .cc-side-v2-view .cc-v6-chat-form select,.cc-side-v2-view .cc-v6-chat-form textarea,.cc-side-v2-view .cc-v6-chat-form button{width:100%!important;font-size:10px!important}
  .cc-side-v2-view .cc-v6-chat-form textarea{min-height:66px!important;resize:vertical}
  .cc-side-v2-view .cc-v6-chat-form button{min-height:38px!important}
  .cc-side-v2-view .cc-v5-schedule-note{margin:10px!important}
  .cc-side-v2-view .cc-v5-slots{padding:0 8px 10px!important;max-height:520px!important;overflow:auto!important}
  .cc-side-v2-view .cc-v5-slot{grid-template-columns:46px 34px minmax(0,1fr) 14px!important;padding:7px 5px!important;gap:5px!important}
  .cc-side-v2-view .cc-v5-slot-time{font-size:9px!important}
  .cc-side-v2-view .cc-v5-slot-person strong{font-size:9px!important}
  .cc-side-v2-view .cc-v5-slot-person small{font-size:8px!important}
  .cc-side-v2-lower-single{grid-template-columns:1fr!important}
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
