(() => {
  'use strict';

  const columnWidth = 380;
  const columnHeight = 637;
  const mix = ([x,y], [u,v], t) => [x + (u-x)*t, y + (v-y)*t];
  const distance = ([x,y], [u,v]) => Math.hypot(u-x, v-y);

  // Cut the corners of the routing rails into short quadratic arcs. The same
  // polyline drives both the visible glass conduit and its constant-speed packet.
  function roundedTrack(waypoints) {
    const points = [waypoints[0]];
    for (let i=1; i<waypoints.length-1; i++) {
      const prev = waypoints[i-1], corner = waypoints[i], next = waypoints[i+1];
      const incoming = distance(corner, prev), outgoing = distance(corner, next);
      if (!incoming || !outgoing) continue;
      const radius = Math.min(16, incoming/2, outgoing/2);
      const entry = mix(corner, prev, radius/incoming);
      const exit = mix(corner, next, radius/outgoing);
      points.push(entry);
      for (let j=1; j<=8; j++) {
        const t = j/8;
        points.push(mix(mix(entry,corner,t), mix(corner,exit,t), t));
      }
    }
    points.push(waypoints[waypoints.length-1]);
    const lengths = [0];
    for (let i=1; i<points.length; i++) {
      lengths.push(lengths[i-1] + distance(points[i-1], points[i]));
    }
    return {
      d: points.map(([x,y], i) => (i ? 'L' : 'M') + x.toFixed(2) + ' ' + y.toFixed(2)).join(' '),
      point(t) {
        if (t <= 0) return points[0];
        if (t >= 1) return points[points.length-1];
        const offset = t * lengths[lengths.length-1];
        const i = lengths.findIndex(length => length >= offset);
        return mix(points[i-1], points[i], (offset-lengths[i-1])/(lengths[i]-lengths[i-1]));
      },
    };
  }

  function addPath(graph, key, from, to, bends) {
    graph.paths[key] = {
      from, to,
      ...roundedTrack([graph.positions[from], ...bends, graph.positions[to]]),
    };
  }

  function addStream(graph, nodes, edges, ox, oy) {
    const shift = ([x,y]) => [x+ox, y+oy];
    for (const [key, position] of Object.entries(nodes)) graph.positions[key] = shift(position);
    for (const [from, to, bends] of edges) {
      // In the overview each event is named after its non-CRM station.
      addPath(graph, to==='crm' ? from : to, from, to, bends.map(shift));
    }
  }

  function overview(narrow) {
    const mx = narrow ? 0 : columnWidth;
    const ly = narrow ? columnHeight : 0;
    const graph = {
      width: narrow ? columnWidth : columnWidth*2,
      height: narrow ? columnHeight*2 : columnHeight,
      positions: {}, paths: {},
      titles: [
        {x:mx+columnWidth/2,y:27,text:'مسیر اعضا',group:'member'},
        {x:columnWidth/2,y:ly+27,text:'مسیر جذب لید',group:'intake'},
      ],
      separator: narrow ? 'M 15 636 H 365' : 'M 380 18 V 616',
    };
    addStream(graph, {
      me:[175,91], account:[73,247], sync:[285,220], request:[169,379], booked:[239,540],
    }, [
      ['me','account',[[128,77],[73,77]]],
      ['me','sync',[[221,87],[285,87]]],
      ['me','request',[[107,115],[107,186],[169,186]]],
      ['request','booked',[[239,379]]],
    ], mx, 0);
    addStream(graph, {
      website:[63,93], instagram:[244,84], school:[139,234], other:[315,249],
      crm:[176,397], assigned:[98,545],
    }, [
      ['website','crm',[[17,93],[17,385],[115,385]]],
      ['instagram','crm',[[193,84],[193,335]]],
      ['school','crm',[[78,234],[78,363],[119,363]]],
      ['other','crm',[[246,249],[246,396]]],
      ['crm','assigned',[[98,412]]],
    ], 0, ly);
    return graph;
  }

  const roomKeys = {
    members:['account','sync','request','diet','device','network'],
    leads:['lead_new','lead_contacted','lead_appointment','lead_visited','lead_won','lead_lost'],
  };

  function room(view, narrow) {
    const members = view === 'members';
    const hub = members ? 'me' : 'crm';
    const graph = {
      width: narrow ? 380 : 760, height: narrow ? 636 : 479,
      positions: {}, paths: {},
      titles: [{x:narrow ? 190 : 380,y:26,group:members ? 'member' : 'followup',
        text:members ? 'داخل گرین‌لایف ME' : 'وضعیت فعلی لیدهای ثبت‌شدهٔ امروز'}],
    };
    // Each descendant has its own lane. The right-of-hub aisle on phones
    // stays outside the hub's caption, and between both columns of captions.
    const nodes = narrow ? [
      [287,188], [68,218], [96,365], [304,336], [66,510], [280,542],
    ] : [
      [94,213], [429,216], [635,194], [176,372], [359,388], [598,352],
    ];
    graph.positions[hub] = narrow ? [113,86] : [328,84];
    const routes = narrow ? [
      [[252,80],[287,80]],
      [[68,87]],
      [[182,94],[182,365]],
      [[214,81],[214,336]],
      [[190,88],[190,510]],
      [[204,87],[204,542]],
    ] : [
      [[263,68],[94,68]],
      [[382,89],[429,89]],
      [[384,64],[635,64]],
      [[260,92],[176,92]],
      [[249,101],[249,181],[339,181],[339,312],[359,312]],
      [[392,76],[521,76],[521,352]],
    ];
    roomKeys[view].forEach((key,i) => {
      graph.positions[key] = nodes[i];
      addPath(graph, key, hub, key, routes[i]);
    });
    return graph;
  }

  // Geometry depends on just the selected room and its width breakpoint.
  // Polling counts and changing selection reuse the same rails and anchors.
  const scenes = new Map();
  function layout(view, narrow) {
    const key = view + (narrow ? '/narrow' : '/wide');
    if (!scenes.has(key)) {
      scenes.set(key, view === 'members' || view === 'leads' ? room(view,narrow) : overview(narrow));
    }
    return scenes.get(key);
  }

  window.GreenLifeFlowLayout = {layout};
})();
