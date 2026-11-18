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
  const number = new Intl.NumberFormat('fa-IR');
  const clock = new Intl.DateTimeFormat('fa-IR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Tehran',
  });
  const initial = JSON.parse(root.querySelector('#gl-activity-initial').textContent);
  let previous = new Set(initial.events.map(event => event.id));
  let lastSnapshot = JSON.stringify([initial.channels, initial.events]);
  let refreshing = false;
  let selected = '';
  let current = initial;

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

  function positionWires() {
    const bounds = orbit.getBoundingClientRect();
    const center = hub.getBoundingClientRect();
    const endX = center.left + center.width / 2;
    const endY = center.top + center.height / 2;

    for (const node of nodes) {
      const contact = node.getBoundingClientRect();
      const x = contact.left + contact.width / 2;
      const y = contact.top + contact.height / 2;
      const dx = endX - x;
      const dy = endY - y;
      const wire = paths.get(node.dataset.family);
      Object.assign(wire.style, {
        left: (x - bounds.left) + 'px',
        top: (y - bounds.top) + 'px',
        width: Math.hypot(dx, dy) + 'px',
        transform: 'rotate(' + Math.atan2(dy, dx) + 'rad)',
      });
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
    if (!active.size) return;
    const activityPaths = [hub, ...[...new Set([...active].map(family))]
      .map(key => paths.get(key)).filter(Boolean)];
    for (const path of activityPaths) {
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

  async function refresh() {
    if (document.hidden || refreshing) return;
    refreshing = true;
    try {
      const response = await fetch(root.dataset.activityUrl, {
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
    wires.append(wire);
    paths.set(node.dataset.family, wire);
  }
  orbit.addEventListener('click', event => {
    const button = event.target.closest('[data-family]');
    if (!button) return;
    selected = selected === button.dataset.family ? '' : button.dataset.family;
    render(current);
  });
  new ResizeObserver(positionWires).observe(orbit);
  positionWires();
  render(initial);
  syncText(initial);
  window.setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', refresh);
})();
