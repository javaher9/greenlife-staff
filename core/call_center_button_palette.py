"""Colorize neutral-black buttons on the call-center staff dashboard.

The page already has semantic green/purple/blue controls. This small enhancer only
recolors controls whose computed background is genuinely neutral-dark, so existing
brand colors are left intact while inherited/global black buttons are removed.
"""

_BUTTON_PALETTE_STYLE = r'''<style id="greenlife-call-center-button-palette-v1">
body.gl-role-call-center .cc-v5 .cc-colorized-neutral{
  border-radius:11px!important;
  font-family:Tahoma,sans-serif!important;
  font-weight:900!important;
  transition:background .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease!important;
  text-shadow:none!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral:hover{
  transform:translateY(-1px)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral.cc-tone-green{
  background:linear-gradient(135deg,#e6f7ee,#f4fbf7)!important;
  color:#176b4b!important;border:1px solid #bddfcd!important;
  box-shadow:0 5px 13px rgba(28,118,82,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral.cc-tone-blue{
  background:linear-gradient(135deg,#edf4ff,#f7faff)!important;
  color:#35669f!important;border:1px solid #cbdcf0!important;
  box-shadow:0 5px 13px rgba(65,109,169,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral.cc-tone-purple{
  background:linear-gradient(135deg,#f1eafb,#faf7fd)!important;
  color:#65458f!important;border:1px solid #d8cae8!important;
  box-shadow:0 5px 13px rgba(104,71,147,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral.cc-tone-amber{
  background:linear-gradient(135deg,#fff5df,#fffaf0)!important;
  color:#92651f!important;border:1px solid #ecd9aa!important;
  box-shadow:0 5px 13px rgba(168,118,33,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral.cc-tone-rose{
  background:linear-gradient(135deg,#fff0f4,#fff7f9)!important;
  color:#a7445f!important;border:1px solid #edcbd5!important;
  box-shadow:0 5px 13px rgba(189,79,107,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-neutral:focus-visible{
  outline:3px solid rgba(79,121,190,.16)!important;outline-offset:2px!important;
}
</style>'''

_BUTTON_PALETTE_SCRIPT = r'''<script id="greenlife-call-center-button-palette-script-v1">
(function(){
  if(window.__greenlifeButtonPaletteV1)return;
  window.__greenlifeButtonPaletteV1=true;

  function rgb(value){
    var m=String(value||'').match(/rgba?\((\d+)[, ]+\s*(\d+)[, ]+\s*(\d+)(?:[, /]+\s*([\d.]+))?\)/i);
    if(!m)return null;
    return {r:+m[1],g:+m[2],b:+m[3],a:m[4]===undefined?1:+m[4]};
  }
  function isNeutralDark(el){
    var c=rgb(getComputedStyle(el).backgroundColor);
    if(!c||c.a<.55)return false;
    var max=Math.max(c.r,c.g,c.b),min=Math.min(c.r,c.g,c.b);
    return max<=92 && (max-min)<=28;
  }
  function toneFor(el,index){
    var t=(el.textContent||el.value||el.getAttribute('aria-label')||el.title||'').trim();
    if(/حذف|لغو|×|✕/.test(t))return 'rose';
    if(/پیگیری|امروز|بعدی/.test(t))return 'amber';
    if(/نوبت|نتیجه|تقویم/.test(t))return 'purple';
    if(/پیام|کارتابل|چت|داخلی/.test(t))return 'blue';
    if(/تماس|ثبت|افزودن|ساخت|ارسال|ذخیره|واتساپ/.test(t))return 'green';
    return ['blue','purple','green','amber'][index%4];
  }
  function paint(root){
    root=root||document;
    var scope=root.querySelector?root:document;
    var selector='.cc-v5 button,.cc-v5 input[type="button"],.cc-v5 input[type="submit"],.cc-v5 a[class*="action"],.cc-v5 a[class*="btn"],.cc-v5 a.cc-v5-open,.cc-v5 a.cc-v5-call';
    Array.prototype.slice.call(scope.querySelectorAll(selector)).forEach(function(el,index){
      if(el.classList.contains('cc-colorized-neutral'))return;
      if(!isNeutralDark(el))return;
      el.classList.add('cc-colorized-neutral','cc-tone-'+toneFor(el,index));
    });
  }
  function boot(){
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;
    paint(document);
    setTimeout(function(){paint(document);},120);
    setTimeout(function(){paint(document);},650);
    var target=document.querySelector('.cc-v5');
    if(!target)return;
    new MutationObserver(function(mutations){
      var needs=false;
      mutations.forEach(function(m){if(m.addedNodes&&m.addedNodes.length)needs=true;});
      if(needs)paint(target);
    }).observe(target,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>'''


def install_call_center_button_palette():
    """Append the neutral-black button palette to call-center staff responses."""
    from . import call_center_views

    if 'greenlife-call-center-button-palette-v1' not in call_center_views._CALL_CENTER_STAFF_STYLE:
        call_center_views._CALL_CENTER_STAFF_STYLE += _BUTTON_PALETTE_STYLE
    if 'greenlife-call-center-button-palette-script-v1' not in call_center_views._CALL_TRACKING_SCRIPT:
        call_center_views._CALL_TRACKING_SCRIPT += _BUTTON_PALETTE_SCRIPT
