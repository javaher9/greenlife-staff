(() => {
  'use strict';

  const groups = {
    member: { label: 'عضویت و همگام‌سازی', color: '#74e2c4', light: '#d0fff2', water: '#289f92', deep: '#12515c' },
    intake: { label: 'منابع جذب لید', color: '#bf9aef', light: '#f1e4ff', water: '#8660af', deep: '#423266' },
    service: { label: 'خدمات و نوبت', color: '#f5c378', light: '#fff0cd', water: '#ba884a', deep: '#66432d' },
    followup: { label: 'پیگیری لید', color: '#8ec9fa', light: '#dcf1ff', water: '#548fbc', deep: '#294d72' },
  };
  const membership = {
    me:'member', account:'member', sync:'member',
    crm:'intake', website:'intake', instagram:'intake', school:'intake', other:'intake',
    request:'service', booked:'service', diet:'service', device:'service', network:'service',
    assigned:'followup', lead_new:'followup', lead_contacted:'followup', lead_appointment:'followup',
    lead_visited:'followup', lead_won:'followup', lead_lost:'followup',
  };
  const groupFor = key => Object.hasOwn(membership,key) ? membership[key] : undefined;

  // A uniform 100-unit reference width keeps each instrument upright at any
  // size. The trajectory clipper uses the exact outline drawn by the SVG.
  function outline(start, curves) {
    const points = [start];
    for (const [a,b,c,d,x,y] of curves) {
      const [sx,sy] = points[points.length-1];
      for (let step=1; step<=12; step++) {
        const t=step/12, u=1-t;
        const cubic = (p0,p1,p2,p3) => +(u*u*u*p0 + 3*u*u*t*p1 + 3*u*t*t*p2 + t*t*t*p3).toFixed(3);
        points.push([cubic(sx,a,c,x),cubic(sy,b,d,y)]);
      }
    }
    // The final curve closes at the start.
    points.pop();
    return points;
  }
  const hulls = {
    member: outline([24,-65],[
      [13,-65,-14,-45,-31,-21], [-44,-3,-49,18,-42,36], [-36,55,-19,64,0,64],
      [24,64,39,45,44,21], [50,-6,42,-31,33,-53], [30,-62,27,-65,24,-65],
    ]),
    intake:[[-7,-69],[24,-48],[41,-30],[39,26],[24,45],[2,69],[-27,49],[-40,30],[-39,-32]],
    service: outline([-34,-42],[
      [-34,-49,-28,-50,-25,-55], [-24,-57,-23,-58,-20,-58], [-10,-58,10,-58,20,-58],
      [23,-58,24,-57,25,-55], [28,-50,34,-49,34,-42], [34,-18,34,24,34,46],
      [34,54,30,58,23,58], [9,58,-9,58,-23,58], [-30,58,-34,54,-34,46], [-34,22,-34,-22,-34,-42],
    ]),
    followup: outline([-39,-52],[
      [-39,-65,39,-65,39,-52], [39,-23,39,22,39,52],
      [39,65,-39,65,-39,52], [-39,24,-39,-24,-39,-52],
    ]),
  };

  function contains(key, dx, dy, width) {
    const points = hulls[groupFor(key)];
    if (!points || !(width > 0)) return false;
    const x = dx * 100 / width, y = dy * 100 / width;
    let inside = false;
    for (let i=0,j=points.length-1; i<points.length; j=i++) {
      const [ax,ay]=points[j], [bx,by]=points[i];
      const cross=(x-ax)*(by-ay) - (y-ay)*(bx-ax);
      if (Math.abs(cross)<1e-5 && x >= Math.min(ax,bx) && x <= Math.max(ax,bx)
          && y >= Math.min(ay,by) && y <= Math.max(ay,by)) return true;
      if ((ay>y)!==(by>y) && x<(bx-ax)*(y-ay)/(by-ay)+ax) inside=!inside;
    }
    return inside;
  }

  // A physical liquid line at all nodes is decorative. Counts and event
  // changes are rendered independently by the atlas from authoritative data.
  const wave = ' q8-5.5 17-1.6 t17 1.6 q6 3.7 13 1.5 t13-1.5'.repeat(4);
  const glass = {
    member: `<path d="M-38 10C-35-18-14-43 15-56C-4-42-24-15-30 7Q-35 24-38 10Z" fill="url(#glv-sheen)" opacity=".62"/>
      <path d="M-40 9Q-37-18-12-42Q5-57 22-61M-39 28Q-34 48-17 56" fill="none" stroke="#dcfff6" opacity=".83" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M36-26C48 18 30 53 5 58" fill="none" stroke="currentColor" opacity=".75" stroke-width="1.6"/> `,
    intake: `<path d="M-7-69 24-48 41-30 24-23 10-40Z" fill="#dfc8ff" opacity=".31"/>
      <path d="M-7-69-39-32-26-23 3-47Z" fill="url(#glv-sheen)" opacity=".77"/>
      <path d="M-39-32-26-23-25 23-40 30Z" fill="#ecd9ff" opacity=".17"/>
      <path d="M41-30 39 26 24 33 24-23Z" fill="currentColor" opacity=".27"/>
      <path d="M39 26 2 69 24 33Z" fill="#ead9ff" opacity=".43"/>
      <path d="M-40 30-27 49 2 69-14 39-25 23Z" fill="currentColor" opacity=".38"/>
      <path d="M-39-32-7-68 23-48M-26-23 3-47 24-23M24-23V33L2 68M-25 23-14 39" stroke="#efe5ff" stroke-opacity=".58" stroke-width="1.4" fill="none"/> `,
    service: `<path d="M-31-35Q-31-47-24-49L-20-54H16M-30-23V30Q-30 48-25 51M28-30V38" stroke="#fff3d6" opacity=".77" stroke-width="1.7" fill="none" stroke-linecap="round"/>
      <path d="M-28-39-21-45V40L-26 46Z" fill="url(#glv-sheen)" opacity=".56"/>
      <path d="M21-41 26-36 26 42 21 46Z" fill="#fff1cf" opacity=".14"/>
      <path d="M-17-54H17M-23 52H22" stroke="currentColor" stroke-width="2.2" fill="none"/>
      <path d="M16-28H22M18-17H22M16-6H22" stroke="#ffe8b8" stroke-opacity=".68" stroke-width="1.35"/> `,
    followup: `<ellipse cy="-52" rx="38.3" ry="9" fill="url(#glv-cap)" stroke="#bbdbed" stroke-width="1.35"/>
      <ellipse cy="-52" rx="31" ry="5.7" fill="#263e57" stroke="currentColor" stroke-opacity=".75" stroke-width=".95"/>
      <path d="M-38 47C-37 60 37 60 38 47V52C37 65-37 65-38 52Z" fill="url(#glv-cap)" stroke="currentColor" stroke-opacity=".65"/>
      <path d="M-33-54Q-21-60 1-60M-34-40V33M-30 53Q-6 61 20 56" fill="none" stroke="#edfbff" stroke-opacity=".8" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M-31-43-24-41V44L-31 42ZM24-41 30-43V43L24 46Z" fill="url(#glv-sheen)" opacity=".53"/> `,
  };

  function defs() {
    const materials = Object.entries(groups).map(([name, palette]) => {
      const coordinates=hulls[name].map(p=>p.join(',')).join(' ');
      return `<polygon id="glv-hull-${name}" points="${coordinates}"/>
        <clipPath id="glv-inside-${name}"><use href="#glv-hull-${name}" transform="scale(.89 .91)"/></clipPath>
        <linearGradient id="glv-water-${name}" gradientUnits="userSpaceOnUse" x1="-45" y1="7" x2="43" y2="29">
          <stop stop-color="${palette.deep}"/><stop offset=".12" stop-color="${palette.water}"/><stop offset=".25" stop-color="${palette.color}"/><stop offset=".42" stop-color="${palette.water}"/><stop offset=".67" stop-color="${palette.deep}"/><stop offset=".89" stop-color="${palette.water}"/><stop offset="1" stop-color="${palette.color}"/>
        </linearGradient>
        <linearGradient id="glv-chamber-${name}" x1="0" y1="0" x2=".98" y2=".58">
          <stop stop-color="#92a6b0"/><stop offset=".10" stop-color="${palette.deep}"/><stop offset=".29" stop-color="#253b48"/><stop offset=".60" stop-color="#112331"/><stop offset=".9" stop-color="${palette.deep}"/><stop offset="1" stop-color="${palette.color}"/>
        </linearGradient>`;
    }).join('');
    return `<defs>${materials}
      <linearGradient id="glv-rim" x1="0" y1="0" x2=".85" y2="1"><stop stop-color="#e2f2fa"/><stop offset=".16" stop-color="#81949f"/><stop offset=".31" stop-color="#33434f"/><stop offset=".65" stop-color="#243442"/><stop offset=".91" stop-color="#8199a5"/><stop offset="1" stop-color="#3c5261"/></linearGradient>
      <linearGradient id="glv-cap" x1="0" y1="0" x2=".72" y2="1"><stop stop-color="#aabecb"/><stop offset=".30" stop-color="#5c707d"/><stop offset=".75" stop-color="#263b49"/><stop offset="1" stop-color="#496377"/></linearGradient>
      <linearGradient id="glv-sheen"><stop stop-color="#f4fcff" stop-opacity=".12"/><stop offset=".35" stop-color="#f4fcff"/><stop offset="1" stop-color="#d9f7ff" stop-opacity=".05"/></linearGradient>
      <radialGradient id="glv-pearl" cx=".32" cy=".23" r=".78"><stop stop-color="#fff"/><stop offset=".28" stop-color="#eaffff" stop-opacity=".74"/><stop offset=".65" stop-color="#b5e8f6" stop-opacity=".12"/><stop offset="1" stop-color="#edfaff" stop-opacity=".56"/></radialGradient>
      <style>
        .glv-slosh { animation:glv-tide var(--glv-period) ease-in-out var(--glv-phase) infinite alternate; }
        .glv-bubble { opacity:.94; transform:translateY(var(--glv-still)); animation:glv-rise 5.2s linear var(--glv-born) infinite; }
        [data-station].is-flow-impact .glv-reaction { animation:glv-splash .38s ease-out; transform-origin:0 7px; }
        .glv-ripple { opacity:0; }
        [data-station].is-flow-impact .glv-ripple { animation:glv-ripple .38s ease-out; }
        .flow-paused .glv-slosh,.flow-paused .glv-bubble,.is-still .glv-slosh,.is-still .glv-bubble { animation-play-state:paused; }
        .flow-paused [data-station].is-flow-impact .glv-reaction,.flow-paused [data-station].is-flow-impact .glv-ripple,
        .is-still [data-station].is-flow-impact .glv-reaction,.is-still [data-station].is-flow-impact .glv-ripple { animation:none; }
        @keyframes glv-tide { from { transform:translateX(-11px) rotate(-1.5deg); } to { transform:translateX(11px) rotate(1.5deg); } }
        @keyframes glv-rise {
          0% { transform:translate(0,0) scale(.65); opacity:0; } 9% { opacity:.96; }
          55% { transform:translate(var(--glv-drift),var(--glv-mid)); opacity:.96; }
          84% { opacity:.93; } 100% { transform:translate(0,var(--glv-rise)) scale(.8); opacity:0; }
        }
        @keyframes glv-splash { 0% { transform:rotate(0); } 25% { transform:rotate(2deg); } 56% { transform:rotate(-1.2deg); } 100% { transform:rotate(0); } }
        @keyframes glv-ripple { 0% { opacity:0; transform:scale(.16,.4); } 26% { opacity:.8; } 100% { opacity:0; transform:scale(1.35,1); } }
        @media(prefers-reduced-motion:reduce) { .glv-slosh,.glv-bubble,[data-station].is-flow-impact .glv-reaction,[data-station].is-flow-impact .glv-ripple { animation:none; } }
      </style></defs>`;
  }

  // Start each instrument mid-cycle. A static pose stays legible with motion
  // disabled. The moving liquid clip ensures bubbles disappear at its surface.
  const bubbles = [[-14,41,3.5],[13,45,2.6],[-5,48,2.15],[20,35,2.9],[-21,33,2.25]];
  function pearls(seed) {
    return bubbles.map(([x,bottom,radius],index) => {
      const phase=(index/5 + (seed%19)/19) % 1;
      const rise=9-bottom;
      return `<g transform="translate(${x} ${bottom})"><g class="glv-bubble" style="--glv-born:-${(5.2*phase).toFixed(2)}s;--glv-still:${Math.round(rise*(.1+.8*phase))}px;--glv-mid:${Math.round(rise*.53)}px;--glv-rise:${rise}px;--glv-drift:${index%2?-2:2}px">
        <circle r="${radius}" fill="url(#glv-pearl)" stroke="#e2fdff" stroke-width="1.0"/>
        <circle cx="${-radius*.34}" cy="${-radius*.36}" r="${radius*.22}" fill="white"/>
      </g></g>`;
    }).join('');
  }
  function shape(key, width, selected=false) {
    const name=groupFor(key);
    if (!name || !(width>0)) return '';
    const swatch=groups[name];
    const seed=Array.from(key).reduce((value,c)=>value+c.charCodeAt(0),0);
    const waterStart = -115 + seed % 27;
    const crest = 'M' + waterStart + ' 7' + wave;
    const volume = crest + ' V75 H' + waterStart + 'Z';
    const hull='glv-hull-'+name,inside='glv-inside-'+name,water='glv-liquid-'+key;
    return `<g aria-hidden="true" transform="scale(${width/100})" color="${swatch.color}" style="--glv-period:${(3.1+seed%13/10).toFixed(1)}s;--glv-phase:-${(seed%55/10).toFixed(1)}s">
      <defs><clipPath id="${water}"><path class="glv-slosh" d="${volume}"/></clipPath></defs>
      <use href="#${hull}" transform="translate(0 2)" fill="#030b15" opacity=".8"/>
      <use href="#${hull}" class="flow-plate" fill="url(#glv-rim)" stroke="${selected?'#f0fbff':swatch.color}" stroke-width="${selected?2.7:1.5}"/>
      <use href="#${hull}" transform="scale(.948 .961)" fill="url(#glv-chamber-${name})" stroke="${swatch.light}" stroke-opacity=".42" stroke-width="1.1"/>
      <g clip-path="url(#${inside})"><g class="glv-reaction">
        <g class="glv-slosh">
          <path d="${volume}" transform="translate(0 -2.8)" fill="${swatch.color}" opacity=".61"/>
          <path d="${volume}" fill="url(#glv-water-${name})"/>
          <path d="${crest}" fill="none" stroke="${swatch.light}" stroke-width="1.7"/>
        </g>
        <g clip-path="url(#${water})">${pearls(seed)}</g>
        <g style="transform:translateX(var(--glv-impact-x, 20px))"><g transform="translate(0 7)"><ellipse class="glv-ripple" rx="11" ry="2.1" fill="none" stroke="${swatch.light}" stroke-width=".8"/></g></g>
      </g></g>
      ${glass[name]}
    </g>`;
  }

  window.GreenLifeFlowVessels = {groups,groupFor,shape,contains,defs};
})();
