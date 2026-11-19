(() => {
  'use strict';
  const panel = document.getElementById('gl-flow');
  if (!panel) return;
  const root = panel.closest('[data-activity-url]');
  const section = panel.querySelector('[data-journey]');
  const stage = section.querySelector('[data-journey-stage]');
  const picker = section.querySelector('select');
  const replay = section.querySelector('[data-replay]');
  const summary = section.querySelector('[data-journey-summary]');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const clock = new Intl.DateTimeFormat('fa-IR-u-nu-latn', {timeZone:'Asia/Tehran', hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
  let records = [];
  let selected, frame = 0, visible = false, pending = false, pinned = false;
  const sources = [62, 180, 298];
  const entryY = 34;
  const junction = 'M180 119 C180 136 180 141 180 156';
  const handoff = 'M180 169 C180 200 105 177 105 221';
  const booking = 'M126 234 C166 232 219 230 248 230';
  const direct = 'M193 165 C226 180 258 192 258 216';
  const flowerColors = {نرگس:'#efda90', بنفشه:'#bea7f7', یاسمن:'#f5e3cf', خورشیدی:'#efb477', لاله:'#fb9fae', کاملیا:'#f3aecd', گندم:'#e7ce8c'};

  function tube(d, active) {
    return '<g class="journey-tube'+(active?' is-lit':'')+'"><path class="outer" d="'+d+'"/><path class="inner" d="'+d+'"/></g>';
  }
  function bloom(color) {
    const petals = Array.from({length:8}, (_,i) =>
      '<g transform="rotate('+i*45+')"><path d="M0 -2 C-10 -10 -8 -24 0 -29 C8 -25 10 -10 0 -2Z" fill="url(#gl-petal)" stroke="'+color+'" stroke-width=".8"/><path d="M0 -5 Q-3 -15 0 -24" fill="none" stroke="#fff1db" opacity=".55"/></g>').join('');
    return '<g transform="rotate(-12)">'+petals+'<circle r="7" fill="#c68d52" stroke="#ffe8b3"/><circle cy="-1" r="3.1" fill="#ffeabc"/></g>';
  }
  function sourceTrack(x) {
    return 'M'+x+' 45 C'+x+' 99 180 82 180 119';
  }
  function textTag(x, y, key, cls) {
    return '<text x="'+x+'" y="'+y+'" class="'+cls+'" data-j-label="'+key+'" text-anchor="middle" direction="rtl"></text>';
  }
  function cancel() {
    cancelAnimationFrame(frame);
    frame = 0;
    stage.querySelector('[data-traveler]')?.setAttribute('visibility','hidden');
    for (const halo of stage.querySelectorAll('[data-flash]')) halo.setAttribute('opacity','0');
  }
  function canPlay() { return visible && !document.hidden && !section.hidden && !panel.classList.contains('flow-paused') && !reduced.matches; }
  function play() {
    cancel();
    if (!selected || !canPlay()) return;
    pending = false;
    const route = [...stage.querySelectorAll('[data-leg]')].map(path => ({
      path, length:path.getTotalLength(), halo:stage.querySelector('[data-flash="'+path.dataset.leg+'"]'),
    }));
    const dot = stage.querySelector('[data-traveler]');
    const start = performance.now();
    const stepMs = 1150;
    function advance(now) {
      if (!canPlay()) { cancel(); return; }
      const phase = (now-start)/stepMs;
      const i = Math.floor(phase);
      if (i >= route.length) { cancel(); return; }
      const {path,length,halo} = route[i];
      const part = phase-i;
      const end = Math.min(1,part/.80);
      const p = path.getPointAtLength(length*end);
      dot.setAttribute('transform','translate('+p.x+' '+p.y+')');
      dot.setAttribute('visibility',part<=.87?'visible':'hidden');
      for (const h of stage.querySelectorAll('[data-flash]')) h.setAttribute('opacity','0');
      if (halo && part>.69) halo.setAttribute('opacity',String(Math.sin(Math.PI*(part-.69)/.31)*.92));
      frame=requestAnimationFrame(advance);
    }
    frame=requestAnimationFrame(advance);
  }
  function render(animate) {
    cancel();
    pending = animate;
    if (!selected) {
      summary.textContent='امروز هنوز مسیری برای نمایش ثبت نشده است.';
      stage.replaceChildren();
      picker.closest('label').hidden=true;
      replay.disabled=true;
      return;
    }
    picker.closest('label').hidden=false;
    replay.disabled=reduced.matches || panel.classList.contains('flow-paused');
    const item = selected;
    const booked = Boolean(item.booked);
    const viaOwner = Boolean(item.owner && item.assigned && (!booked || Date.parse(item.assigned)<=Date.parse(item.booked)));
    const originList = [...new Set(records.map(r=>r.source))];
    const currentIndex = Math.min(originList.indexOf(item.source),2);
    const shown = originList.slice(0,3);
    shown[currentIndex]=item.source;
    const positions = shown.length===1 ? [180] : shown.length===2 ? [96,264] : sources;
    const flower = flowerColors[item.owner] || '#c6a9ef';
    const paths = shown.map((_,i)=>tube(sourceTrack(positions[i]),i===currentIndex)).join('');
    const sourceNodes = shown.map((_,i)=>{
      const x=positions[i];
      return '<g transform="translate('+x+' '+entryY+')" class="journey-source'+(i===currentIndex?' active':'')+'"><ellipse rx="12" ry="12"/><ellipse cx="-1.5" cy="-1.5" rx="4" ry="4"/></g>'+textTag(x,13,'s'+i,'source-label');
    }).join('');
    const legs = [['hub',sourceTrack(positions[currentIndex])+' C180 136 180 141 180 156']];
    if (viaOwner) legs.push(['owner',handoff]);
    if (booked) legs.push(['booking',viaOwner?booking:direct]);
    const endStatus = booked?'نوبت ثبت‌شده':item.cancelled?'نوبت لغوشده':'بدون نوبت';
    const owner = item.owner || 'در انتظار مسئول';
    summary.textContent = [item.source, owner, endStatus].join('  ·  ');
    if (item.owner && !item.assigned) summary.textContent+=' · زمان ارجاع ثبت نشده';
    else if (booked && item.owner && !viaOwner) summary.textContent+=' · ارجاع فعلی پس از ثبت نوبت';
    stage.innerHTML = '<svg viewBox="0 -6 360 308" role="img" aria-label="مسیر ثبت لید و وضعیت پیگیری" direction="ltr">'+
      '<defs><linearGradient id="gl-petal" x1="0" x2="1" y2=".85"><stop stop-color="#292034"/><stop offset=".42" stop-color="'+flower+'"/><stop offset="1" stop-color="#58475d"/></linearGradient>'+
      '<linearGradient id="gl-prism" x2=".7" y2="1"><stop stop-color="#f5e5ff"/><stop offset=".36" stop-color="#b198e4"/><stop offset="1" stop-color="#4b3e78"/></linearGradient>'+
      '<radialGradient id="gl-j-halo"><stop stop-color="#fff8e8"/><stop offset=".22" stop-color="#e6caff" stop-opacity=".9"/><stop offset="1" stop-color="#cfbaff" stop-opacity="0"/></radialGradient></defs>'+
      paths+tube(junction,true)+tube(handoff,viaOwner)+tube(viaOwner?booking:direct,booked)+
      legs.map(([id,d])=>'<path data-leg="'+id+'" d="'+d+'" fill="none" stroke="none"/>').join('')+sourceNodes+
      '<g transform="translate(180 153)"><ellipse rx="33" ry="23" fill="url(#gl-j-halo)" opacity=".13"/><path d="M0 -19 15 -4 10 11 0 19 -12 9 -16 -4Z" stroke="#ddceff" fill="url(#gl-prism)"/><path d="M0 -19 -5 -3 0 19 7 -4Z" fill="#d7bdf8" opacity=".64"/><path d="M-16 -4 -5 -3 7 -4 15 -4" fill="none" stroke="#f5e9ff"/></g>'+
      textTag(237,155,'hub','node-label')+
      '<g transform="translate(105 232)" opacity="'+(item.owner?1:.32)+'">'+bloom(flower)+'</g>'+
      '<g transform="translate(260 230)" opacity="'+(booked?1:.44)+'"><ellipse rx="20" ry="23" fill="#1b302f" stroke="#739e9a"/><path d="M-9 0 -3 6 10 -8" fill="none" stroke="'+(booked?'#96eac9':'#748283')+'" stroke-width="2.7" stroke-linecap="round" visibility="'+(booked?'visible':'hidden')+'"/><path d="M-7 0 H7" stroke="#a5b9c9" visibility="'+(booked?'hidden':'visible')+'"/></g>'+
      textTag(105,284,'owner','node-label')+textTag(260,284,'booking','node-label')+
      '<g fill="url(#gl-j-halo)" pointer-events="none"><circle data-flash="hub" cx="180" cy="153" r="30" opacity="0"/><circle data-flash="owner" cx="105" cy="232" r="42" opacity="0"/><circle data-flash="booking" cx="260" cy="230" r="32" opacity="0"/></g>'+
      '<g data-traveler visibility="hidden"><circle r="9" fill="url(#gl-j-halo)"/><circle r="2.8" fill="#fffaf0"/></g></svg>';
    const labels={hub:'ثبت لید',owner,booking:endStatus};
    shown.forEach((name,i)=>{labels['s'+i]=name;});
    for (const el of stage.querySelectorAll('[data-j-label]')) {
      const value = labels[el.dataset.jLabel];
      el.textContent=value.length>16?value.slice(0,15)+'…':value;
    }
    if (animate && canPlay()) play();
  }
  function update(items) {
    const previous=selected;
    records = items || [];
    selected = pinned && previous ? records.find(r=>r.id===previous.id) : null;
    if (!selected) { pinned=false; selected=records[0]; }
    picker.replaceChildren(...records.map(item=>{
      const option=document.createElement('option');
      option.value=String(item.id);
      option.textContent=clock.format(new Date(item.updated))+' · '+item.source+' · '+(item.owner || 'در انتظار مسئول')+' · #'+item.id;
      option.selected=item===selected;
      return option;
    }));
    if (!previous || JSON.stringify(previous)!==JSON.stringify(selected)) render(true);
  }
  picker.addEventListener('change',()=>{
    selected=records.find(r=>String(r.id)===picker.value);
    pinned=selected!==records[0];
    render(true);
  });
  replay.addEventListener('click',play);
  function syncMode() {
    section.hidden=!['overview','leads'].includes(panel.dataset.flowView);
    replay.disabled=!selected || reduced.matches || panel.classList.contains('flow-paused');
    if (!canPlay()) cancel();
    else if (pending) play();
  }
  new MutationObserver(syncMode).observe(panel,{attributes:true,attributeFilter:['class','data-flow-view']});
  new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;syncMode();}).observe(section);
  reduced.addEventListener('change',syncMode);
  document.addEventListener('visibilitychange',syncMode);
  root.addEventListener('flowupdate',event=>{
    const next=event.detail?.journeys || [];
    if (JSON.stringify(next)!==JSON.stringify(records)) update(next);
  });
  update(JSON.parse(root.querySelector('#gl-activity-initial').textContent).flow.journeys);
})();
