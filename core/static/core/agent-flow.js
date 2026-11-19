(() => {
  'use strict';
  const format = new Intl.NumberFormat('fa-IR-u-nu-latn');
  // The two systems share a dashboard, but an account is never implicitly a lead.
  const stations = {
    me: ['گرین‌لایف ME', 'مسیر حساب مشترک، همگام‌سازی در اپ و درخواست ویزیت.'],
    account: ['ثبت‌نام با شماره', 'حساب‌های مشترک جدید امروز با ورود تأییدشده. شمارهٔ شخص روی نقشه نمایش داده نمی‌شود.'],
    sync: ['همگام‌سازی اپ', 'تعداد ذخیره‌های موفق حساب در اپ ME امروز. یک عضو می‌تواند چند بار ذخیره کند.'],
    request: ['درخواست ویزیت', 'درخواست‌های ویزیت ثبت‌شدهٔ امروز در مسیر مشترک اعضا و ME.'],
    booked: ['نوبت تأییدشده', 'از درخواست‌های ویزیت امروز، چند درخواست اکنون نوبت تأییدشده و متصل دارند.'],
    website: ['وب‌سایت', 'لیدهای امروز در گروه وب‌سایت.'],
    instagram: ['اینستاگرام', 'لیدهای امروز در گروه اینستاگرام. دریافت دایرکت به‌تنهایی شمارندهٔ لید را بالا نمی‌برد.'],
    school: ['مدارس', 'لیدهای امروز با ثبت‌نام مدرسهٔ مرتبط. هر پرونده فقط در یک شاخه شمرده می‌شود.'],
    other: ['سایر منابع', 'سایر پرونده‌های لید امروز، از جمله گروه‌های معرفی و کمپ.'],
    crm: ['لیدهای فشرده', 'کل پرونده‌های لید ثبت‌شدهٔ امروز از چهار مسیر ورودی.'],
    assigned: ['دارای مسئول', 'از لیدهای ثبت‌شدهٔ امروز، چند پرونده هم‌اکنون مسئول پیگیری دارد.'],
  };
  const layout = window.GreenLifeFlowLayout.layout;
  const vessels = window.GreenLifeFlowVessels;
  const tint = key => vessels.groups[vessels.groupFor(key)].color;
  const isHub = key => key === 'me' || key === 'crm';
  const bodyWidth = narrow => narrow ? 48 : 56;
  const hubRadius = narrow => narrow ? 28 : 34;
  const arabic = 'Noto Sans Arabic,Tahoma,Arial,sans-serif';
  function label(x,y,value,size,color,weight=500,reading=false) {
    const attribute=reading?' data-station-count=""':'';
    return '<text'+attribute+' direction="rtl" unicode-bidi="plaintext" x="'+x+'" y="'+y+'" text-anchor="middle" font-family="'+arabic+'" font-size="'+size+'" font-weight="'+weight+'" fill="'+color+'">'+value+'</text>';
  }
  const extras={
    diet:['پیگیری رژیم','درخواست‌های کمک و پیگیری رژیم ثبت‌شدهٔ امروز.'],
    device:['نوبت دستگاه','درخواست‌های نوبت دستگاه ثبت‌شدهٔ امروز.'],
    network:['شبکهٔ فروش','درخواست‌های عضویت در شبکهٔ فروش امروز.'],
    lead_new:['جدید','پرونده‌های امروز با وضعیت فعلی جدید.'],
    lead_contacted:['تماس گرفته شد','پرونده‌های امروز با وضعیت فعلی تماس گرفته شد.'],
    lead_appointment:['نوبت ثبت شد','پرونده‌های امروز با وضعیت فعلی نوبت ثبت شد.'],
    lead_visited:['مراجعه کرد','پرونده‌های امروز با وضعیت فعلی مراجعه کرد.'],
    lead_won:['فروش موفق','پرونده‌های امروز با وضعیت فعلی فروش موفق.'],
    lead_lost:['ناموفق','پرونده‌های امروز با وضعیت فعلی ناموفق.'],
  };
  const info=key=>stations[key] || extras[key];
  // The same upper-left light models every station, including the expanded rooms.
  function spaceBackdrop() {
    const materials = [
      { id:'me', ice:'#d3fff0', light:'#72eed7', middle:'#297f83', shade:'#153d51', dark:'#091825' },
      { id:'crm', ice:'#f4e6ff', light:'#c1a4ff', middle:'#8263b4', shade:'#403257', dark:'#17152c' },
    ].map(({id, ice, light, middle, shade, dark}) => `
      <radialGradient id="gl-sphere-${id}" cx=".29" cy=".22" r=".86">
        <stop stop-color="${ice}"/><stop offset=".08" stop-color="${light}"/>
        <stop offset=".31" stop-color="${middle}"/><stop offset=".63" stop-color="${shade}"/>
        <stop offset=".87" stop-color="${dark}"/><stop offset="1" stop-color="${middle}"/>
      </radialGradient>
      <radialGradient id="gl-corona-${id}">
        <stop offset=".56" stop-color="${light}" stop-opacity=".32"/><stop offset="1" stop-color="${light}" stop-opacity="0"/>
      </radialGradient>
    `).join('');
    return `<defs>${materials}
      <radialGradient id="gl-arrival-light">
        <stop stop-color="#e5ddff" stop-opacity=".55"/><stop offset=".54" stop-color="#b9c8ff" stop-opacity=".32"/><stop offset="1" stop-color="#a5b3ff" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="gl-atlas-sky" cx=".64" cy=".44" r=".78">
        <stop stop-color="#1a2036"/><stop offset=".65" stop-color="#101a2c"/><stop offset="1" stop-color="#091321"/>
      </radialGradient>
      <pattern id="gl-atlas-stars" patternUnits="userSpaceOnUse" width="173" height="127" fill="#c5d5f1">
        <circle cx="13" cy="39" r=".7" opacity=".44"/><circle cx="65" cy="106" r=".9" opacity=".36"/>
        <circle cx="121" cy="19" r=".5" opacity=".36"/><circle cx="150" cy="73" r=".65" opacity=".52"/>
      </pattern></defs>
      <rect width="100%" height="100%" fill="url(#gl-atlas-sky)"/>
      <rect width="100%" height="100%" fill="url(#gl-atlas-stars)"/>`;
  }
  function conduit(path, color) {
    return `<g fill="none" stroke-linecap="round" aria-hidden="true">
      <path d="${path}" stroke="${color}" stroke-opacity=".07" stroke-width="10"/>
      <path d="${path}" stroke="${color}" stroke-opacity=".37" stroke-width="4.5"/>
      <path d="${path}" stroke="#081523" stroke-width="2.8"/>
      <path d="${path}" stroke="${color}" stroke-width="1.25"/>
    </g>`;
  }

  function planet(key, radius, accent, selected) {
    // Draw the far side first; the near side runs below the inscription.
    return `<g transform="scale(${radius/48})" aria-hidden="true">
      <circle r="65" fill="url(#gl-corona-${key})"/>
      <g transform="translate(0 10) rotate(-14)">
        <ellipse rx="66" ry="18" fill="none" stroke="${accent}" stroke-opacity=".43" stroke-width="2.8"/>
      </g>
      <circle class="flow-plate" r="48" fill="url(#gl-sphere-${key})" stroke="${selected ? '#dfeeff' : accent}" stroke-width="${selected ? 1.65 : .95}"/>
      <path d="M -40 -24 Q -28 -45 -9 -44 M -38 -27 Q -27 -42 -18 -41" fill="none" stroke="#ecfffc" stroke-opacity=".67" stroke-linecap="round"/>
      <path d="M -39 23 Q -22 43 6 42 Q 25 42 39 25 Q 24 46 3 46 Q -23 47 -39 23" fill="${accent}" opacity=".19"/>
      <g transform="translate(0 10) rotate(-14)" fill="none">
        <path d="M -66 0 A 66 18 0 0 0 66 0" stroke="#0a1020" stroke-width="4.2"/>
        <path d="M -66 0 A 66 18 0 0 0 66 0" stroke="${accent}" stroke-width="2" opacity=".81"/>
        <path d="M -66 0 Q -65 10 -44 13.4" stroke="#effaff" stroke-width="1.15"/>
      </g>
    </g>`;
  }
  function station(key,counts,narrow,selected,[x,y]) {
    const color = tint(key);
    const active = selected === key;
    const body = isHub(key) ? planet(key,hubRadius(narrow),color,active) : vessels.shape(key,bodyWidth(narrow),active);
    const caption = label(0,54,info(key)[0],narrow?13:14,'#f4f8fc',600);
    const number = key==='me' ? '' : label(0,71,format.format(counts[key] || 0),14,color,700,true);
    return `<g role="button" tabindex="0" aria-pressed="${active}" aria-label="${info(key)[0]}" data-station="${key}" data-station-group="${vessels.groupFor(key)}" transform="translate(${x} ${y})">
      <rect x="-35" y="-39" width="70" height="83" rx="16" fill="none" pointer-events="all"/>
      ${body}<g data-station-caption="">${caption}${number}</g>
    </g>`;
  }

  function drawing(counts,narrow,selected,view) {
    const scene = layout(view,narrow);
    const tracks = Object.entries(scene.paths).map(([key,route]) => {
      if(view!=='overview') return conduit(route.d,tint(key));
      const [x,y]=route.point(.50), [u,v]=route.point(.58);
      const angle=Math.atan2(v-y,u-x)*180/Math.PI;
      return '<g class="member-stem"><path d="'+route.d+'" stroke="#142e2f" stroke-width="7" fill="none"/>'+
        '<path d="'+route.d+'" stroke="#649d85" stroke-width="2.2" fill="none"/>'+
        '<g transform="translate('+x+' '+y+') rotate('+angle+')"><path d="M0 0 Q-9 -14 -20 -12 Q-16 -1 0 0Z" fill="#387465" stroke="#83ba91" stroke-width=".7"/></g></g>';
    }).join('');
    const titles = scene.titles.map(t => label(t.x,t.y,t.text,15,vessels.groups[t.group].color,700)).join('');
    const divider = scene.separator ? `<path d="${scene.separator}" stroke="#33445b" fill="none"/>` : '';
    const nodes = Object.entries(scene.positions).map(([key,point]) => station(key,counts,narrow,selected,point)).join('');
    const title = scene.titles.map(t=>t.text).join(' و ');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${scene.width} ${scene.height}" role="group" aria-label="${title}">
      ${spaceBackdrop()}${vessels.defs()}${divider}${tracks}${titles}
      <g data-glows="" pointer-events="none"></g><g data-particles="" pointer-events="none"></g>${nodes}
    </svg>`;
  }
  // Topology and animation geometry are shared by the live UI and the example.
  // Clip the trajectory to the visible surfaces. A flash at a node's center
  // would be hidden behind its opaque glass body.
  const transferPaths = new Map();
  function transferPath(key, narrow, view) {
    const cacheKey = view + '/' + narrow + '/' + key;
    if (transferPaths.has(cacheKey)) return transferPaths.get(cacheKey);

    const scene = layout(view,narrow);
    const route = scene.paths[key];
    if (!route) return null;
    const from = scene.positions[route.from], to = scene.positions[route.to];
    const point = route.point;
    function surface(atSource) {
      const stationKey = atSource ? route.from : route.to;
      const [cx,cy] = atSource ? from : to;
      let inside = atSource ? 0 : 1;
      let outside = 1-inside;
      for (let i=0; i<14; i++) {
        const mid = (inside+outside)/2;
        const [x,y] = point(mid);
        const dx = x-cx, dy = y-cy;
        const inBody = isHub(stationKey) ? Math.hypot(dx,dy) <= hubRadius(narrow)
          : vessels.contains(stationKey,dx,dy,bodyWidth(narrow));
        if (inBody) inside = mid;
        else outside = mid;
      }
      return (inside+outside)/2;
    }
    const entry = surface(true), exit = surface(false);
    // Place each surface ripple below its own port, including diagonal connections.
    const width = bodyWidth(narrow);
    const rippleX = (t, origin) => Math.max(-38,Math.min(38,(point(t)[0]-origin[0])*100/width));
    const path = {
      point: progress => point(entry+(exit-entry)*progress), color:tint(key),
      from:route.from, to:route.to, fromX:rippleX(entry,from), toX:rippleX(exit,to),
    };
    transferPaths.set(cacheKey,path);
    return path;
  }

  function contactFlash([x,y], color, phase) {
    if (phase <= 0 || phase >= 1) return '';
    const strength = Math.min(1,phase/.18) * Math.pow(1-phase,1.4);
    return `<g transform="translate(${x} ${y})" opacity="${strength}">
      <circle r="${8+phase*7}" fill="url(#gl-arrival-light)"/>
      <circle r="${3.1+phase*2}" fill="${color}" opacity=".62"/>
      <path d="M -6 0 Q -1 -.5 0 -4 Q .6 -.5 6 0 Q .6 .5 0 4 Q -.6 .5 -6 0" fill="#f3ffff"/>
      <circle r="1.6" fill="white"/></g>`;
  }

  function motion(events,narrow,view) {
    let particles='', glows='';
    const impacts = new Map();
    for (const {key,t} of events) {
      if (t<0 || t>=1) continue;
      const path = transferPath(key,narrow,view);
      if (!path) continue;
      if (t<.18 && !isHub(path.from)) impacts.set(path.from,path.fromX);
      if (t>=.79 && !isHub(path.to)) impacts.set(path.to,path.toX);
      glows += contactFlash(path.point(0),path.color,t/.13);
      glows += contactFlash(path.point(1),path.color,(t-.79)/.21);
      const progress = (t-.06)/.73;
      if (progress<0 || progress>1.13) continue;
      if (view==='overview' && progress<=1) {
        const [x,y]=path.point(progress), [aheadX,aheadY]=path.point(Math.min(1,progress+.012));
        const angle=Math.atan2(aheadY-y,aheadX-x)*180/Math.PI;
        particles+='<g transform="translate('+x+' '+y+') rotate('+angle+')"><circle r="9" fill="url(#gl-arrival-light)"/>'+
          '<path d="M-7 0 Q-2 -1 0 -3 C5 -5 7 3 2 3 Q-2 2 -7 0" fill="#9bf5d7" stroke="#e7fff3" stroke-width=".7"/>'+
          '<ellipse cx="2" cy="-1.2" rx="1.6" ry=".7" fill="white"/></g>';
        continue;
      }
      for (let j=7; j>=0; j--) {
        const at = progress-j*.018;
        if (at<0 || at>1) continue;
        const [x,y]=path.point(at);
        if (j===0) particles+=`<circle cx="${x}" cy="${y}" r="7" fill="url(#gl-arrival-light)"/>`;
        particles+=`<circle cx="${x}" cy="${y}" r="${j===0?2.7:2.3-j*.22}" fill="${j===0?'#f0ffff':path.color}" opacity="${1-j*.12}"/>`;
      }
    }
    return {particles,glows,impacts};
  }
  const panel=document.getElementById('gl-flow');
  if (!panel) return;
  const root=panel.closest('[data-activity-url]') || panel;
  const host=panel.querySelector('[data-flow-map]'), toggle=panel.querySelector('[data-flow-pause]');
  const viewport=host.closest('[data-map-viewport]');
  const initial=JSON.parse(root.querySelector('#gl-activity-initial').textContent).flow;
  let view='overview';
  let snapshot=initial, selected='me', narrow=false, active=[], raf=0, paused=false;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  function details() {
    panel.querySelector('[data-flow-title]').textContent=info(selected)[0];
    panel.querySelector('[data-flow-description]').textContent=info(selected)[1];
    const c=snapshot.counts;
    const count = panel.querySelector('[data-flow-count]');
    count.style.color=tint(selected);
    count.textContent=selected==='me'?'':format.format(c[selected] || 0);
    const target=panel.querySelector('[data-flow-breakdown]');
    let rows=[];
    if (selected==='me' || selected==='request') {
      rows=[['ویزیت',c.request],['پیگیری رژیم',c.diet],['نوبت دستگاه',c.device],['عضویت شبکه فروش',c.network]];
    } else if (selected==='crm' || selected==='assigned') {
      rows=[['دارای مسئول',c.assigned],['در انتظار مسئول',(c.crm || 0)-(c.assigned || 0)]];
    }
    target.replaceChildren(...rows.map(([name,value])=>{
      const item=document.createElement('span');
      item.textContent=name+'  ·  '+format.format(value || 0);
      return item;
    }));
  }
  function draw() {
    panel.dataset.flowView = view;
    const focused=document.activeElement?.dataset.station;
    narrow=viewport.getBoundingClientRect().width<640;
    host.innerHTML=drawing(snapshot.counts,narrow,selected,view);
    if (focused) host.querySelector('[data-station="'+focused+'"]')?.focus({preventScroll:true});
    details();
  }
  function tick(time) {
    active=active.filter(a=>time-a.start<2400);
    const layers=motion(active.map(a=>({key:a.key,t:(time-a.start)/2400})),narrow,view);
    host.querySelector('[data-particles]').innerHTML=layers.particles;
    host.querySelector('[data-glows]').innerHTML=layers.glows;
    for (const node of host.querySelectorAll('[data-station]')) {
      const offset = layers.impacts.get(node.dataset.station);
      if (offset !== undefined && !node.classList.contains('is-flow-impact')) {
        node.style.setProperty('--glv-impact-x',offset+'px');
      }
      node.classList.toggle('is-flow-impact',offset !== undefined);
    }
    raf=active.length?requestAnimationFrame(tick):0;
  }
  function stop() { active=[]; cancelAnimationFrame(raf); tick(performance.now()); }
  function select(event) {
    const key=event.target.closest('[data-station]')?.dataset.station;
    if (!key) return;
    if (event.type==='keydown' && !['Enter',' '].includes(event.key)) return;
    event.preventDefault(); selected=key; draw();
  }
  panel.querySelector('.flow-views').addEventListener('click',event=>{
    const button=event.target.closest('[data-atlas-view]');
    if (!button) return;
    stop(); view=button.dataset.atlasView;
    selected=view==='members' || view==='overview'?'me':'crm';
    for (const item of panel.querySelectorAll('[data-atlas-view]')) {
      item.setAttribute('aria-pressed',String(button===item));
    }
    draw();
  });
  host.addEventListener('click',select); host.addEventListener('keydown',select);
  toggle.addEventListener('click',()=>{
    paused=!paused; panel.classList.toggle('flow-paused',paused); toggle.setAttribute('aria-pressed',String(paused));
    toggle.textContent=paused?'ادامهٔ حرکت':'توقف حرکت';
    if (paused) stop();
  });
  root.addEventListener('flowupdate',event=>{
    const next=event.detail;
    if (!next || JSON.stringify(next)===JSON.stringify(snapshot)) return;
    const previous=snapshot; snapshot=next;
    if(next.day!==previous.day) stop();
    if (!paused && !reduced.matches && next.day===previous.day) {
      const start=performance.now();
      for(const key of Object.keys(layout(view,narrow).paths)) {
        if ((next.counts[key]||0)>(previous.counts[key]||0)) {
          active=active.filter(a=>a.key!==key);
          active.push({key,start});
        }
      }
    }
    for (const item of host.querySelectorAll('[data-station]')) {
      const key = item.dataset.station;
      if (key !== 'me') item.querySelector('[data-station-count]').textContent = format.format(next.counts[key] || 0);
    }
    details();
    if (!raf && active.length) raf=requestAnimationFrame(tick);
  });
  draw();
  new ResizeObserver(()=>{if((viewport.getBoundingClientRect().width<640)!==narrow) draw();}).observe(viewport);
  reduced.addEventListener('change',()=>{if(reduced.matches) stop();});
})();
