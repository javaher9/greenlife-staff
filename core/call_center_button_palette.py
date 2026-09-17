"""Lighten every visually dark button on the call-center staff dashboard.

The previous pass only detected neutral black. Some controls were very dark green,
blue, or purple and still looked black. This version measures visual luminance,
including gradients, and recolors any genuinely dark control into the existing
pastel Green Life palette while preserving already-light controls.
"""

_BUTTON_PALETTE_STYLE = r'''<style id="greenlife-call-center-button-palette-v2">
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2{
  border-radius:11px!important;
  font-family:Tahoma,sans-serif!important;
  font-weight:900!important;
  text-shadow:none!important;
  transition:background .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2:hover{
  transform:translateY(-1px)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2.cc-tone-green{
  background:linear-gradient(135deg,#e5f7ee,#f6fcf9)!important;
  color:#176b4b!important;border:1px solid #b9ddca!important;
  box-shadow:0 5px 14px rgba(28,118,82,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2.cc-tone-blue{
  background:linear-gradient(135deg,#ebf3ff,#f8fbff)!important;
  color:#35669f!important;border:1px solid #c7d9ee!important;
  box-shadow:0 5px 14px rgba(65,109,169,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2.cc-tone-purple{
  background:linear-gradient(135deg,#f0e9fb,#faf8fd)!important;
  color:#65458f!important;border:1px solid #d6c8e7!important;
  box-shadow:0 5px 14px rgba(104,71,147,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2.cc-tone-amber{
  background:linear-gradient(135deg,#fff4dd,#fffaf1)!important;
  color:#8b601d!important;border:1px solid #ead5a3!important;
  box-shadow:0 5px 14px rgba(168,118,33,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2.cc-tone-rose{
  background:linear-gradient(135deg,#ffedf3,#fff8fa)!important;
  color:#a3425d!important;border:1px solid #ebc6d1!important;
  box-shadow:0 5px 14px rgba(189,79,107,.08)!important;
}
body.gl-role-call-center .cc-v5 .cc-colorized-dark-v2:focus-visible{
  outline:3px solid rgba(79,121,190,.16)!important;outline-offset:2px!important;
}
</style>'''

_BUTTON_PALETTE_SCRIPT = r'''<script id="greenlife-call-center-button-palette-script-v2">
(function(){
  if(window.__greenlifeButtonPaletteV2)return;
  window.__greenlifeButtonPaletteV2=true;

  function parseColors(value){
    var out=[];
    var re=/rgba?\(\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)(?:\s*[, /]\s*([\d.]+))?\s*\)/ig;
    var m;
    while((m=re.exec(String(value||'')))){
      out.push({r:+m[1],g:+m[2],b:+m[3],a:m[4]===undefined?1:+m[4]});
    }
    return out;
  }
  function luma(c){return .2126*c.r+.7152*c.g+.0722*c.b;}
  function visualLuma(el){
    var cs=getComputedStyle(el);
    var colors=parseColors(cs.backgroundColor).concat(parseColors(cs.backgroundImage));
    colors=colors.filter(function(c){return c.a>=.45;});
    if(!colors.length)return null;
    var total=0;
    colors.forEach(function(c){total+=luma(c);});
    return total/colors.length;
  }
  function isVisuallyDark(el){
    var lum=visualLuma(el);
    return lum!==null&&lum<=118;
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
    root=root||document;
    var scope=root.querySelector?root:document;
    var selector=[
      '.cc-v5 button',
      '.cc-v5 input[type="button"]',
      '.cc-v5 input[type="submit"]',
      '.cc-v5 a',
      '.cc-v5 [role="button"]'
    ].join(',');
    Array.prototype.slice.call(scope.querySelectorAll(selector)).forEach(function(el,index){
      if(el.classList.contains('cc-colorized-dark-v2'))return;
      if(!isVisuallyDark(el))return;
      el.classList.remove('cc-colorized-neutral');
      el.classList.remove('cc-tone-green','cc-tone-blue','cc-tone-purple','cc-tone-amber','cc-tone-rose');
      el.classList.add('cc-colorized-dark-v2','cc-tone-'+toneFor(el,index));
    });
  }
  function boot(){
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;
    paint(document);
    [80,250,700,1500].forEach(function(ms){setTimeout(function(){paint(document);},ms);});
    var target=document.querySelector('.cc-v5');
    if(!target)return;
    new MutationObserver(function(mutations){
      var needs=false;
      mutations.forEach(function(m){
        if((m.addedNodes&&m.addedNodes.length)||m.type==='attributes')needs=true;
      });
      if(needs)requestAnimationFrame(function(){paint(target);});
    }).observe(target,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>'''


def install_call_center_button_palette():
    """Append the dark-control palette to call-center staff responses."""
    from . import call_center_views

    if 'greenlife-call-center-button-palette-v2' not in call_center_views._CALL_CENTER_STAFF_STYLE:
        call_center_views._CALL_CENTER_STAFF_STYLE += _BUTTON_PALETTE_STYLE
    if 'greenlife-call-center-button-palette-script-v2' not in call_center_views._CALL_TRACKING_SCRIPT:
        call_center_views._CALL_TRACKING_SCRIPT += _BUTTON_PALETTE_SCRIPT
