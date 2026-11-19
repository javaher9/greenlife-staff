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

  // Outlines share a 100-unit-wide coordinate system. The renderer and the
  // trajectory clipper use the very same vertices, including the seed's nose.
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
    member: outline([-50,1],[
      [-51,-13,-42,-21,-23,-22], [-3,-24,25,-17,43,-7],
      [50,-3,53,2,46,6], [40,10,28,13,14,18],
      [-6,25,-29,24,-42,15], [-47,12,-50,7,-50,1],
    ]),
    intake:[[-50,-3],[-34,-18],[-17,-22],[30,-21],[50,-9],[48,7],[31,20],[10,22],[-33,19],[-48,9]],
    service: outline([-50,-13],[
      [-50,-20,-47,-22,-40,-22], [-16,-22,16,-22,40,-22], [47,-22,50,-19,50,-12],
      [50,-8,50,8,50,12], [50,20,47,22,40,22], [16,22,-16,22,-40,22],
      [-47,22,-50,19,-50,13], [-50,8,-50,-8,-50,-13],
    ]),
    followup: outline([-50,-14],[
      [-50,-25,50,-25,50,-14], [50,-6,50,7,50,14],
      [50,25,-50,25,-50,14], [-50,6,-50,-6,-50,-14],
    ]),
  };

  function contains(key, dx, dy, width) {
    const points = hulls[groupFor(key)];
    if (!points || !(width > 0)) return false;
    const x = dx * 100 / width;
    let inside = false;
    for (let i=0,j=points.length-1; i<points.length; j=i++) {
      const [ax,ay]=points[j], [bx,by]=points[i];
      const cross=(x-ax)*(by-ay) - (dy-ay)*(bx-ax);
      if (Math.abs(cross)<1e-5 && x >= Math.min(ax,bx) && x <= Math.max(ax,bx)
          && dy >= Math.min(ay,by) && dy <= Math.max(ay,by)) return true;
      if ((ay>dy)!==(by>dy) && x<(bx-ax)*(dy-ay)/(by-ay)+ax) inside=!inside;
    }
    return inside;
  }

  // A physical liquid line at all nodes is decorative. Counts and event
  // changes are rendered independently by the atlas from authoritative data.
  const crest = 'M-110 7 q7-3.5 15-.8 t15 .8 q7 2.8 14 .8 t14-.8'.concat(
    ' q7-3.5 15-.8 t15 .8 q7 2.8 14 .8 t14-.8'.repeat(3));
  const volume = crest+' V29 H-110 Z';
  const glass = {
    member: `<path d="M-47-2Q-45-15-29-18Q-36-15-41-4Z" fill="url(#glv-sheen)" opacity=".68"/>
      <path d="M-46-4Q-45-16-30-19Q-15-23 1-20M25 13Q38 9 44 6" fill="none" stroke="#ecfbff" stroke-opacity=".75" stroke-linecap="round"/>
      <path d="M-40 12Q-31 20-13 20" fill="none" stroke="currentColor" stroke-opacity=".70" stroke-width=".8"/> `,
    intake: `<path d="M-50-3-34-18-17-22 29-21 25-16-16-17-31-13-44-1Z" fill="#f3e9ff" opacity=".31"/>
      <path d="M30-21 50-9 43-6 25-16Z" fill="url(#glv-sheen)" opacity=".70"/>
      <path d="M50-9 48 7 40 5 43-6Z" fill="currentColor" opacity=".25"/>
      <path d="M48 7 31 20 10 22 15 16 40 5Z" fill="currentColor" opacity=".31"/>
      <path d="M10 22-33 19-48 9-40 6-28 14 15 16Z" fill="currentColor" opacity=".20"/>
      <path d="M-49-3-34-18-17-22 29-21M-49 8-34 18" stroke="#e9e5ff" stroke-width=".8" fill="none"/> `,
    service: `<path d="M-47-13Q-47-19-39-19H20M-46-5V9M43-8V7" stroke="#e7f9ff" opacity=".7" fill="none" stroke-linecap="round"/>
      <path d="M-43-13Q-42-16-36-16L-39 14-42 14Z" fill="#f9fcf2" opacity=".21"/>
      <path d="M37-13 40-15 39 13 36 15Z" fill="#f6fbff" opacity=".16"/>
      <path d="M-37 19H30" stroke="currentColor" stroke-opacity=".39" fill="none"/> `,
    followup: `<ellipse cy="-14" rx="49.3" ry="7.8" fill="url(#glv-cap)" stroke="#a1b8c9" stroke-width=".7"/>
      <ellipse cy="-14" rx="43" ry="5.2" fill="url(#glv-glass)" stroke="#b1c3cf" stroke-opacity=".56" stroke-width=".6"/>
      <path d="M-46-16Q-34-21-9-21M-46-7V12M-39 17Q-16 23 19 20M45-6V10" fill="none" stroke="#e7f8ff" stroke-opacity=".7" stroke-linecap="round" stroke-width=".8"/>
      <path d="M-42-8-38-7V15L-42 13ZM35-7 40-8V14L35 16Z" fill="url(#glv-sheen)" opacity=".48"/> `,
  };

  function defs() {
    const materials = Object.entries(groups).map(([name, palette]) => {
      const coordinates=hulls[name].map(p=>p.join(',')).join(' ');
      return `<polygon id="glv-hull-${name}" points="${coordinates}"/>
        <clipPath id="glv-inside-${name}"><use href="#glv-hull-${name}" transform="scale(.91 .82)"/></clipPath>
        <linearGradient id="glv-water-${name}" x1="0" y1="0" x2="1" y2=".56">
          <stop stop-color="${palette.deep}"/><stop offset=".14" stop-color="${palette.water}"/><stop offset=".24" stop-color="${palette.color}"/><stop offset=".43" stop-color="${palette.water}"/><stop offset=".74" stop-color="${palette.deep}"/><stop offset="1" stop-color="${palette.water}"/>
        </linearGradient>`;
    }).join('');
    return `<defs>${materials}
      <linearGradient id="glv-rim" x1="0" y1="0" x2=".85" y2="1"><stop stop-color="#e2f2fa"/><stop offset=".16" stop-color="#81949f"/><stop offset=".31" stop-color="#33434f"/><stop offset=".65" stop-color="#243442"/><stop offset=".91" stop-color="#8199a5"/><stop offset="1" stop-color="#3c5261"/></linearGradient>
      <linearGradient id="glv-glass" x1="0" y1="0" x2=".86" y2="1"><stop stop-color="#8096a5"/><stop offset=".14" stop-color="#405462"/><stop offset=".36" stop-color="#1b2b37"/><stop offset=".64" stop-color="#132431"/><stop offset=".89" stop-color="#293b49"/><stop offset="1" stop-color="#768996"/></linearGradient>
      <linearGradient id="glv-cap" x1="0" y1="0" x2=".72" y2="1"><stop stop-color="#aabecb"/><stop offset=".30" stop-color="#5c707d"/><stop offset=".75" stop-color="#263b49"/><stop offset="1" stop-color="#496377"/></linearGradient>
      <linearGradient id="glv-sheen"><stop stop-color="#f4fcff" stop-opacity=".12"/><stop offset=".35" stop-color="#f4fcff"/><stop offset="1" stop-color="#d9f7ff" stop-opacity=".05"/></linearGradient>
      <style>
        .glv-slosh { animation:glv-tide var(--glv-period) ease-in-out var(--glv-phase) infinite alternate; }
        .glv-bubble { opacity:0; animation:glv-rise 5.7s ease-in-out var(--glv-phase) infinite; }
        .glv-bubble:nth-child(2) { animation-delay:calc(var(--glv-phase) + .4s); }
        .glv-bubble:nth-child(3) { animation-delay:calc(var(--glv-phase) + .75s); }
        [data-station].is-flow-impact .glv-reaction { animation:glv-splash .38s ease-out; transform-origin:0 7px; }
        .glv-ripple { opacity:0; }
        [data-station].is-flow-impact .glv-ripple { animation:glv-ripple .38s ease-out; }
        .flow-paused .glv-slosh,.flow-paused .glv-bubble,.is-still .glv-slosh,.is-still .glv-bubble { animation-play-state:paused; }
        .flow-paused [data-station].is-flow-impact .glv-reaction,.flow-paused [data-station].is-flow-impact .glv-ripple,
        .is-still [data-station].is-flow-impact .glv-reaction,.is-still [data-station].is-flow-impact .glv-ripple { animation:none; }
        @keyframes glv-tide { from { transform:translateX(-8px); } to { transform:translateX(8px); } }
        @keyframes glv-rise { 0%,37% { transform:translateY(0); opacity:0; } 47% { opacity:.75; } 78% { opacity:.72; } 90%,100% { transform:translateY(-12px); opacity:0; } }
        @keyframes glv-splash { 0% { transform:rotate(0); } 25% { transform:rotate(2deg); } 56% { transform:rotate(-1.2deg); } 100% { transform:rotate(0); } }
        @keyframes glv-ripple { 0% { opacity:0; transform:scale(.16,.4); } 26% { opacity:.8; } 100% { opacity:0; transform:scale(1.35,1); } }
        @media(prefers-reduced-motion:reduce) { .glv-slosh,.glv-bubble,[data-station].is-flow-impact .glv-reaction,[data-station].is-flow-impact .glv-ripple { animation:none; } }
      </style></defs>`;
  }
  function shape(key, width, selected=false) {
    const name=groupFor(key);
    if (!name || !(width>0)) return '';
    const swatch=groups[name];
    const seed=Array.from(key).reduce((value,c)=>value+c.charCodeAt(0),0);
    const hull='glv-hull-'+name,inside='glv-inside-'+name,water='glv-liquid-'+key;
    return `<g aria-hidden="true" transform="scale(${width/100} 1)" color="${swatch.color}" style="--glv-period:${(3.1+seed%13/10).toFixed(1)}s;--glv-phase:-${(seed%55/10).toFixed(1)}s">
      <defs><clipPath id="${water}"><path class="glv-slosh" d="${volume}"/></clipPath></defs>
      <use href="#${hull}" transform="translate(0 2)" fill="#030b15" opacity=".8"/>
      <use href="#${hull}" class="flow-plate" fill="url(#glv-rim)" stroke="${selected?'#f0fbff':swatch.color}" stroke-width="${selected?1.5:.8}"/>
      <use href="#${hull}" transform="scale(.961 .90)" fill="url(#glv-glass)" stroke="#afc6d0" stroke-opacity=".41" stroke-width=".7"/>
      <g clip-path="url(#${inside})"><g class="glv-reaction">
        <g class="glv-slosh"><path d="${volume}" fill="url(#glv-water-${name})"/><path d="${crest}" fill="none" stroke="${swatch.color}" stroke-width="2.3"/><path d="${crest}" fill="none" stroke="${swatch.light}" stroke-width=".75"/></g>
        <g clip-path="url(#${water})" fill="${swatch.color}" fill-opacity=".24" stroke="${swatch.light}" stroke-width=".5">
          <circle class="glv-bubble" cx="-29" cy="17" r="1.15"/><circle class="glv-bubble" cx="27" cy="17" r=".85"/><circle class="glv-bubble" cx="-20" cy="17" r=".7"/>
        </g>
        <g style="transform:translateX(var(--glv-impact-x, 20px))"><g transform="translate(0 7)"><ellipse class="glv-ripple" rx="11" ry="2.1" fill="none" stroke="${swatch.light}" stroke-width=".8"/></g></g>
      </g></g>
      ${glass[name]}
    </g>`;
  }

  window.GreenLifeFlowVessels = {groups,groupFor,shape,contains,defs};
})();
