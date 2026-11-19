(() => {
  'use strict';
  const format = new Intl.NumberFormat('fa-IR-u-nu-latn');
  // Each station declares its own label, definition and desktop/mobile anchors.
  // The two systems share a dashboard, but an account is never implicitly a lead.
  const stations = {
    me: ['گرین‌لایف ME', 'مسیر حساب مشترک، همگام‌سازی در اپ و درخواست ویزیت.', [722,116], [332,124]],
    account: ['ثبت‌نام با شماره', 'حساب‌های مشترک جدید امروز با ورود تأییدشده. شمارهٔ شخص روی نقشه نمایش داده نمی‌شود.', [500,55], [185,66]],
    sync: ['همگام‌سازی اپ', 'تعداد ذخیره‌های موفق حساب در اپ ME امروز. یک عضو می‌تواند چند بار ذخیره کند.', [500,175], [184,190]],
    request: ['درخواست ویزیت', 'درخواست‌های ویزیت ثبت‌شدهٔ امروز در مسیر مشترک اعضا و ME.', [354,116], [188,129]],
    booked: ['نوبت تأییدشده', 'از درخواست‌های ویزیت امروز، چند درخواست اکنون نوبت تأییدشده و متصل دارند.', [137,116], [59,129]],
    website: ['وب‌سایت', 'لیدهای امروز در گروه وب‌سایت.', [783,261], [329,289]],
    instagram: ['اینستاگرام', 'لیدهای امروز در گروه اینستاگرام. دریافت دایرکت به‌تنهایی شمارندهٔ لید را بالا نمی‌برد.', [783,320], [329,354]],
    school: ['مدارس', 'لیدهای امروز با ثبت‌نام مدرسهٔ مرتبط. هر پرونده فقط در یک شاخه شمرده می‌شود.', [783,379], [329,419]],
    other: ['سایر منابع', 'سایر پرونده‌های لید امروز، از جمله گروه‌های معرفی و کمپ.', [783,438], [329,484]],
    crm: ['لیدهای فشرده', 'کل پرونده‌های لید ثبت‌شدهٔ امروز از چهار مسیر ورودی.', [488,350], [185,383]],
    assigned: ['دارای مسئول', 'از لیدهای ثبت‌شدهٔ امروز، چند پرونده هم‌اکنون مسئول پیگیری دارد.', [179,350], [57,383]],
  };
  const routes = [
    ['me','account','account'], ['me','sync','sync'], ['me','request','request'], ['request','booked','booked'],
    ['website','crm','website'], ['instagram','crm','instagram'], ['school','crm','school'], ['other','crm','other'],
    ['crm','assigned','assigned'],
  ];
  const aquamarine = '#6eeac7', lilac = '#bc9aff';
  const isMe = key => ['me','account','sync','request','booked'].includes(key);
  const tint = key => isMe(key) ? aquamarine : lilac;
  const isHub = key => key === 'me' || key === 'crm';
  const coord = (key, narrow) => stations[key][narrow ? 3 : 2];
  const arabic = 'Noto Sans Arabic,Tahoma,Arial,sans-serif';
  function label(x,y,value,size,color,weight=500) {
    return '<text direction="rtl" unicode-bidi="plaintext" x="'+x+'" y="'+y+'" text-anchor="middle" font-family="'+arabic+'" font-size="'+size+'" font-weight="'+weight+'" fill="'+color+'">'+value+'</text>';
  }
  function curve(route,narrow) {
    const [x,y]=coord(route[0],narrow), [u,v]=coord(route[1],narrow);
    const mid=(x+u)/2;
    return {path:'M '+x+' '+y+' C '+mid+' '+y+' '+mid+' '+v+' '+u+' '+v,
      point(t) {
        const z=1-t;
        return [z*z*z*x+3*z*t*mid+t*t*t*u, z*z*z*y+3*z*z*t*y+3*z*t*t*v+t*t*t*v];
      }};
  }
  const rooms = {
    members: { hub:'me', caption:'داخل گرین‌لایف ME', color:aquamarine,
      keys:['account','sync','request','diet','device','network'] },
    leads: { hub:'crm', caption:'وضعیت فعلی لیدهای ثبت‌شدهٔ امروز', color:lilac,
      keys:['lead_new','lead_contacted','lead_appointment','lead_visited','lead_won','lead_lost'] },
  };
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
  function roomGraph(room,narrow) {
    const [cx,cy]=narrow?[200,191]:[460,177];
    const rx=narrow?134:258, ry=narrow?127:119;
    const positions={[room.hub]:[cx,cy]};
    room.keys.forEach((key,i)=>{
      const angle=(i*60-90)*Math.PI/180;
      positions[key]=[Math.round(cx+rx*Math.cos(angle)),Math.round(cy+ry*Math.sin(angle))];
    });
    return positions;
  }
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
      <linearGradient id="gl-tube-${id}" x2="0" y2="1">
        <stop stop-color="${middle}"/><stop offset=".075" stop-color="${ice}"/><stop offset=".135" stop-color="${middle}"/>
        <stop offset=".30" stop-color="${shade}"/><stop offset=".64" stop-color="${dark}"/>
        <stop offset=".83" stop-color="${shade}"/><stop offset=".93" stop-color="${middle}"/><stop offset="1" stop-color="${dark}"/>
      </linearGradient>
      <linearGradient id="gl-fiber-${id}" x1="0" y1="0" x2="0" y2="1" gradientUnits="userSpaceOnUse" gradientTransform="scale(1 370)">
        <stop stop-color="${light}"/><stop offset=".46" stop-color="${ice}"/><stop offset="1" stop-color="${light}"/>
      </linearGradient>`).join('');
    return `<defs>${materials}
      <linearGradient id="gl-ferrule" x1="0" y1="0" x2=".22" y2="1">
        <stop stop-color="#718898"/><stop offset=".13" stop-color="#c5d5e9"/>
        <stop offset=".29" stop-color="#27384e"/><stop offset=".65" stop-color="#0c1626"/>
        <stop offset=".85" stop-color="#45546e"/><stop offset="1" stop-color="#142437"/>
      </linearGradient>
      <linearGradient id="gl-tube-reflection">
        <stop stop-color="#e3faff" stop-opacity="0"/><stop offset=".58" stop-color="#f1fcff" stop-opacity=".85"/>
        <stop offset="1" stop-color="#e3faff" stop-opacity="0"/>
      </linearGradient>
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
    const fiber = color===aquamarine ? 'me' : 'crm';
    return `<g fill="none" stroke-linecap="round" aria-hidden="true">
      <path d="${path}" stroke="${color}" stroke-opacity=".055" stroke-width="11"/>
      <path d="${path}" stroke="${color}" stroke-opacity=".30" stroke-width="5"/>
      <path d="${path}" stroke="#081523" stroke-width="3.3"/>
      <path d="${path}" stroke="url(#gl-fiber-${fiber})" stroke-width="1.15" stroke-opacity=".91"/>
    </g>`;
  }

  function glassTube(key, width, accent, selected) {
    const cap = width/2 - 6;
    const material = accent===aquamarine ? 'me' : 'crm';
    const left = -cap+5, right = cap-5;
    // The dark inner chamber sits behind a curved double wall and two recessed couplings.
    return `<g aria-hidden="true">
      <defs><clipPath id="gl-glass-${key}"><rect x="${left}" y="-19" width="${right-left}" height="35" rx="4"/></clipPath></defs>
      <rect x="${-cap}" y="-16" width="${cap*2}" height="42" rx="7" fill="#030810" opacity=".75"/>
      <path class="flow-plate" d="M ${-cap} -21 Q 0 -23 ${cap} -21 V 21 Q 0 23 ${-cap} 21 Z"
        fill="url(#gl-tube-${material})" stroke="${selected ? '#ebfaff' : accent}" stroke-opacity="${selected ? '.98' : '.69'}" stroke-width="${selected ? 1.65 : .85}"/>
      <g clip-path="url(#gl-glass-${key})">
        <rect x="${left}" y="-11" width="${right-left}" height="25" rx="4" fill="#07111e" opacity=".36"/>
        <path d="M ${left} -17 Q 0 -19 ${right} -17 M ${left} 16 Q 0 18 ${right} 16" fill="none" stroke="${accent}" stroke-width="1.2" opacity=".82"/>
        <g class="flow-glint" style="--gl-travel:${width+24}px;--gl-delay:-${(cap+key.length)%7}s">
          <rect x="${-cap-26}" y="-19" width="30" height="5" fill="url(#gl-tube-reflection)"/>
          <path d="M ${-cap-20} -16 l 7 3 -11 27 h -6 z" fill="${accent}" opacity=".09"/>
        </g>
      </g>
      <path d="M ${left} -21 v 42 M ${right} -21 v 42" stroke="#060f1f" stroke-width="2"/>
      <ellipse cx="${-cap}" rx="5.5" ry="22.4" fill="url(#gl-ferrule)" stroke="${accent}" stroke-width=".8"/>
      <path d="M ${-cap+1.5} -16 q -3 13 -1 25" fill="none" stroke="${accent}" opacity=".87" stroke-width="1.3"/>
      <ellipse cx="${cap}" rx="5.7" ry="22.4" fill="url(#gl-ferrule)" stroke="${accent}" stroke-width=".9"/>
      <ellipse cx="${cap+1.1}" rx="3.3" ry="15.4" fill="#081421" stroke="${accent}" stroke-width=".8"/>
      <ellipse cx="${cap+1.6}" rx="1.35" ry="8" fill="${accent}" opacity=".74"/>
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
  function roomDrawing(room,counts,narrow,selected){
    const nodes=roomGraph(room,narrow), w=narrow?400:920,h=narrow?380:355;
    const [cx,cy]=nodes[room.hub], c=room.color;
    let tracks='';
    for(const key of room.keys){
      const [x,y]=nodes[key];
      tracks+=conduit(`M ${cx} ${cy} L ${x} ${y}`, c);
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+w+' '+h+'" role="group" aria-label="'+room.caption+'">'+spaceBackdrop()+
      label(w/2,26,room.caption,15,c)+tracks+'<g data-glows="" pointer-events="none"></g><g data-particles="" pointer-events="none"></g>'+
      Object.keys(nodes).map(key=>station(key,counts,narrow,selected,nodes[key],c)).join('')+
      '</svg>';
  }
  function station(key,counts,narrow,selected,position,color) {
    const [x,y]=position || coord(key,narrow), c=color || tint(key), hub=isHub(key), width=narrow?105:140;
    const number=counts[key] || 0;
    let shape;
    if (hub) {
      const r=narrow?40:48;
      shape=planet(key,r,c,selected===key)+
        label(0,0,info(key)[0],narrow?11:14,'#f6f4ff',700)+
        label(0,20,key==='crm'?format.format(number):'ME',14,c,700);
    } else {
      shape=glassTube(key,width,c,selected===key)+
        label(0,-2,info(key)[0],narrow?12:14,'#f4f8fc',600)+label(0,14,format.format(number),13,c,700);
    }
    return '<g role="button" tabindex="0" aria-pressed="'+(selected===key)+'" aria-label="'+info(key)[0]+'" data-station="'+key+'" transform="translate('+x+' '+y+')">'+shape+'</g>';
  }
  function drawing(counts,narrow,selected,view) {
    if (rooms[view]) return roomDrawing(rooms[view],counts,narrow,selected);
    const w=narrow?400:920, h=narrow?526:485, split=narrow?228:215;
    const tracks=routes.map(route=>conduit(curve(route,narrow).path,tint(route[2]))).join('');
    const nodes=Object.keys(stations).map(k=>station(k,counts,narrow,selected)).join('');
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+w+' '+h+'" role="group" aria-label="نقشه مسیر اعضا و منابع لید">'+
      spaceBackdrop()+
      '<path d="M 15 '+split+' H '+(w-15)+'" stroke="#33445b"/>'+
      label(narrow?67:95,24,'مسیر اعضا',14,aquamarine,700)+label(narrow?80:104,split+25,'مسیر جذب لید',14,lilac,700)+tracks+
      '<g data-glows="" pointer-events="none"></g><g data-particles="" pointer-events="none"></g>'+nodes+'</svg>';
  }
  // Topology and animation geometry are shared by the live UI and the example.
  // Clip the trajectory to the visible surfaces. A flash at a node's center
  // would be hidden behind its opaque glass body.
  const transferPaths = new Map();
  function transferPath(key, narrow, view) {
    const cacheKey = view + '/' + narrow + '/' + key;
    if (transferPaths.has(cacheKey)) return transferPaths.get(cacheKey);

    const room = rooms[view];
    const route = room ? [room.hub, key] : routes.find(item => item[2] === key);
    if (!route || (room && !room.keys.includes(key))) return null;
    const positions = room && roomGraph(room, narrow);
    const center = stationKey => room ? positions[stationKey] : coord(stationKey, narrow);
    const from = center(route[0]), to = center(route[1]);
    const point = room ? t => [from[0]+(to[0]-from[0])*t, from[1]+(to[1]-from[1])*t] : curve(route, narrow).point;

    function surface(atSource) {
      const stationKey = route[atSource ? 0 : 1];
      const [cx,cy] = atSource ? from : to;
      let inside = atSource ? 0 : 1;
      let outside = 1-inside;
      for (let i=0; i<14; i++) {
        const mid = (inside+outside)/2;
        const [x,y] = point(mid);
        const dx = Math.abs(x-cx), dy = Math.abs(y-cy);
        const inBody = isHub(stationKey) ? Math.hypot(dx,dy) <= (narrow?40:48)
          : dx <= (narrow?52.5:70) && dy <= 22;
        if (inBody) inside = mid;
        else outside = mid;
      }
      return (inside+outside)/2;
    }
    const entry = surface(true), exit = surface(false);
    const path = { point: progress => point(entry+(exit-entry)*progress), color: room ? room.color : tint(key) };
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
    for (const {key,t} of events) {
      if (t<0 || t>=1) continue;
      const path = transferPath(key,narrow,view);
      if (!path) continue;
      glows += contactFlash(path.point(0),path.color,t/.13);
      glows += contactFlash(path.point(1),path.color,(t-.79)/.21);
      const progress = (t-.06)/.73;
      if (progress<0 || progress>1.13) continue;
      for (let j=7; j>=0; j--) {
        const at = progress-j*.018;
        if (at<0 || at>1) continue;
        const [x,y]=path.point(at);
        if (j===0) particles+=`<circle cx="${x}" cy="${y}" r="7" fill="url(#gl-arrival-light)"/>`;
        particles+=`<circle cx="${x}" cy="${y}" r="${j===0?2.7:2.3-j*.22}" fill="${j===0?'#f0ffff':path.color}" opacity="${1-j*.12}"/>`;
      }
    }
    return {particles,glows};
  }
  const panel=document.getElementById('gl-flow');
  if (!panel) return;
  const root=panel.closest('[data-activity-url]') || panel;
  const host=panel.querySelector('[data-flow-map]'), toggle=panel.querySelector('[data-flow-pause]');
  const viewport=host.parentElement;
  const initial=JSON.parse(root.querySelector('#gl-activity-initial').textContent).flow;
  let view='overview';
  let snapshot=initial, selected='crm', narrow=false, active=[], raf=0, paused=false;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  function details() {
    panel.querySelector('[data-flow-title]').textContent=info(selected)[0];
    panel.querySelector('[data-flow-description]').textContent=info(selected)[1];
    const c=snapshot.counts;
    panel.querySelector('[data-flow-count]').textContent=selected==='me'?'':format.format(c[selected] || 0);
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
    selected=view==='members'?'me':'crm';
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
      for(const key of (rooms[view]?.keys || routes.map(route=>route[2]))) {
        if ((next.counts[key]||0)>(previous.counts[key]||0)) {
          active=active.filter(a=>a.key!==key);
          active.push({key,start});
        }
      }
    }
    for (const item of host.querySelectorAll('[data-station]')) {
      const key = item.dataset.station;
      if (key !== 'me') item.querySelector('text:last-child').textContent = format.format(next.counts[key] || 0);
    }
    details();
    if (!raf && active.length) raf=requestAnimationFrame(tick);
  });
  draw();
  new ResizeObserver(()=>{if((viewport.getBoundingClientRect().width<640)!==narrow) draw();}).observe(viewport);
  reduced.addEventListener('change',()=>{if(reduced.matches) stop();});
})();
