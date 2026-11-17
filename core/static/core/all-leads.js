(() => {
  'use strict';
  const root = document.getElementById('all-leads');
  if (!root) return;
  const form = document.getElementById('al-filters'), grid = document.getElementById('al-grid');
  const scroll = document.getElementById('al-scroll'), message = document.getElementById('al-message');
  const more = document.getElementById('al-more'), total = document.getElementById('al-total');
  const before = document.getElementById('al-before'), after = document.getElementById('al-after');
  let items = [], cursor = null, done = false, busy = false, controller, generation = 0, timer, frame;
  const rowHeight = 90;
  let renderedWindow = null;
  const initial = new URLSearchParams(location.search);
  for (const [key,value] of initial) {
    const el = form.elements.namedItem(key);
    if (el) { if (el.type === 'checkbox') el.checked = value === '1'; else el.value = value; }
  }
  function params() { return new URLSearchParams(new FormData(form)); }
  function span(className, text) { const el = document.createElement('span'); el.className = className; el.textContent = text; return el; }
  function draw() {
    const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
    const startRow = Math.max(0, Math.floor(scroll.scrollTop / rowHeight) - 3);
    const start = Math.min(items.length, startRow * columns);
    const end = Math.min(items.length, start + (Math.ceil(scroll.clientHeight / rowHeight) + 7) * columns);
    const windowKey = `${generation}:${start}:${end}:${columns}:${items.length}`;
    if (windowKey === renderedWindow) return;
    renderedWindow = windowKey;
    const fragment = document.createDocumentFragment();
    items.slice(start, end).forEach(item => {
      const link = document.createElement('button'); link.type = 'button'; link.className = 'al-plaque';
      link.dataset.callPlaqueUrl = item.plaque_url;
      link.dataset.leadName = item.name;
      link.setAttribute('aria-label', `${item.name}، ${item.flower}، ${item.label}؛ پلاک تماس و سوابق`);
      const head = span('al-plaque-head', ''), meta = span('al-plaque-meta', '');
      const name = span('al-name', item.name); name.title = item.name;
      const flower = span('al-flower', item.flower); flower.title = item.flower;
      const status = span('al-state', item.label); status.dataset.state = item.state;
      const r = item.readiness || {}, score = span('cp-readiness', '');
      score.dataset.callScoreFor = item.id; score.dataset.band = r.do_not_contact ? 'blocked' : (r.band || 'unknown');
      score.title = 'امتیاز آمادگی؛ درصد احتمال خرید نیست';
      const label = span('', r.do_not_contact ? 'عدم تماس' : (r.label || 'اطلاعات ناکافی')); label.dataset.callScoreLabel = '';
      const number = document.createElement('b'); number.dataset.callScoreNumber = ''; number.textContent = r.score == null ? '—' : `${r.score} / 100`;
      const track = span('cp-readiness-track', ''); track.setAttribute('aria-hidden', 'true');
      const fill = document.createElement('i'); fill.dataset.callScoreFill = ''; fill.style.width = `${r.score == null ? 0 : Math.max(0, Math.min(100, r.score))}%`;
      track.append(fill); score.append(label, number, track);
      head.append(name, flower); meta.append(span('al-date', item.date), status); link.append(head, meta, score); fragment.append(link);
    });
    before.style.height = `${Math.floor(start / columns) * rowHeight}px`;
    after.style.height = `${Math.max(0, Math.ceil(items.length / columns) - Math.ceil(end / columns)) * rowHeight}px`;
    grid.replaceChildren(fragment);
  }
  async function load() {
    if (busy || done) return;
    busy = true; more.disabled = true; message.textContent = 'در حال دریافت لیدها…';
    const current = generation, query = params(); if (cursor) query.set('cursor', cursor);
    controller = new AbortController();
    try {
      const response = await fetch(`${root.dataset.endpoint}?${query}`, {signal:controller.signal, credentials:'same-origin', headers:{Accept:'application/json'}});
      if (response.redirected) throw new Error('نشست شما پایان یافته؛ صفحه را دوباره باز کنید.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'دریافت لیدها ممکن نشد. دوباره تلاش کنید.');
      if (current !== generation) return;
      items.push(...data.items); cursor = data.next; done = !cursor;
      if (data.total !== null) total.textContent = `${data.total.toLocaleString('fa-IR')} لید`;
      draw(); message.textContent = items.length ? `${items.length.toLocaleString('fa-IR')} لید دریافت شد${done ? ' · پایان فهرست' : ' · برای ادامه اسکرول کنید'}` : 'لیدی با این فیلترها پیدا نشد.';
      more.hidden = done;
    } catch (error) {
      if (error.name !== 'AbortError' && current === generation) { message.textContent = error.message || 'خطای ارتباط؛ دوباره تلاش کنید.'; more.hidden = false; more.textContent = 'تلاش دوباره'; }
    } finally { if (current === generation) { busy = false; more.disabled = false; } }
  }
  function reload() {
    clearTimeout(timer); generation++; if (controller) controller.abort();
    items = []; cursor = null; done = false; busy = false; scroll.scrollTop = 0; total.textContent = '';
    more.hidden = false; more.textContent = 'دریافت ادامه'; draw();
    history.replaceState(null, '', `${location.pathname}?${params()}`); load();
  }
  form.addEventListener('submit', event => {event.preventDefault(); reload();});
  form.addEventListener('change', reload);
  form.addEventListener('input', event => { if (event.target.matches('input:not([type=checkbox])')) {clearTimeout(timer); timer = setTimeout(reload, 400);} });
  form.addEventListener('reset', () => setTimeout(reload, 0));
  document.getElementById('al-refresh').addEventListener('click', reload);
  document.getElementById('al-all-dates').addEventListener('click', () => {form.elements.namedItem('from').value = ''; form.elements.namedItem('to').value = ''; reload();});
  more.addEventListener('click', load);
  scroll.addEventListener('scroll', () => {
    cancelAnimationFrame(frame); frame = requestAnimationFrame(() => {draw(); if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 500) load();});
  }, {passive:true});
  new ResizeObserver(draw).observe(scroll);
  document.addEventListener('call-plaque-saved', event => {
    if (!event.detail || event.detail.action !== 'finalize') return;
    const item = items.find(row => String(row.id) === String(event.detail.leadId));
    if (item) { item.readiness = {...event.detail.profile.readiness, do_not_contact:event.detail.profile.do_not_contact}; renderedWindow = null; draw(); }
  });
  reload();
})();
