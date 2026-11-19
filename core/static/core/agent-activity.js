(() => {
  const root = document.querySelector('[data-activity-url]');
  if (!root) return;

  const channels = root.querySelector('[data-channels]');
  const events = root.querySelector('[data-events]');
  const status = root.querySelector('[data-sync]');
  const orbit = root.querySelector('[data-orbit]');
  const hub = orbit.querySelector('.gl-activity-hub');
  const wires = orbit.querySelector('.gl-activity-wires');
  const nodes = [...orbit.querySelectorAll('.gl-orbit-node')];
  const paths = new Map();
  const number = new Intl.NumberFormat('fa-IR-u-nu-latn');
  const clock = new Intl.DateTimeFormat('fa-IR-u-nu-latn', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Tehran',
  });
  const initial = JSON.parse(root.querySelector('#gl-activity-initial').textContent);
  let previous = new Set(initial.events.map(event => event.id));
  let lastSnapshot = JSON.stringify([initial.channels, initial.events]);
  let refreshing = false;
  let selected = '';
  let current = initial;

  const board = root.querySelector('#gl-cycle-board');
  const cycleDialog = root.querySelector('#gl-cycle-dialog');
  const expandCycle = board.querySelector('[data-expand-cycle]');
  const boardAnchor = document.createComment('cycle board position');
  board.before(boardAnchor);
  expandCycle.addEventListener('click', () => {
    if (cycleDialog.open) { cycleDialog.close(); return; }
    cycleDialog.append(board);
    cycleDialog.showModal();
    cycleDialog.scrollTop = 0;
    expandCycle.textContent = 'بستن نمای گسترده';
    expandCycle.setAttribute('aria-expanded','true');
    expandCycle.focus({preventScroll:true});
  });
  cycleDialog.addEventListener('close', () => {
    boardAnchor.after(board);
    expandCycle.textContent = 'نمای گستردهٔ چرخه';
    expandCycle.setAttribute('aria-expanded','false');
    expandCycle.focus({preventScroll:true});
  });

  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function channelCard(channel, active) {
    const card = element('article', '', 'gl-activity-node');
    card.dataset.channel = channel.id;
    card.dataset.tone = channel.tone;
    card.classList.toggle('is-recent', active);
    const title = element('div', '', 'gl-activity-node-title');
    const ring = element('span', '', 'gl-activity-ring');
    ring.setAttribute('aria-hidden', 'true');
    title.append(ring, element('h3', channel.name));
    card.append(title);
    if (channel.account) card.append(element('p', channel.account));
    card.append(element('p', channel.state, 'gl-activity-state'));
    if (channel.metric) {
      const metric = element('p', '', 'gl-activity-metric');
      metric.append(element('b', number.format(channel.count)), ' ' + channel.metric);
      card.append(metric);
    }
    if (active) window.setTimeout(() => card.classList.remove('is-recent'), 2800);
    return card;
  }

  function eventRow(event) {
    const row = element('li', '');
    row.dataset.family = family(event.channel);
    const stamp = element('time', clock.format(new Date(event.time)));
    stamp.dateTime = event.time;
    row.append(element('strong', event.label), element('small', event.name), stamp);
    return row;
  }

  function family(channel) {
    return channel.startsWith('wa-') ? 'whatsapp' : channel;
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let angle = 0, width = 0, height = 0, frame = 0, lastTime = 0;
  let visible = false, pointing = false, focused = false;
  let hubRadius = 0, nodeRadius = 0;

  function positionWires() {
    if (!width || !height) return;
    nodes.forEach((node, index) => {
      const theta = angle - Math.PI / 2 + index * 2 * Math.PI / nodes.length;
      const dx = Math.cos(theta) * Math.min(width * .34, width / 2 - 42);
      const dy = Math.sin(theta) * height * .35;
      const left = (width / 2 + dx) + 'px';
      const top = (height / 2 + dy) + 'px';
      const depth = 1 + .075 * Math.sin(theta);
      node.style.setProperty('--depth-scale', depth.toFixed(3));
      Object.assign(node.style, { left, top });
      // End each conduit at the glass surface so packets and flashes meet the rim.
      const distance = Math.hypot(dx, dy);
      const fraction = 1 - nodeRadius * depth / distance;
      Object.assign(paths.get(node.dataset.family).style, {
        left: (width / 2 + dx * fraction) + 'px',
        top: (height / 2 + dy * fraction) + 'px',
        width: Math.max(0, distance - nodeRadius * depth - hubRadius) + 'px',
        transform: 'rotate(' + Math.atan2(-dy, -dx) + 'rad)',
      });
    });
  }

  function orbitFrame(time) {
    if (lastTime) angle += Math.min(time - lastTime, 100) * 2 * Math.PI / 56000;
    lastTime = time;
    positionWires();
    frame = requestAnimationFrame(orbitFrame);
  }

  function updateMotion() {
    cancelAnimationFrame(frame);
    lastTime = 0;
    if (visible && !document.hidden && !pointing && !focused && !reducedMotion.matches) {
      frame = requestAnimationFrame(orbitFrame);
    }
  }

  function render(snapshot, active = new Set()) {
    current = snapshot;
    const shown = item => !selected || family(item) === selected;
    const visible = snapshot.channels.filter(channel => shown(channel.id));
    const connected = visible.filter(channel => channel.tone === 'connected').length;
    root.querySelector('[data-connected-count]').textContent =
      number.format(connected) + ' از ' + number.format(visible.length) + ' حساب متصل';
    channels.replaceChildren(...visible
      .map(channel => channelCard(channel, active.has(channel.id))));
    const rows = snapshot.events.filter(event => shown(event.channel)).map(eventRow);
    if (!rows.length) rows.push(element('li', 'فعالیت تازه‌ای ثبت نشده است.', 'gl-activity-empty'));
    events.replaceChildren(...rows);

    for (const node of [hub, ...nodes]) {
      const key = node.dataset.family;
      node.setAttribute('aria-pressed', String(key === selected));
      node.dataset.active = String(snapshot.channels.some(channel =>
        family(channel.id) === key && channel.tone === 'connected'
      ));
    }
    for (const key of new Set([...active].map(family))) {
      const path = paths.get(key);
      if (!path) continue;
      path.classList.remove('is-recent');
      // Restart the animation when the same channel receives another message.
      void path.offsetWidth;
      path.classList.add('is-recent');
      window.clearTimeout(path.activityTimeout);
      path.activityTimeout = window.setTimeout(() => path.classList.remove('is-recent'), 2800);
    }
  }

  function syncText(snapshot) {
    status.dataset.state = 'live';
    status.textContent = 'آخرین به‌روزرسانی ' + clock.format(new Date(snapshot.updated_at));
  }

  let targetsCheckedAt = Date.now();
  let previousTargetMarkup = '';

  function updateTargets(markup) {
    targetsCheckedAt = Date.now();
    if (markup === previousTargetMarkup) return;
    const currentSection = board.querySelector('#gl-targets');
    const nextSection = new DOMParser().parseFromString(markup,'text/html').querySelector('#gl-targets');
    if (!currentSection || !nextSection) return;
    previousTargetMarkup = markup;

    const departmentNodes = new Map([...currentSection.querySelectorAll('[data-target-department]')]
      .map(item => [item.id,item]));
    for (const department of nextSection.querySelectorAll('[data-target-department]')) {
      const previousDepartment = departmentNodes.get(department.id);
      if (!previousDepartment) continue;
      const previousCards = new Map([...previousDepartment.querySelectorAll('[data-target-key]')]
        .map(item => [item.dataset.targetKey,item]));
      for (const card of department.querySelectorAll('[data-target-key]')) {
        const oldCard = previousCards.get(card.dataset.targetKey);
        if (oldCard && oldCard.dataset.targetReading !== card.dataset.targetReading) card.classList.add('is-updated');
      }
    }

    const focusedDepartment = document.activeElement?.closest('[data-target-department]')?.id;
    const offsets = [...departmentNodes].map(([id,node]) => [id,node.querySelector('.gl-target-vessels').scrollLeft]);
    currentSection.replaceWith(nextSection);
    for (const [id,offset] of offsets) {
      const row = document.getElementById(id)?.querySelector('.gl-target-vessels');
      if (!row) continue;
      row.scrollLeft = offset;
      if (id === focusedDepartment) row.focus({preventScroll:true});
    }
  }

  async function refresh() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    try {
      const url = new URL(root.dataset.activityUrl,document.baseURI);
      if (Date.now()-targetsCheckedAt >= 60000) url.searchParams.set('targets','1');
      const response = await fetch(url, {
        cache: 'no-store', headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(8000),
      });
      if (!response.ok || response.redirected) throw new Error('Snapshot unavailable');
      const snapshot = await response.json();
      const serialized = JSON.stringify([snapshot.channels, snapshot.events]);
      if (serialized !== lastSnapshot) {
        const active = new Set(snapshot.events.filter(event => !previous.has(event.id)).map(event => event.channel));
        render(snapshot, active);
        previous = new Set(snapshot.events.map(event => event.id));
        lastSnapshot = serialized;
      }
      root.dispatchEvent(new CustomEvent('flowupdate', { detail: snapshot.flow }));
      if (typeof snapshot.target_html === 'string') updateTargets(snapshot.target_html);
      syncText(snapshot);
    } catch {
      status.dataset.state = 'stale';
      status.textContent = 'به‌روزرسانی قطع شده؛ آخرین دادهٔ دریافت‌شده نمایش داده می‌شود.';
    } finally {
      refreshing = false;
    }
  }

  for (const node of nodes) {
    const wire = element('div', '', 'gl-activity-wire');
    wire.style.setProperty('--wire-color', getComputedStyle(node).getPropertyValue('--node-color'));
    wire.append(element('span', '', 'gl-wire-packet'));
    wires.append(wire);
    paths.set(node.dataset.family, wire);
  }
  orbit.addEventListener('click', event => {
    const button = event.target.closest('[data-family]');
    if (!button) return;
    selected = selected === button.dataset.family ? '' : button.dataset.family;
    render(current);
  });
  new ResizeObserver(() => {
    hubRadius = hub.offsetWidth / 2;
    nodeRadius = nodes[0].offsetWidth / 2;
    width = orbit.clientWidth;
    height = orbit.clientHeight;
    positionWires();
  }).observe(orbit);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    updateMotion();
  }).observe(orbit);
  orbit.addEventListener('pointerover', e => {
    pointing = e.pointerType === 'mouse' && Boolean(e.target.closest('button'));
    updateMotion();
  });
  orbit.addEventListener('pointerleave', () => { pointing = false; updateMotion(); });
  orbit.addEventListener('focusin', () => { focused = true; updateMotion(); });
  orbit.addEventListener('focusout', e => { focused = orbit.contains(e.relatedTarget); updateMotion(); });
  reducedMotion.addEventListener('change', updateMotion);
  document.addEventListener('visibilitychange', updateMotion);
  render(initial);
  syncText(initial);
  window.setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', refresh);
})();
