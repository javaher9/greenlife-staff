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
    const planets = [
      ['me', '#b2ebdd', '#35756d', '#123a42', '#081824'],
      ['crm', '#d9c2ee', '#766391', '#382d55', '#111424'],
    ].map(([id, light, middle, shade, dark]) =>
      `<radialGradient id="gl-sphere-${id}" cx="32%" cy="22%" r="80%">
        <stop stop-color="${light}"/><stop offset=".24" stop-color="${middle}"/>
        <stop offset=".6" stop-color="${shade}"/><stop offset=".91" stop-color="${dark}"/>
        <stop offset="1" stop-color="${shade}"/></radialGradient>`
    ).join('');
    return `<defs>${planets}
      <linearGradient id="gl-station-glass" x2=".4" y2="1" gradientUnits="objectBoundingBox">
        <stop stop-color="#29374e"/><stop offset=".42" stop-color="#1a293e"/><stop offset="1" stop-color="#101c2e"/>
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
  function roomDrawing(room,counts,narrow,selected){
    const nodes=roomGraph(room,narrow), w=narrow?400:920,h=narrow?380:355;
    const [cx,cy]=nodes[room.hub], c=room.color;
    let tracks='';
    for(const key of room.keys){
      const [x,y]=nodes[key];
      tracks+='<path d="M '+cx+' '+cy+' L '+x+' '+y+'" stroke="'+c+'" stroke-opacity=".48"/>';
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
      shape=`<ellipse cy="${r*.94}" rx="${r*.83}" ry="${r*.16}" fill="#050a16" opacity=".64"/>
        <circle class="flow-plate" r="${r}" fill="url(#gl-sphere-${key})" stroke="${selected===key?c:'#8997b0'}" stroke-width="${selected===key?1.8:.8}"/>
        <path d="M ${-.84*r} ${-.43*r} Q ${-.61*r} ${-.94*r} ${-.12*r} ${-.93*r}" fill="none" stroke="#f0f6ff" stroke-opacity=".64" stroke-linecap="round" stroke-width="1.6"/>`+
        label(0,0,info(key)[0],narrow?11:14,'#f6f4ff',700)+
        label(0,20,key==='crm'?format.format(number):'ME',14,c,700);
    } else {
      shape='<rect class="flow-plate" x="'+(-width/2)+'" y="-23" width="'+width+'" height="46" rx="12" fill="url(#gl-station-glass)" stroke="'+(selected===key?c:'#394960')+'"/>'+
        label(0,-3,info(key)[0],narrow?12:14,'#edf2fc')+label(0,15,format.format(number),13,c,700);
    }
    return '<g role="button" tabindex="0" aria-pressed="'+(selected===key)+'" aria-label="'+info(key)[0]+'" data-station="'+key+'" transform="translate('+x+' '+y+')">'+shape+'</g>';
  }
  function drawing(counts,narrow,selected,view) {
    if (rooms[view]) return roomDrawing(rooms[view],counts,narrow,selected);
    const w=narrow?400:920, h=narrow?526:485, split=narrow?228:215;
    const tracks=routes.map(route=>'<path d="'+curve(route,narrow).path+'" fill="none" stroke="'+tint(route[2])+'" stroke-opacity=".47" stroke-width="1.5"/>').join('');
    const nodes=Object.keys(stations).map(k=>station(k,counts,narrow,selected)).join('');
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+w+' '+h+'" role="group" aria-label="نقشه مسیر اعضا و منابع لید">'+
      spaceBackdrop()+
      '<path d="M 15 '+split+' H '+(w-15)+'" stroke="#33445b"/>'+
      label(narrow?67:95,24,'مسیر اعضا',14,aquamarine,700)+label(narrow?80:104,split+25,'مسیر جذب لید',14,lilac,700)+tracks+
      '<g data-glows="" pointer-events="none"></g><g data-particles="" pointer-events="none"></g>'+nodes+'</svg>';
  }
  // Topology and animation geometry are shared by the live UI and the example.
  function motion(events,narrow,view) {
    const room=rooms[view], positions=room && roomGraph(room,narrow);
    let particles='', glows='';
    for (const {key,t} of events) {
      const route=routes.find(item=>item[2]===key);
      if (t<0 || t>=1 || (room ? !room.keys.includes(key) : !route)) continue;
      const ends=room?[room.hub,key]:route;
      const c=room?room.color:tint(key), p=Math.min(1,t/.75);
      const arc=room?{point(f){
        const [x,y]=positions[room.hub], [u,v]=positions[key];
        return [x+(u-x)*f,y+(v-y)*f];
      }}:curve(route,narrow);
      for (let j=4;j>=0;j--) {
        const [x,y]=arc.point(Math.max(0,p-j*.032));
        particles+='<circle cx="'+x+'" cy="'+y+'" r="'+(j===0?3.8:3-j*.35)+'" fill="'+(j===0?'#efffff':c)+'" opacity="'+(1-j*.16)+'"/>';
      }
      const terminal=t<.40?ends[0]:t>.64?ends[1]:null;
      if (terminal) {
        const [x,y]=room?positions[terminal]:coord(terminal,narrow), r=isHub(terminal)?(narrow?44:52):26;
        const strength = terminal===ends[0] ? 1-t/.4 : Math.sin(Math.PI*(t-.64)/.36);
        glows+=`<ellipse cx="${x}" cy="${y}" rx="${r*(isHub(terminal)?1.55:3.25)}" ry="${r*1.58}" fill="url(#gl-arrival-light)" opacity="${strength}"/>`;
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
    paused=!paused; toggle.setAttribute('aria-pressed',String(paused));
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
    draw();
    if (!raf && active.length) raf=requestAnimationFrame(tick);
  });
  draw();
  new ResizeObserver(()=>{if((viewport.getBoundingClientRect().width<640)!==narrow) draw();}).observe(viewport);
  reduced.addEventListener('change',()=>{if(reduced.matches) stop();});
})();
