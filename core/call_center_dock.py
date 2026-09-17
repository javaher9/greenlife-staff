"""Install a persistent, staff-only internal-message dock for call-center screens.

The existing call-center middleware already injects staff-only CSS/JS.  This
module extends those payloads during app startup, keeping the manager UI and
other roles untouched.
"""

_DOCK_STYLE = r'''<style id="greenlife-call-center-dock-v1">
@media (min-width:1100px){
  .cc-dock-rail{
    position:fixed;left:16px;bottom:18px;z-index:132;width:64px;
    display:flex;flex-direction:column;align-items:center;gap:8px;padding:9px 7px;
    border:1px solid #dfe5ec;border-radius:20px;background:rgba(255,255,255,.97);
    box-shadow:0 18px 45px rgba(31,45,68,.16);backdrop-filter:blur(12px);direction:rtl
  }
  .cc-dock-main{
    width:48px;height:48px;border:0;border-radius:15px;background:#7351a4;color:#fff;
    display:grid;place-items:center;cursor:pointer;font:900 10px Tahoma;line-height:1.25;
    box-shadow:0 8px 20px rgba(91,61,140,.22);position:relative
  }
  .cc-dock-main .cc-dock-unread{
    position:absolute;top:-6px;right:-6px;min-width:20px;height:20px;padding:0 5px;
    border-radius:999px;background:#c73b59;color:#fff;border:2px solid #fff;
    display:grid;place-items:center;font:900 8px Tahoma
  }
  .cc-dock-favs{display:flex;flex-direction:column;gap:7px;align-items:center;max-height:290px;overflow:auto;width:100%}
  .cc-dock-fav,.cc-dock-add{
    width:46px;min-height:46px;border:1px solid #e1e6ed;border-radius:14px;background:#f8fafc;
    color:#334157;display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:2px;padding:4px;cursor:pointer;font-family:Tahoma;overflow:hidden
  }
  .cc-dock-fav:hover,.cc-dock-add:hover{border-color:#d5c6e7;background:#f7f2fc}
  .cc-dock-fav b{font-size:12px;color:#684793;line-height:1}
  .cc-dock-fav span{display:block;width:100%;font-size:7px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center;color:#4e5c70}
  .cc-dock-add{font-size:19px;font-weight:900;color:#7351a4}
  .cc-dock-panel{
    position:fixed!important;left:90px!important;bottom:18px!important;z-index:131!important;
    width:min(410px,calc(100vw - 120px))!important;max-height:78vh!important;
    display:grid!important;grid-template-rows:auto auto minmax(150px,1fr) auto!important;
    border:1px solid #dfe5ec!important;border-radius:20px!important;background:#fff!important;
    box-shadow:0 24px 60px rgba(28,40,61,.20)!important;overflow:hidden!important;
    transform:translateX(-18px) scale(.98);opacity:0;pointer-events:none;
    transition:transform .18s ease,opacity .18s ease
  }
  .cc-dock-panel.is-expanded{transform:translateX(0) scale(1);opacity:1;pointer-events:auto}
  .cc-dock-panel .cc-v5-section-head{padding:13px 14px!important;background:linear-gradient(135deg,#fbf9fe,#f7fbf9)!important}
  .cc-dock-panel .cc-v5-section-head h3{font-size:13px!important}
  .cc-dock-minimize{
    margin-inline-start:auto;border:1px solid #dfe5ec;background:#fff;color:#566379;border-radius:9px;
    width:32px;height:32px;display:grid;place-items:center;cursor:pointer;font:900 15px Tahoma
  }
  .cc-dock-tools{padding:9px 11px;border-bottom:1px solid #edf0f4;background:#fff}
  .cc-dock-tools-top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}
  .cc-dock-tools-title{font:900 9px Tahoma;color:#425067}
  .cc-dock-star-current{border:1px solid #ded3eb;background:#f6f1fb;color:#65458f;border-radius:9px;padding:6px 8px;cursor:pointer;font:900 8px Tahoma}
  .cc-dock-fav-chips{display:flex;gap:5px;flex-wrap:wrap;min-height:28px}
  .cc-dock-chip{display:inline-flex;align-items:center;gap:5px;padding:5px 7px;border:1px solid #e1e6ed;border-radius:999px;background:#fafbfd;color:#46546b;font:900 8px Tahoma;cursor:pointer}
  .cc-dock-chip button{width:17px;height:17px;padding:0;border:0;border-radius:50%;background:#eceff4;color:#6a7482;cursor:pointer;font:900 10px Tahoma}
  .cc-dock-empty{color:#7f8b9b;font:800 8px Tahoma;padding:5px 1px}
  .cc-dock-panel .cc-v6-chat-feed{max-height:300px!important;min-height:150px!important}
  .cc-dock-panel .cc-v6-chat-compose{padding:10px!important}
  .cc-dock-panel .cc-v6-chat-form{grid-template-columns:135px minmax(0,1fr) 64px!important}
  .cc-dock-panel .cc-v6-chat-form select,.cc-dock-panel .cc-v6-chat-form textarea{font-size:10px!important}
  .cc-dock-source-cleared{grid-template-columns:1fr!important}
}
@media (max-width:1099px){.cc-dock-rail{display:none!important}.cc-dock-tools,.cc-dock-minimize{display:none!important}}
</style>'''


_DOCK_SCRIPT = r'''<script id="greenlife-call-center-dock-script-v1">
(function(){
  if(window.__greenlifeCallCenterDockInstalled)return;
  window.__greenlifeCallCenterDockInstalled=true;

  function boot(){
    if(window.innerWidth<1100)return;
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;
    var chat=document.querySelector('.cc-v6-chat');
    if(!chat||document.querySelector('.cc-dock-rail'))return;
    var select=chat.querySelector('select[name="recipient"]');
    if(!select)return;

    var originalParent=chat.parentElement;
    if(originalParent)originalParent.classList.add('cc-dock-source-cleared');
    document.body.appendChild(chat);
    chat.classList.add('cc-dock-panel');

    var head=chat.querySelector('.cc-v5-section-head');
    var minimize=document.createElement('button');
    minimize.type='button';minimize.className='cc-dock-minimize';minimize.title='مینیمال کردن';minimize.textContent='−';
    if(head)head.appendChild(minimize);

    var tools=document.createElement('div');
    tools.className='cc-dock-tools';
    tools.innerHTML='<div class="cc-dock-tools-top"><span class="cc-dock-tools-title">★ افراد پرکاربرد</span><button type="button" class="cc-dock-star-current">☆ افزودن فرد انتخاب‌شده</button></div><div class="cc-dock-fav-chips"></div>';
    var feed=chat.querySelector('.cc-v6-chat-feed');
    if(feed)chat.insertBefore(tools,feed);

    var rail=document.createElement('aside');
    rail.className='cc-dock-rail';
    rail.setAttribute('aria-label','کارتابل سریع');
    var unreadNode=chat.querySelector('.cc-v5-count');
    var unread=unreadNode?(unreadNode.textContent||'').trim():'';
    rail.innerHTML='<button type="button" class="cc-dock-main" title="باز کردن کارتابل"><span>کارتابل</span>'+(unread?'<b class="cc-dock-unread">'+unread+'</b>':'')+'</button><div class="cc-dock-favs"></div>';
    document.body.appendChild(rail);

    var key='greenlife.callcenter.favoriteContacts.v1';
    var openKey='greenlife.callcenter.dockOpen.v1';
    function allContacts(){
      return Array.prototype.slice.call(select.options).filter(function(o){return o.value;}).map(function(o){return {id:String(o.value),name:(o.textContent||'').trim()};});
    }
    function readFavs(){
      try{var value=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(value)?value.map(String):[];}catch(e){return [];}
    }
    function saveFavs(ids){try{localStorage.setItem(key,JSON.stringify(ids.slice(0,6)));}catch(e){}}
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
    function setOpen(open){
      chat.classList.toggle('is-expanded',!!open);
      try{localStorage.setItem(openKey,open?'1':'0');}catch(e){}
      if(open){setTimeout(function(){var t=chat.querySelector('textarea[name="body"]');if(t)t.focus();},120);}
    }
    function choose(id){
      select.value=String(id);select.dispatchEvent(new Event('change',{bubbles:true}));setOpen(true);
      var textarea=chat.querySelector('textarea[name="body"]');if(textarea)textarea.focus();
    }
    function render(){
      var ids=readFavs().filter(function(id){return !!contactById(id);});
      if(ids.length!==readFavs().length)saveFavs(ids);
      var railFavs=rail.querySelector('.cc-dock-favs');
      var chips=tools.querySelector('.cc-dock-fav-chips');
      railFavs.innerHTML='';chips.innerHTML='';
      if(!ids.length){
        var add=document.createElement('button');add.type='button';add.className='cc-dock-add';add.title='انتخاب فرد پرکاربرد';add.textContent='＋';add.addEventListener('click',function(){setOpen(true);select.focus();});railFavs.appendChild(add);
        chips.innerHTML='<span class="cc-dock-empty">از لیست گیرنده یک نفر را انتخاب کنید و ستاره بزنید.</span>';
        return;
      }
      ids.forEach(function(id){
        var c=contactById(id);if(!c)return;
        var fav=document.createElement('button');fav.type='button';fav.className='cc-dock-fav';fav.title=c.name;fav.innerHTML='<b>'+initial(c.name)+'</b><span>'+shortName(c.name)+'</span>';fav.addEventListener('click',function(){choose(id);});railFavs.appendChild(fav);
        var chip=document.createElement('span');chip.className='cc-dock-chip';chip.innerHTML='<span>'+c.name+'</span><button type="button" title="حذف از پرکاربردها">×</button>';
        chip.addEventListener('click',function(e){if(e.target.tagName==='BUTTON')return;choose(id);});
        chip.querySelector('button').addEventListener('click',function(){saveFavs(readFavs().filter(function(x){return x!==id;}));render();});chips.appendChild(chip);
      });
      if(ids.length<6){var plus=document.createElement('button');plus.type='button';plus.className='cc-dock-add';plus.title='افزودن فرد دیگر';plus.textContent='＋';plus.addEventListener('click',function(){setOpen(true);select.focus();});railFavs.appendChild(plus);}
    }

    rail.querySelector('.cc-dock-main').addEventListener('click',function(){setOpen(!chat.classList.contains('is-expanded'));});
    minimize.addEventListener('click',function(){setOpen(false);});
    tools.querySelector('.cc-dock-star-current').addEventListener('click',function(){
      var id=String(select.value||'');if(!id){select.focus();return;}
      var ids=readFavs();var pos=ids.indexOf(id);if(pos>=0){ids.splice(pos,1);}else{ids.unshift(id);}
      saveFavs(ids);render();
    });
    select.addEventListener('change',function(){
      var id=String(select.value||'');var active=id&&readFavs().indexOf(id)>=0;
      tools.querySelector('.cc-dock-star-current').textContent=active?'★ حذف از پرکاربردها':'☆ افزودن فرد انتخاب‌شده';
    });

    render();
    var shouldOpen=false;try{shouldOpen=localStorage.getItem(openKey)==='1';}catch(e){}
    setOpen(shouldOpen);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>'''


def install_call_center_dock():
    """Extend the existing call-center-only response injection once per process."""
    from . import call_center_views

    if 'greenlife-call-center-dock-v1' in call_center_views._CALL_CENTER_STAFF_STYLE:
        return
    call_center_views._CALL_CENTER_STAFF_STYLE += _DOCK_STYLE
    call_center_views._CALL_TRACKING_SCRIPT += _DOCK_SCRIPT
