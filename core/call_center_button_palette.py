"""Final light button palette and metadata contrast for call-center staff.

This pass is intentionally explicit: the recurring dark controls in the quick
filters, lead form, integrated cartable, chat composer, and completed-call action
are styled by their real classes instead of relying only on computed-color
heuristics. A small luminance fallback remains for dynamically added controls.
"""

_BUTTON_PALETTE_STYLE = r'''<style id="greenlife-call-center-button-palette-v3">
/* ===== Explicit palette: never let the recurring staff controls render black ===== */
body.gl-role-call-center .cc-v5 .cc-v5-quick button{
  background:#f4f7fb!important;color:#40536a!important;border:1px solid #d8e1ea!important;
  box-shadow:none!important;border-radius:999px!important;font-weight:900!important
}
body.gl-role-call-center .cc-v5 .cc-v5-quick button:nth-child(1){background:#eef5ff!important;color:#35669f!important;border-color:#cbdcf0!important}
body.gl-role-call-center .cc-v5 .cc-v5-quick button:nth-child(2){background:#f1eafb!important;color:#65458f!important;border-color:#d8cae8!important}
body.gl-role-call-center .cc-v5 .cc-v5-quick button:nth-child(3){background:#eaf8f1!important;color:#176b4b!important;border-color:#c4e1d1!important}
body.gl-role-call-center .cc-v5 .cc-v5-quick button:nth-child(4){background:#fff5df!important;color:#8b601d!important;border-color:#ecd9aa!important}
body.gl-role-call-center .cc-v5 .cc-v5-quick button:nth-child(5){background:#fff0f4!important;color:#a3425d!important;border-color:#edcbd5!important}
body.gl-role-call-center .cc-v5 .cc-v5-quick button.active{
  background:linear-gradient(135deg,#e8ddf6,#f5effb)!important;color:#57377f!important;
  border-color:#cdb8e2!important;box-shadow:0 5px 14px rgba(104,71,147,.08)!important
}

body.gl-role-call-center .cc-v5 .cc-v5-group-new button{
  background:linear-gradient(135deg,#edf4ff,#f7faff)!important;color:#35669f!important;
  border:1px solid #c7d9ee!important;box-shadow:0 5px 14px rgba(65,109,169,.07)!important
}
body.gl-role-call-center .cc-v5 .cc-v5-lead-new button{
  background:linear-gradient(135deg,#e5f7ee,#f6fcf9)!important;color:#176b4b!important;
  border:1px solid #b9ddca!important;box-shadow:0 5px 14px rgba(28,118,82,.08)!important
}

/* Row actions: green call, purple result, mint WhatsApp, soft teal completed-call. */
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-v5-call{
  background:linear-gradient(135deg,#dff5e9,#f3fbf7)!important;color:#116b49!important;
  border:1px solid #afd8c2!important;box-shadow:0 4px 12px rgba(28,118,82,.07)!important
}
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-v5-open,
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-result-action{
  background:linear-gradient(135deg,#efe7f9,#faf7fd)!important;color:#5f3d88!important;
  border:1px solid #d5c5e7!important;box-shadow:0 4px 12px rgba(104,71,147,.07)!important
}
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-whatsapp-action{
  background:linear-gradient(135deg,#e8f8ef,#f7fcf9)!important;color:#176b4b!important;
  border:1px solid #c2e0cf!important;box-shadow:0 4px 12px rgba(28,118,82,.06)!important
}
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-contact-done{
  background:linear-gradient(135deg,#e8f4f2,#f7fbfa)!important;color:#28675b!important;
  border:1px solid #bfdcd6!important;box-shadow:0 4px 12px rgba(40,103,91,.07)!important;
  opacity:1!important
}
body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-contact-done[disabled]{
  background:#f1f6f5!important;color:#55756e!important;border-color:#d3e2df!important;opacity:1!important
}

/* Integrated cartable: each function gets its own light semantic tone. */
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-main{
  background:linear-gradient(145deg,#eaf3ff,#f7faff)!important;color:#35669f!important;border-color:#c7d9ee!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-schedule{
  background:linear-gradient(145deg,#f1eafb,#faf7fd)!important;color:#65458f!important;border-color:#d8cae8!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-fav{
  background:#fff!important;color:#3e5067!important;border-color:#dce4ec!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-add{
  background:#fff5df!important;color:#8b601d!important;border-color:#ecd9aa!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-tab{
  background:#f5f7fa!important;color:#475b72!important;border:1px solid #dfe6ed!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-tab.is-active{
  background:linear-gradient(135deg,#edf4ff,#fafcff)!important;color:#315f96!important;border-color:#cbdcf0!important;
  box-shadow:0 3px 10px rgba(65,109,169,.08)!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-collapse{
  background:#fff0f4!important;color:#9e3f59!important;border-color:#edcbd5!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-side-v2-star-current{
  background:#fff5df!important;color:#8b601d!important;border-color:#ecd9aa!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-v6-chat-form select,
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-v6-chat-form textarea{
  background:#f8fafc!important;color:#25384f!important;border:1px solid #d9e2ea!important;
  box-shadow:none!important
}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-v6-chat-form textarea::placeholder{color:#68798c!important;opacity:1!important}
body.gl-role-call-center .cc-v5 .cc-side-v2 .cc-v6-chat-form button{
  background:linear-gradient(135deg,#e5f7ee,#f6fcf9)!important;color:#176b4b!important;
  border:1px solid #b9ddca!important;box-shadow:0 5px 14px rgba(28,118,82,.08)!important
}

/* ===== Lead metadata: remove the washed-out text circled in the screenshot ===== */
body.gl-role-call-center .cc-v5 .cc-v5-person-copy small,
body.gl-role-call-center .cc-v5 .cc-v5-person-copy p,
body.gl-role-call-center .cc-v5 .cc-v5-person-meta,
body.gl-role-call-center .cc-v5 .cc-v5-person-meta span,
body.gl-role-call-center .cc-v5 .cc-v5-person-meta small{
  color:#455970!important;font-weight:800!important;opacity:1!important
}
body.gl-role-call-center .cc-v5 .cc-v5-person-meta b,
body.gl-role-call-center .cc-v5 .cc-v5-person-meta strong{
  color:#243950!important;font-weight:900!important;opacity:1!important
}
body.gl-role-call-center .cc-v5 .cc-v5-tag{
  color:#4c3d6a!important;font-weight:900!important;opacity:1!important
}
body.gl-role-call-center .cc-v5 .cc-v5-service{
  color:#253b52!important;font-weight:850!important;opacity:1!important
}

/* Common button finish. */
body.gl-role-call-center .cc-v5 button,
body.gl-role-call-center .cc-v5 a.cc-v5-call,
body.gl-role-call-center .cc-v5 a.cc-v5-open,
body.gl-role-call-center .cc-v5 a.cc-whatsapp-action{
  text-shadow:none!important;transition:transform .14s ease,box-shadow .14s ease,border-color .14s ease!important
}
body.gl-role-call-center .cc-v5 button:hover,
body.gl-role-call-center .cc-v5 a.cc-v5-call:hover,
body.gl-role-call-center .cc-v5 a.cc-v5-open:hover,
body.gl-role-call-center .cc-v5 a.cc-whatsapp-action:hover{transform:translateY(-1px)!important}

/* Fallback for any dynamically introduced dark control not covered above. */
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v3.cc-tone-green{background:#e5f7ee!important;color:#176b4b!important;border:1px solid #b9ddca!important}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v3.cc-tone-blue{background:#ebf3ff!important;color:#35669f!important;border:1px solid #c7d9ee!important}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v3.cc-tone-purple{background:#f0e9fb!important;color:#65458f!important;border:1px solid #d6c8e7!important}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v3.cc-tone-amber{background:#fff4dd!important;color:#8b601d!important;border:1px solid #ead5a3!important}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v3.cc-tone-rose{background:#ffedf3!important;color:#a3425d!important;border:1px solid #ebc6d1!important}
</style>'''

_BUTTON_PALETTE_SCRIPT = r'''<script id="greenlife-call-center-button-palette-script-v3">
(function(){
  if(window.__greenlifeButtonPaletteV3)return;
  window.__greenlifeButtonPaletteV3=true;

  function parseColors(value){
    var out=[],re=/rgba?\(\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)(?:\s*[, /]\s*([\d.]+))?\s*\)/ig,m;
    while((m=re.exec(String(value||''))))out.push({r:+m[1],g:+m[2],b:+m[3],a:m[4]===undefined?1:+m[4]});
    return out;
  }
  function luma(c){return .2126*c.r+.7152*c.g+.0722*c.b;}
  function isDark(el){
    var cs=getComputedStyle(el),colors=parseColors(cs.backgroundColor).concat(parseColors(cs.backgroundImage)).filter(function(c){return c.a>=.45;});
    if(!colors.length)return false;
    var total=0;colors.forEach(function(c){total+=luma(c);});
    return total/colors.length<=125;
  }
  function toneFor(el,index){
    var t=(el.textContent||el.value||el.getAttribute('aria-label')||el.title||'').trim();
    if(/حذف|لغو|×|✕/.test(t))return 'rose';
    if(/پیگیری|امروز|بعدی/.test(t))return 'amber';
    if(/نوبت|نتیجه|تقویم/.test(t))return 'purple';
    if(/پیام|کارتابل|چت|داخلی/.test(t))return 'blue';
    if(/تماس|ثبت|افزودن|ساخت|ارسال|ذخیره|واتساپ|تایید/.test(t))return 'green';
    return ['blue','purple','green','amber'][index%4];
  }
  function paint(root){
    var scope=root&&root.querySelector?root:document;
    var selector='.cc-v5 button,.cc-v5 input[type="button"],.cc-v5 input[type="submit"],.cc-v5 a[class*="btn"],.cc-v5 a[class*="action"]';
    Array.prototype.slice.call(scope.querySelectorAll(selector)).forEach(function(el,index){
      if(el.classList.contains('cc-colorized-dark-v3')||!isDark(el))return;
      el.classList.add('cc-colorized-dark-v3','cc-tone-'+toneFor(el,index));
    });
  }
  function boot(){
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;
    paint(document);[100,350,900,1800].forEach(function(ms){setTimeout(function(){paint(document);},ms);});
    var target=document.querySelector('.cc-v5');if(!target)return;
    new MutationObserver(function(){requestAnimationFrame(function(){paint(target);});}).observe(target,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>'''


def install_call_center_button_palette():
    """Append the final explicit staff palette and metadata contrast pass."""
    from . import call_center_views

    if 'greenlife-call-center-button-palette-v3' not in call_center_views._CALL_CENTER_STAFF_STYLE:
        call_center_views._CALL_CENTER_STAFF_STYLE += _BUTTON_PALETTE_STYLE
    if 'greenlife-call-center-button-palette-script-v3' not in call_center_views._CALL_TRACKING_SCRIPT:
        call_center_views._CALL_TRACKING_SCRIPT += _BUTTON_PALETTE_SCRIPT
