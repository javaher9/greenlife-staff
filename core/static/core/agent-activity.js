(() => {
  const root = document.querySelector('[data-activity-url]');
  if (!root) return;

  const channels = root.querySelector('[data-channels]');
  const events = root.querySelector('[data-events]');
  const status = root.querySelector('[data-sync]');
  const number = new Intl.NumberFormat('fa-IR');
  const clock = new Intl.DateTimeFormat('fa-IR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Tehran',
  });
  const initial = JSON.parse(root.querySelector('#gl-activity-initial').textContent);
  let previous = new Set(initial.events.map(event => event.id));
  let lastSnapshot = JSON.stringify([initial.channels, initial.events]);
  let refreshing = false;

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
    const stamp = element('time', clock.format(new Date(event.time)));
    stamp.dateTime = event.time;
    row.append(element('strong', event.label), element('small', event.name), stamp);
    return row;
  }

  function render(snapshot, active = new Set()) {
    channels.replaceChildren(...snapshot.channels.map(channel => channelCard(channel, active.has(channel.id))));
    const rows = snapshot.events.map(eventRow);
    if (!rows.length) rows.push(element('li', 'فعالیت تازه‌ای ثبت نشده است.', 'gl-activity-empty'));
    events.replaceChildren(...rows);
  }

  function syncText(snapshot) {
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
      syncText(snapshot);
    } catch {
      status.textContent = 'به‌روزرسانی قطع شده؛ آخرین دادهٔ دریافت‌شده نمایش داده می‌شود.';
    } finally {
      refreshing = false;
    }
  }

  render(initial);
  syncText(initial);
  window.setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', refresh);
})();
