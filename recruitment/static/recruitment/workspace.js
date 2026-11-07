(function () {
  'use strict';
  const root = document.getElementById('recruitment-workspace');
  if (!root) return;
  const apiRoot = root.dataset.apiRoot;
  const content = root.querySelector('#rh-content');
  const dialog = root.querySelector('#rh-dialog');
  const dialogBody = root.querySelector('#rh-dialog-body');
  const selected = new Set();
  let state = {jobs: [], applications: [], ads: [], staff: [], branches: [], countries: [], choices: {}, stats: {}};
  let tab = 'jobs';
  let quick = '';
  let page = 1;
  let searchTimer;
  let detail = null;
  let detailTab = 'overview';
  let restoreFocus = null;
  let requestVersion = 0;
  let dialogVersion = 0;
  const filters = {q: 'rh-search', organization: 'rh-organization', job: 'rh-job', stage: 'rh-stage', owner: 'rh-owner', source: 'rh-source'};
  const tabInfo = {
    jobs: ['موقعیت‌های شغلی', 'نیاز، بودجه و معیار انتخاب هر موقعیت را مشخص کنید.'],
    applications: ['متقاضیان', 'پرونده‌ها را بررسی کنید؛ هر متقاضی می‌تواند برای چند موقعیت درخواست داشته باشد.'],
    followups: ['مصاحبه و پیگیری', 'هر پروندهٔ فعال، یک مسئول و یک اقدام بعدی دارد. زمان‌ها به وقت تهران هستند.'],
    ads: ['آگهی‌ها و منابع جذب', 'متن، منبع، هزینه و نتیجهٔ انتشار هر آگهی را در یک جا ثبت کنید.'],
    onboarding: ['شروع همکاری', 'پیشنهاد همکاری، شروع کار و نتیجهٔ دورهٔ آزمایشی را دنبال کنید.'],
    talent: ['بانک استعدادها', 'افراد مناسب برای فرصت‌های آینده، با دلیل ذخیره و زمان پیگیری مشخص.']
  };
  const emptyInfo = {
    jobs: ['◇', 'اولین موقعیت شغلی را تعریف کنید', 'عنوان شغل، محل کار، بودجه و معیارهای انتخاب را ثبت کنید تا پرونده‌های جذب منظم آغاز شوند.', 'create-job', 'درخواست جذب نیرو'],
    applications: ['♙', 'هنوز متقاضی ثبت نشده است', 'رزومه‌ها و تماس‌های استخدام را اینجا ثبت کنید و رسیدگی را به یک مسئول بسپارید.', 'create-application', 'افزودن متقاضی'],
    followups: ['◷', 'فعلاً پیگیری‌ای در این فهرست نیست', 'پس از ثبت متقاضی و تعیین اقدام بعدی، برنامهٔ پیگیری‌ها و مصاحبه‌ها اینجا نمایش داده می‌شود.'],
    ads: ['▤', 'آگهی‌های استخدام را منظم نگه دارید', 'برای هر موقعیت، متن آگهی و اطلاعات انتشار در دیوار، لینکدین یا منابع دیگر را ثبت کنید.', 'create-ad', 'ثبت آگهی'],
    onboarding: ['✓', 'شروع همکاری تازه‌ای ثبت نشده است', 'متقاضیان از مرحلهٔ پیشنهاد همکاری به بعد، برای پیگیری شروع کار و دورهٔ آزمایشی در این بخش دیده می‌شوند.'],
    talent: ['✦', 'بانک استعدادها آمادهٔ تکمیل است', 'در پروندهٔ افراد مناسب، مرحلهٔ «بانک استعدادها» را انتخاب و زمان پیگیری آینده را ثبت کنید.']
  };
  const esc = value => String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const n = value => new Intl.NumberFormat('en-US').format(Number(value || 0));
  const money = value => value === null || value === undefined || value === '' ? 'ثبت نشده' : n(value) + ' تومان';
  const choiceLabel = (key, value) => ((state.choices[key] || []).find(x => x.value === value) || {}).label || value || '—';
  const staffName = id => ((state.staff || []).find(x => String(x.id) === String(id)) || {}).name || 'تعیین نشده';
  const jobFor = id => state.jobs.find(j => String(j.id) === String(id));
  const faDate = (value, withTime) => {
    if (!value) return 'تعیین نشده';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return 'تعیین نشده';
    return new Intl.DateTimeFormat('fa-IR', {timeZone: 'Asia/Tehran', year: 'numeric', month: 'short', day: 'numeric', ...(withTime ? {hour: '2-digit', minute: '2-digit'} : {})}).format(d);
  };
  const localDateTime = value => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const parts = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Tehran', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(date);
    const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
  };
  const isToday = value => value && localDateTime(value).slice(0, 10) === localDateTime(new Date()).slice(0, 10);
  const isOverdue = a => a.next_action_at && new Date(a.next_action_at) < new Date() && !['rejected', 'withdrawn', 'salary_declined', 'hired'].includes(a.stage);
  const badge = (label, color) => `<span class="rh-tag ${esc(color || '')}">${esc(label)}</span>`;
  const stageBadge = a => badge(a.stage_label || choiceLabel('stages', a.stage), a.review_required ? 'amber' : ['hired', 'accepted', 'started'].includes(a.stage) ? 'green' : ['rejected', 'withdrawn', 'salary_declined'].includes(a.stage) ? 'red' : a.stage === 'talent' ? 'purple' : '');
  function notice(message, error) {
    const element = root.querySelector('#rh-notice');
    element.textContent = message;
    element.hidden = !message;
    element.classList.toggle('is-error', !!error);
  }
  async function api(path, data) {
    const options = {credentials: 'same-origin', headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}};
    if (data) {
      options.method = 'POST';
      options.headers['X-CSRFToken'] = root.querySelector('[name=csrfmiddlewaretoken]').value;
      options.body = data;
    }
    const response = await fetch(apiRoot + path, options);
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) throw new Error(response.status === 403 ? 'دسترسی این عملیات را ندارید؛ صفحه را تازه‌سازی کنید.' : 'پاسخ معتبر دریافت نشد. اتصال یا وضعیت ورود خود را بررسی کنید.');
    const result = await response.json();
    if (!response.ok || result.ok === false) {
      const descriptions = Object.values(result.errors || {}).flat().map(String);
      throw new Error([result.error || 'ثبت اطلاعات انجام نشد.', ...descriptions].join('\n'));
    }
    return result;
  }
  function setOptions(id, items, first) {
    const select = root.querySelector('#' + id);
    const previous = select.value;
    select.innerHTML = `<option value="">${esc(first)}</option>` + items.map(x => `<option value="${esc(x.value === undefined ? x.id : x.value)}">${esc(x.label || x.name || x.title)}</option>`).join('');
    select.value = previous;
  }
  async function refresh(showLoading) {
    const version = ++requestVersion;
    if (showLoading) content.innerHTML = '<div class="rh-loading"><span class="rh-spinner"></span> در حال دریافت اطلاعات استخدام…</div>';
    content.setAttribute('aria-busy', 'true');
    try {
      const query = new URLSearchParams({...values(), page: String(page), view: tab, quick});
      const result = await api('?' + query.toString());
      if (version !== requestVersion) return;
      state = result;
      setOptions('rh-organization', state.choices.organizations || [], 'همهٔ مجموعه‌ها');
      setOptions('rh-job', state.jobs, 'همهٔ موقعیت‌ها');
      setOptions('rh-stage', state.choices.stages || [], 'همهٔ مراحل');
      setOptions('rh-owner', state.staff, 'همهٔ مسئولان');
      setOptions('rh-source', state.choices.sources || [], 'همهٔ منابع');
      const stats = {interviews_today: state.stats.interviews_today, overdue: state.stats.overdue, pending_review: Number(state.stats.needs_approval || 0) + Number(state.stats.pending_budgets || 0), new: state.stats.new_applications};
      root.querySelectorAll('[data-stat]').forEach(el => el.textContent = n(stats[el.dataset.stat]));
      root.querySelector('[data-count=jobs]').textContent = n(state.jobs.length);
      root.querySelector('[data-count=applications]').textContent = n(state.applications_total === undefined ? state.applications.length : state.applications_total);
      root.querySelector('#rh-updated').textContent = 'آخرین دریافت: ' + new Intl.DateTimeFormat('fa-IR', {timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit'}).format(new Date());
      render();
    } catch (error) {
      if (showLoading) content.innerHTML = '<div class="rh-empty"><div class="rh-empty-symbol">!</div><h3>دریافت اطلاعات انجام نشد</h3><p>اطلاعات ثبت‌شده محفوظ است. اتصال را بررسی و دوباره تلاش کنید.</p><button class="rh-btn" data-action="refresh" type="button">تلاش دوباره</button></div>';
      notice(error.message, true);
      throw error;
    } finally { content.setAttribute('aria-busy', 'false'); }
  }
  function values() { return Object.fromEntries(Object.entries(filters).map(([key, id]) => [key, root.querySelector('#' + id).value.trim()])); }
  function applicationRows() {
    const f = values();
    return state.applications.filter(a => {
      if (f.q && ![a.name, a.phone, a.job_title].join(' ').toLowerCase().includes(f.q.toLowerCase())) return false;
      if (Object.entries(f).some(([k, v]) => k !== 'q' && v && String(a[k]) !== v)) return false;
      if (tab === 'talent' && a.stage !== 'talent') return false;
      if (tab === 'onboarding' && !['offer', 'accepted', 'started', 'probation', 'hired'].includes(a.stage)) return false;
      if (tab === 'followups' && ['rejected', 'withdrawn', 'salary_declined', 'hired'].includes(a.stage)) return false;
      if (quick === 'today' && !isToday(a.interview_at)) return false;
      if (quick === 'overdue' && !isOverdue(a)) return false;
      if (quick === 'review' && !a.review_required) return false;
      if (quick === 'new' && a.stage !== 'new') return false;
      return true;
    });
  }
  function empty(filtered) {
    const e = filtered ? ['⌕', 'موردی با این فیلترها پیدا نشد', 'فیلترها یا عبارت جستجو را تغییر دهید.', 'clear', 'حذف فیلترها'] : emptyInfo[tab];
    return `<div class="rh-empty"><div class="rh-empty-symbol" aria-hidden="true">${e[0]}</div><h3>${esc(e[1])}</h3><p>${esc(e[2])}</p>${e[3] ? `<button type="button" class="rh-btn rh-primary" data-action="${e[3]}">${esc(e[4])}</button>` : ''}</div>`;
  }
  function renderJobs() {
    const f = values();
    const rows = state.jobs.filter(j => (!f.q || [j.title, j.location, j.description].join(' ').toLowerCase().includes(f.q.toLowerCase())) && (!f.organization || j.organization === f.organization) && (!f.job || String(j.id) === f.job) && (!f.owner || String(j.owner) === f.owner));
    if (!rows.length) return empty(!!(f.q || f.organization || f.job || f.owner));
    return `<div class="rh-job-grid">${rows.map(j => `<article class="rh-card"><div class="rh-card-top">${badge(j.organization_label || choiceLabel('organizations', j.organization))}${badge(j.status_label || choiceLabel('job_statuses', j.status), j.status === 'open' ? 'green' : '')}</div><button class="rh-card-title" type="button" data-action="edit-job" data-id="${j.id}">${esc(j.title)}</button><div class="rh-meta"><span>${esc(j.branch_name || j.location || j.country_name || 'محل کار ثبت نشده')}</span><span>·</span><span>${n(j.headcount)} نفر</span></div><p class="rh-card-desc">${esc(j.description || j.expected_outcomes || 'شرح کار و نتیجهٔ موردانتظار را در پروندهٔ این موقعیت کامل کنید.')}</p><div class="rh-card-line"><span>بودجهٔ حقوق</span><strong>${j.salary_min || j.salary_max ? `${n(j.salary_min)} تا ${n(j.salary_max)} تومان` : 'تعیین نشده'}</strong></div><div class="rh-card-line"><span>مسئول جذب</span><strong>${esc(j.owner_name || staffName(j.owner))}</strong></div><div class="rh-meta">${badge(j.budget_approved ? 'بودجه تأیید شده' : 'بودجه در انتظار تأیید', j.budget_approved ? 'green' : 'amber')}${j.requires_executive_approval ? badge('تأیید نهایی دکتر', 'purple') : ''}</div><div class="rh-card-bottom"><button type="button" class="rh-btn rh-small" data-action="job-applicants" data-id="${j.id}">${n(j.application_count)} متقاضی ←</button><button type="button" class="rh-btn rh-small rh-subtle" data-action="edit-job" data-id="${j.id}">جزئیات و ویرایش</button></div></article>`).join('')}</div>`;
  }
  function pendingBudgetCards() {
    if (quick !== 'review') return '';
    const f = values();
    const jobs = state.jobs.filter(j => !j.budget_approved && j.status !== 'closed' && (!f.organization || j.organization === f.organization) && (!f.job || String(j.id) === f.job) && (!f.owner || String(j.owner) === f.owner) && (!f.q || j.title.toLowerCase().includes(f.q.toLowerCase())));
    if (!jobs.length) return '';
    return `<section style="margin-bottom:22px"><h3 style="margin-bottom:13px">بودجه‌های منتظر تأیید</h3><div class="rh-job-grid">${jobs.map(j => `<article class="rh-card"><div class="rh-card-top">${badge('تأیید بودجه', 'amber')}${badge(j.organization_label || choiceLabel('organizations',j.organization))}</div><h3>${esc(j.title)}</h3><div class="rh-card-line"><span>حقوق ماهانه</span><strong>${money(j.salary_min)} تا ${money(j.salary_max)}</strong></div><div class="rh-card-bottom"><small>${esc(j.owner_name || staffName(j.owner))}</small><button type="button" class="rh-btn rh-small" data-action="edit-job" data-id="${j.id}">بررسی بودجه</button></div></article>`).join('')}</div></section>`;
  }
  function renderApplications(rows) {
    const budgets = pendingBudgetCards();
    if (!rows.length) return budgets || empty(Object.values(values()).some(Boolean) || !!quick);
    return budgets + `<div class="rh-table-wrap"><table class="rh-table"><thead><tr><th class="rh-check-cell">انتخاب</th><th>متقاضی</th><th>موقعیت و محل کار</th><th>مرحله</th><th>ارزیابی</th><th>مسئول / اقدام بعدی</th><th>منبع</th><th>پرونده</th></tr></thead><tbody>${rows.map(a => `<tr><td><input type="checkbox" data-compare="${a.id}" aria-label="انتخاب ${esc(a.name)} برای مقایسه" ${selected.has(a.id) ? 'checked' : ''}></td><td><div class="rh-person"><span class="rh-avatar" aria-hidden="true">${esc((a.name || 'م').trim().charAt(0))}</span><span><button type="button" data-action="open-application" data-id="${a.id}">${esc(a.name)}</button><small class="rh-ltr">${esc(a.phone)}</small></span></div></td><td>${esc(a.job_title)}<small>${esc(a.branch_name || choiceLabel('organizations', a.organization))}</small></td><td>${stageBadge(a)}${a.review_required ? '<small class="rh-overdue">در انتظار تصمیم</small>' : ''}</td><td>${a.score === null || a.score === undefined ? '—' : `<strong>${n(a.score)}</strong><small>از 100</small>`}<small>${n(a.evaluation_count)} ارزیابی</small></td><td>${esc(a.owner_name || staffName(a.owner))}<small class="${isOverdue(a) ? 'rh-overdue' : ''}">${esc(a.next_action || 'اقدام بعدی ثبت نشده')}</small><small>${esc(faDate(a.next_action_at, true))}</small></td><td>${esc(a.source_label || choiceLabel('sources', a.source))}</td><td><button type="button" class="rh-btn rh-small" data-action="open-application" data-id="${a.id}">بررسی پرونده</button></td></tr>`).join('')}</tbody></table></div><p class="rh-count-line">${n(rows.length)} پرونده · برای مقایسه، حداکثر سه متقاضی را انتخاب کنید.</p>`;
  }
  function renderFollowups(rows) {
    if (!rows.length) return empty(Object.values(values()).some(Boolean) || !!quick);
    const sorted = [...rows].sort((a, b) => new Date(a.next_action_at || '2099-01-01') - new Date(b.next_action_at || '2099-01-01'));
    return `<div class="rh-schedule-list">${sorted.map(a => `<article class="rh-schedule"><div class="rh-schedule-date">${esc(faDate(quick === 'today' ? a.interview_at : a.next_action_at, false))}<strong>${esc((quick === 'today' ? a.interview_at : a.next_action_at) ? new Intl.DateTimeFormat('fa-IR', {timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit'}).format(new Date(quick === 'today' ? a.interview_at : a.next_action_at)) : '—')}</strong></div><div class="rh-schedule-main"><h3>${esc(a.name)} <span class="rh-muted">· ${esc(a.job_title)}</span></h3><p>${esc(a.next_action || 'بررسی پرونده')}</p><div class="rh-meta"><span>مسئول: ${esc(a.owner_name || staffName(a.owner))}</span>${a.interview_at ? `<span>مصاحبه: ${esc(faDate(a.interview_at, true))}</span>` : ''}</div></div><div class="rh-schedule-actions">${isOverdue(a) ? badge('عقب‌افتاده', 'amber') : stageBadge(a)}<button type="button" class="rh-btn rh-small" data-action="open-followup" data-id="${a.id}">ثبت پیگیری</button></div></article>`).join('')}</div>`;
  }
  function renderAds() {
    const f = values();
    const rows = state.ads.filter(a => (!f.q || [a.title, a.body, a.job_title].join(' ').toLowerCase().includes(f.q.toLowerCase())) && (!f.job || String(a.job) === f.job) && (!f.source || a.source === f.source) && (!f.organization || (jobFor(a.job) || {}).organization === f.organization) && (!f.owner || String((jobFor(a.job) || {}).owner) === f.owner));
    if (!rows.length) return empty(Object.values(f).some(Boolean));
    return `<div class="rh-job-grid">${rows.map(a => `<article class="rh-card"><div class="rh-card-top">${badge(a.source_label || choiceLabel('sources', a.source))}${badge(a.status_label || choiceLabel('ad_statuses', a.status), a.status === 'active' ? 'green' : '')}</div><h3>${esc(a.title)}</h3><div class="rh-meta">${esc(a.job_title)}</div><p class="rh-card-desc">${esc(a.body)}</p><div class="rh-card-line"><span>هزینهٔ ثبت‌شده</span><strong>${money(a.cost)}</strong></div><div class="rh-card-line"><span>انقضا</span><strong>${esc(faDate(a.expires_at, false))}</strong></div><div class="rh-card-bottom"><button class="rh-btn rh-small" type="button" data-action="edit-ad" data-id="${a.id}">متن و جزئیات</button>${safeLink(a.url) ? `<a class="rh-btn rh-small rh-subtle" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">مشاهده آگهی ↗</a>` : '<small>لینک انتشار ثبت نشده</small>'}</div></article>`).join('')}</div>`;
  }
  function safeLink(value) { try { return ['https:', 'http:'].includes(new URL(value, location.origin).protocol) && /^https?:\/\//i.test(value); } catch (_) { return false; } }
  function render() {
    root.querySelectorAll('[data-tab]').forEach(el => { const active = el.dataset.tab === tab; el.classList.toggle('is-active', active); active ? el.setAttribute('aria-current', 'page') : el.removeAttribute('aria-current'); });
    root.querySelector('#rh-section-title').textContent = quick ? {today: 'مصاحبه‌های امروز', overdue: 'پیگیری‌های عقب‌افتاده', review: 'پرونده‌های نیازمند تصمیم', new: 'متقاضیان جدید'}[quick] : tabInfo[tab][0];
    root.querySelector('#rh-section-description').textContent = tabInfo[tab][1];
    root.querySelector('#rh-clear-filters').hidden = !Object.values(values()).some(Boolean) && !quick;
    const compare = root.querySelector('#rh-compare');
    compare.hidden = selected.size < 2 || tab === 'jobs' || tab === 'ads';
    compare.textContent = `مقایسهٔ ${n(selected.size)} متقاضی`;
    root.querySelector('#rh-stage').hidden = tab === 'jobs' || tab === 'ads';
    root.querySelector('#rh-source').hidden = tab === 'jobs';
    content.innerHTML = (tab === 'jobs' ? renderJobs() : tab === 'ads' ? renderAds() : tab === 'followups' ? renderFollowups(applicationRows()) : renderApplications(applicationRows())) + (!['jobs', 'ads'].includes(tab) ? pagination() : '');
  }
  function pagination() {
    const total = state.applications_total || 0;
    const size = state.page_size || 300;
    if (total <= size) return '';
    return `<div class="rh-pagination"><span>${n(total)} پرونده · صفحهٔ ${n(page)} از ${n(Math.ceil(total / size))}</span><div class="rh-inline-actions"><button type="button" class="rh-btn rh-small" data-action="previous-page" ${page <= 1 ? 'disabled' : ''}>صفحهٔ قبل</button><button type="button" class="rh-btn rh-small" data-action="next-page" ${page * size >= total ? 'disabled' : ''}>صفحهٔ بعد</button></div></div>`;
  }
  function queryRefresh() { page = 1; refresh(false).catch(() => {}); }
  function clearFilters() { Object.values(filters).forEach(id => root.querySelector('#' + id).value = ''); quick = ''; queryRefresh(); }
  function openDialog(title, html, eyebrow) {
    ++dialogVersion;
    root.querySelector('#rh-dialog-title').textContent = title;
    root.querySelector('#rh-dialog-eyebrow').textContent = eyebrow || 'مدیریت استخدام';
    dialogBody.innerHTML = html;
    if (!dialog.open) { restoreFocus = document.activeElement; dialog.showModal(); }
    dialog.scrollTop = 0;
    const focus = dialogBody.querySelector('input:not([type=hidden]),select,textarea,button');
    if (focus) focus.focus({preventScroll: true});
  }
  function closeDialog() { dialog.close(); ++dialogVersion; if (restoreFocus && restoreFocus.isConnected) restoreFocus.focus({preventScroll: true}); }
  function options(items, value, blank) { return (blank !== undefined ? `<option value="">${esc(blank)}</option>` : '') + items.map(x => { const val = x.value === undefined ? x.id : x.value; return `<option value="${esc(val)}" ${String(val) === String(value) ? 'selected' : ''}>${esc(x.label || x.name || x.title)}</option>`; }).join(''); }
  function input(name, label, value, type, required, hint, wide, extra) {
    return `<label class="rh-field ${wide ? 'rh-wide' : ''}"><span>${esc(label)}${required ? ' <b class="rh-required">*</b>' : ''}</span><input data-money-exempt="1" name="${esc(name)}" type="${type || 'text'}" value="${esc(value)}" ${required ? 'required' : ''} ${extra || ''}>${hint ? `<small>${esc(hint)}</small>` : ''}</label>`;
  }
  function textarea(name, label, value, required, hint, wide) { return `<label class="rh-field ${wide !== false ? 'rh-wide' : ''}"><span>${esc(label)}${required ? ' <b class="rh-required">*</b>' : ''}</span><textarea name="${esc(name)}" ${required ? 'required' : ''} maxlength="10000">${esc(value)}</textarea>${hint ? `<small>${esc(hint)}</small>` : ''}</label>`; }
  function select(name, label, items, value, required, blank, wide) { return `<label class="rh-field ${wide ? 'rh-wide' : ''}"><span>${esc(label)}${required ? ' <b class="rh-required">*</b>' : ''}</span><select name="${esc(name)}" ${required ? 'required' : ''}>${options(items, value, blank)}</select></label>`; }
  const formStart = (kind, id) => `<form data-form="${kind}" data-id="${id || ''}" autocomplete="off"><div class="rh-form-error" role="alert" hidden></div>${['update','approve','probation'].includes(kind) ? `<input type="hidden" name="expected_updated_at" value="${esc(detail.updated_at)}">` : ''}${kind === 'candidate_update' ? `<input type="hidden" name="expected_candidate_updated_at" value="${esc(detail.candidate.updated_at)}">` : ''}`;
  const formEnd = label => `<div class="rh-form-actions"><button type="button" class="rh-btn rh-subtle" data-action="close-dialog">بستن</button><button type="submit" class="rh-btn rh-primary">${esc(label || 'ذخیره اطلاعات')}</button></div></form>`;
  function criteriaRow(c) { return `<div class="rh-criterion-row"><input data-money-exempt="1" data-criterion-label aria-label="عنوان معیار" required maxlength="120" value="${esc(c.label)}"><input data-money-exempt="1" data-criterion-weight aria-label="وزن معیار از 100" type="number" min="1" max="100" required value="${esc(c.weight)}"><button type="button" class="rh-close" data-action="remove-criterion" aria-label="حذف معیار">×</button></div>`; }
  async function editJob(id) {
    openDialog('پروندهٔ موقعیت شغلی', '<div class="rh-loading"><span class="rh-spinner"></span>در حال دریافت پرونده…</div>');
    const version = dialogVersion;
    try {
      const result = await api(`jobs/${id}/`);
      if (!dialog.open || version !== dialogVersion) return;
      const index = state.jobs.findIndex(j => j.id === id);
      if (index >= 0) state.jobs[index] = result.job;
      jobForm(result.job);
    } catch (error) { if (version === dialogVersion) dialogBody.innerHTML = `<div class="rh-form-error" role="alert">${esc(error.message)}</div>`; }
  }
  function jobForm(job) {
    const j = job || {organization: 'clinic', headcount: 1, status: 'draft', owner: state.current_user_id, country: ((state.countries || []).find(c => c.code === 'IR') || state.countries[0] || {}).id};
    const criteria = j.criteria && j.criteria.length ? j.criteria : [{label: 'مهارت عملی مرتبط با شغل', weight: 40}, {label: 'تجربه و شواهد عملکرد', weight: 25}, {label: 'ارتباط و رفتار حرفه‌ای', weight: 20}, {label: 'دقت و پیگیری تکلیف', weight: 15}];
    let html = formStart('job', j.id) + `<input type="hidden" name="expected_updated_at" value="${esc(j.updated_at)}"><div class="rh-form-grid">`;
    html += input('title', 'عنوان موقعیت شغلی', j.title, 'text', true, 'مثلاً منشی نیاوران یا مسئول نگهداری کمپ', true, 'maxlength="160"');
    html += select('organization', 'مجموعه', state.choices.organizations || [], j.organization, true);
    html += select('country', 'کشور', state.countries, j.country, true, 'انتخاب کشور');
    html += select('branch', 'شعبه', state.branches, j.branch, false, 'بدون شعبه / پروژه مستقل');
    html += input('location', 'محل کار / پروژه', j.location, 'text', false, null, false, 'maxlength="200"');
    html += input('headcount', 'تعداد موردنیاز', j.headcount, 'number', true, null, false, 'min="1" max="100"');
    html += select('owner', 'مسئول جذب', state.staff, j.owner, true, 'انتخاب مسئول');
    html += input('shift', 'شیفت و زمان حضور', j.shift, 'text', false, null, false, 'maxlength="200"');
    html += input('target_date', 'تاریخ موردنیاز برای شروع (میلادی)', j.target_date, 'date');
    html += input('salary_min', 'حداقل حقوق ماهانه (تومان)', j.salary_min, 'number', false, null, false, 'min="0" step="1"');
    html += input('salary_max', 'سقف حقوق ماهانه (تومان)', j.salary_max, 'number', false, null, false, 'min="0" step="1"');
    html += textarea('benefits', 'مزایا و شرایط همکاری', j.benefits, false, 'مزایای نقدی و غیرنقدی را جدا از حقوق توضیح دهید.');
    html += textarea('description', 'شرح کار و علت نیاز', j.description, true);
    html += textarea('requirements', 'مهارت ضروری و موارد قابل آموزش', j.requirements, false);
    html += textarea('expected_outcomes', 'نتیجهٔ موردانتظار بعد از شروع کار', j.expected_outcomes, false);
    html += `<div class="rh-field rh-wide"><span>معیارهای ارزیابی <b class="rh-required">*</b></span><small>معیارها را پیش از ارزیابی افراد مشخص کنید. مجموع وزن‌ها باید 100 باشد.</small><div class="rh-criterion-labels"><span>معیار مرتبط با شغل</span><span>وزن از 100</span></div><div class="rh-criteria-input">${criteria.map(criteriaRow).join('')}</div><button type="button" class="rh-btn rh-small rh-subtle" data-action="add-criterion" style="margin-top:10px">＋ افزودن معیار</button></div>`;
    html += select('status', 'وضعیت موقعیت', state.choices.job_statuses || [], j.status, true);
    html += `<label class="rh-check-label"><input type="checkbox" name="requires_executive_approval" ${j.requires_executive_approval ? 'checked' : ''}>انتخاب نهایی این شغل به تأیید دکتر نیاز دارد</label></div>`;
    if (j.id) html += `<div class="rh-form-hint" style="margin-top:18px">${j.budget_approved ? 'بودجهٔ فعلی تأیید شده است. تغییر بودجه نیازمند تأیید دوباره است.' : 'بودجهٔ این موقعیت هنوز تأیید نشده است.'}${state.can_approve && !j.budget_approved ? `<button type="button" class="rh-btn rh-small rh-positive" data-action="approve-budget" data-id="${j.id}" style="margin-right:10px">تأیید بودجهٔ ذخیره‌شده</button>` : ''}</div>`;
    html += formEnd(j.id ? 'ذخیره تغییرات' : 'ثبت موقعیت شغلی');
    if (j.id) html += `<details class="rh-job-history" style="margin-top:22px"><summary>تاریخچهٔ موقعیت و بودجه</summary><div class="rh-timeline" style="margin-top:16px">${(j.activities || []).map(e => `<article class="rh-event"><strong>${esc(e.actor_name || 'سیستم')}</strong><small> · ${esc(faDate(e.created_at, true))}</small><p>${esc(e.text || 'اطلاعات به‌روز شد')}</p>${changeDetails(e.changes)}</article>`).join('') || '<p class="rh-muted">هنوز سابقه‌ای ثبت نشده است.</p>'}</div></details>`;
    openDialog(j.id ? 'پروندهٔ موقعیت شغلی' : 'درخواست جذب نیرو', html);
    filterBranches();
  }
  function filterBranches() {
    const country = dialogBody.querySelector('[name=country]');
    const branch = dialogBody.querySelector('[name=branch]');
    if (!country || !branch) return;
    const previous = branch.value;
    branch.innerHTML = options(state.branches.filter(b => !b.country || String(b.country) === country.value), previous, 'بدون شعبه / پروژه مستقل');
  }
  function applicationForm() {
    if (!state.jobs.length) { notice('ابتدا یک موقعیت شغلی تعریف کنید، سپس متقاضی آن را ثبت کنید.', true); jobForm(); return; }
    let html = formStart('application') + '<div class="rh-form-grid">';
    html += input('name', 'نام و نام خانوادگی', '', 'text', true, null, false, 'maxlength="160"');
    html += input('phone', 'شماره موبایل', '', 'tel', true, 'شماره‌های فارسی و انگلیسی پذیرفته می‌شوند.', false, 'maxlength="25" dir="ltr"');
    html += select('job', 'موقعیت شغلی', state.jobs.filter(j => !['closed', 'filled', 'archived'].includes(j.status)), root.querySelector('#rh-job').value, true, 'انتخاب موقعیت');
    html += select('owner', 'مسئول رسیدگی', state.staff, state.current_user_id, true, 'انتخاب مسئول');
    html += input('city', 'شهر محل سکونت', '', 'text', false, null, false, 'maxlength="100"');
    html += input('email', 'ایمیل', '', 'email', false, null, false, 'maxlength="254" dir="ltr"');
    html += select('source', 'منبع آشنایی', state.choices.sources || [], 'manual', true);
    html += input('source_detail', 'جزئیات منبع / نام معرف', '', 'text', false, null, false, 'maxlength="300"');
    html += input('requested_salary', 'حقوق درخواستی (تومان)', '', 'number', false, null, false, 'min="0" step="1"');
    html += '<label class="rh-field"><span>فایل رزومه</span><input type="file" name="resume" accept="application/pdf,.pdf"><small>PDF تا 5 مگابایت؛ دسترسی فقط برای مسئولان مجاز استخدام.</small></label>';
    html += textarea('resume_text', 'سوابق، مهارت‌ها و شرایط همکاری', '', false, 'برای افراد بدون رزومه، خلاصهٔ سوابق را اینجا بنویسید.');
    html += input('next_action', 'اقدام بعدی', 'تماس اولیه و بررسی شرایط همکاری', 'text', true, null, false, 'maxlength="300"');
    html += input('next_action_at', 'موعد پیگیری (وقت تهران)', localDateTime(new Date(Date.now() + 86400000)), 'datetime-local', true, 'تاریخ در ورودی به میلادی است؛ نمایش فهرست شمسی است.');
    html += textarea('notes', 'یادداشت اولیه', '', false);
    html += '</div>' + formEnd('ثبت متقاضی');
    openDialog('افزودن متقاضی', html);
  }
  function adForm(ad) {
    if (!state.jobs.length) { notice('برای ثبت آگهی، ابتدا موقعیت شغلی را تعریف کنید.', true); jobForm(); return; }
    const a = ad || {status: 'draft', source: 'divar'};
    let html = formStart('ad', a.id) + '<div class="rh-form-hint">این بخش سابقهٔ آگهی را ثبت می‌کند. انتشار خودکار در پلتفرم‌ها هنوز فعال نشده است.</div><div class="rh-form-grid">';
    html += select('job', 'موقعیت شغلی', state.jobs, a.job, true, 'انتخاب موقعیت');
    html += select('source', 'پلتفرم / منبع', state.choices.sources || [], a.source, true);
    html += input('title', 'عنوان آگهی', a.title, 'text', true, null, true, 'maxlength="200"');
    html += textarea('body', 'متن آگهی', a.body, true);
    html += select('status', 'وضعیت انتشار', state.choices.ad_statuses || [], a.status, true);
    html += input('cost', 'هزینهٔ ثبت‌شده (تومان)', a.cost, 'number', false, null, false, 'min="0" step="1"');
    html += input('url', 'لینک واقعی آگهی', a.url, 'url', false, 'برای وضعیت «فعال» ثبت لینک الزامی است.', true, 'maxlength="500" dir="ltr"');
    html += input('external_id', 'شناسهٔ آگهی در پلتفرم', a.external_id, 'text', false, null, false, 'maxlength="120"');
    html += input('expires_at', 'تاریخ انقضا (میلادی)', a.expires_at ? a.expires_at.slice(0, 10) : '', 'date');
    html += '</div>' + formEnd(a.id ? 'ذخیره تغییرات آگهی' : 'ثبت آگهی');
    openDialog(a.id ? 'جزئیات آگهی' : 'ثبت آگهی استخدام', html);
  }
  async function openApplication(id, initialTab) {
    detailTab = initialTab || 'overview';
    openDialog('پروندهٔ متقاضی', '<div class="rh-loading"><span class="rh-spinner"></span>در حال دریافت پرونده…</div>');
    const version = dialogVersion;
    try { const result = await api(`applications/${id}/`); if (dialog.open && dialogVersion === version) { detail = result.application; renderDetail(); } }
    catch (e) { if (dialog.open && dialogVersion === version) dialogBody.innerHTML = `<div class="rh-form-error" role="alert">${esc(e.message)}</div>`; }
  }
  function detailHeader(a) {
    return `<div class="rh-detail-top"><div class="rh-detail-person"><span class="rh-avatar">${esc((a.name || a.candidate.name || 'م').charAt(0))}</span><div><h3>${esc(a.name || a.candidate.name)}</h3><div class="rh-meta"><span>${esc(a.job_title)}</span><span class="rh-ltr">${esc(a.phone || a.candidate.phone)}</span></div></div></div><div class="rh-inline-actions">${stageBadge(a)}${a.review_required ? badge('نیازمند تصمیم', 'amber') : ''}</div></div><div class="rh-detail-tabs" aria-label="بخش‌های پرونده">${[['overview', 'خلاصه و رزومه'], ['followup', 'پیگیری و تصمیم'], ['evaluation', 'ارزیابی مهارت'], ['probation', 'شروع همکاری'], ['history', 'یادداشت و تاریخچه']].map(([key, label]) => `<button type="button" data-detail-tab="${key}" class="${detailTab === key ? 'is-active' : ''}" ${detailTab === key ? 'aria-current="page"' : ''}>${label}</button>`).join('')}</div>`;
  }
  function overview(a) {
    const c = a.candidate;
    const j = a.job_detail;
    return `<div class="rh-detail-grid"><section class="rh-detail-box"><h4>اطلاعات متقاضی</h4><button type="button" class="rh-btn rh-small rh-subtle" data-detail-tab="candidate" style="margin-bottom:14px">ویرایش مشخصات و رزومه</button><dl><dt>موبایل</dt><dd><span class="rh-ltr">${esc(c.phone)}</span></dd><dt>ایمیل</dt><dd>${esc(c.email || 'ثبت نشده')}</dd><dt>شهر</dt><dd>${esc(c.city || 'ثبت نشده')}</dd><dt>منبع</dt><dd>${esc(a.source_label || choiceLabel('sources', a.source))}</dd><dt>جزئیات منبع</dt><dd>${esc(a.source_detail || 'ثبت نشده')}</dd><dt>حقوق درخواستی</dt><dd>${money(a.requested_salary)}</dd></dl></section><section class="rh-detail-box"><h4>مسیر رسیدگی</h4><dl><dt>مسئول</dt><dd>${esc(a.owner_name || staffName(a.owner))}</dd><dt>اقدام بعدی</dt><dd>${esc(a.next_action || 'ثبت نشده')}</dd><dt>موعد اقدام</dt><dd>${esc(faDate(a.next_action_at, true))}</dd><dt>مصاحبه</dt><dd>${esc(faDate(a.interview_at, true))}</dd><dt>محل مصاحبه</dt><dd>${esc(a.interview_location || 'ثبت نشده')}</dd><dt>ثبت درخواست</dt><dd>${esc(faDate(a.created_at, true))}</dd></dl></section><section class="rh-detail-box rh-wide"><h4>رزومه و سوابق</h4><p>${esc(c.resume_text || 'خلاصهٔ سوابق ثبت نشده است.')}</p>${c.resume_url ? `<a class="rh-btn rh-small" href="${esc(c.resume_url)}" style="margin-top:12px">دریافت رزومهٔ PDF</a>` : ''}</section><section class="rh-detail-box rh-wide"><h4>انتظار از این موقعیت</h4><p>${esc(j.expected_outcomes || j.description || 'شرح نتیجهٔ موردانتظار در موقعیت شغلی تکمیل نشده است.')}</p><div class="rh-meta">${j.criteria.map(x => badge(`${x.label} · ${x.weight}٪`)).join('')}</div></section></div>`;
  }
  function candidateForm(a) {
    const c = a.candidate;
    let html = '<div class="rh-form-hint">این مشخصات در همهٔ درخواست‌های همین متقاضی مشترک است. شمارهٔ شناسایی پرونده: <span class="rh-ltr">' + esc(c.phone) + '</span></div>';
    html += formStart('candidate_update', a.id) + '<div class="rh-form-grid">';
    html += input('name','نام و نام خانوادگی',c.name,'text',true,null,false,'maxlength="160"');
    html += input('email','ایمیل',c.email,'email',false,null,false,'maxlength="254" dir="ltr"');
    html += input('city','شهر محل سکونت',c.city,'text',false,null,false,'maxlength="120"');
    html += '<label class="rh-field"><span>' + (c.resume_name ? 'جایگزینی فایل رزومه' : 'افزودن فایل رزومه') + '</span><input type="file" name="resume" accept="application/pdf,.pdf"><small>PDF حداکثر 5 مگابایت. با انتخاب نکردن فایل، رزومهٔ فعلی حفظ می‌شود.</small></label>';
    html += textarea('resume_text','سوابق، مهارت‌ها و شرایط همکاری',c.resume_text,false);
    return html + '</div>' + formEnd('ذخیره مشخصات و رزومه');
  }
  function followupForm(a) {
    let html = '';
    if (a.review_required) {
      html += `<div class="rh-form-hint">${esc(a.review_reason || 'این پرونده نیازمند بازبینی است.')}${a.pending_stage ? `<br>مرحلهٔ پیشنهادی: ${esc(choiceLabel('stages', a.pending_stage))}` : ''}</div>`;
      if (state.can_approve) html += formStart('approve', a.id) + '<div class="rh-form-grid">' + select('decision', 'تصمیم مدیریت', [{value: 'approve', label: 'تأیید تصمیم پیشنهادی'}, {value: 'return', label: 'بازگشت برای بررسی بیشتر'}], 'approve', true) + textarea('text', 'توضیح تصمیم', '', true) + '</div>' + formEnd('ثبت تصمیم مدیریت');
    }
    html += formStart('update', a.id) + '<div class="rh-form-grid">';
    html += select('stage', 'مرحلهٔ پرونده', state.choices.stages || [], a.stage, true);
    html += select('owner', 'مسئول رسیدگی', state.staff, a.owner, true, 'انتخاب مسئول');
    html += input('next_action', 'اقدام بعدی', a.next_action, 'text', false, 'برای پروندهٔ فعال و بانک استعدادها الزامی است.', false, 'maxlength="300"');
    html += input('next_action_at', 'موعد اقدام (وقت تهران)', localDateTime(a.next_action_at), 'datetime-local', false, 'تاریخ در ورودی به میلادی است.');
    html += input('interview_at', 'زمان مصاحبه (وقت تهران)', localDateTime(a.interview_at), 'datetime-local');
    html += input('interview_location', 'محل یا روش مصاحبه', a.interview_location, 'text', false, null, false, 'maxlength="300"');
    html += input('requested_salary', 'حقوق درخواستی (تومان)', a.requested_salary, 'number', false, null, false, 'min="0" step="1"');
    html += input('offered_salary', 'حقوق پیشنهادی مجموعه (تومان)', a.offered_salary, 'number', false, null, false, 'min="0" step="1"');
    html += input('start_date', 'تاریخ شروع کار (میلادی)', a.start_date, 'date');
    html += input('probation_review_at', 'تاریخ بازبینی دورهٔ آزمایشی (میلادی)', a.probation_review_at, 'date');
    html += select('source', 'منبع آشنایی', state.choices.sources || [], a.source, true);
    html += input('source_detail', 'جزئیات منبع / نام معرف', a.source_detail, 'text', false, null, false, 'maxlength="300"');
    html += textarea('decision_reason', 'دلیل تصمیم یا نتیجهٔ مذاکره', a.decision_reason, false, 'برای رد، انصراف، عدم توافق حقوق و ذخیره برای آینده، توضیح الزامی است.');
    html += '</div>' + `<div class="rh-form-hint" style="margin-top:16px">بودجهٔ این شغل: ${money(a.job_detail.salary_min)} تا ${money(a.job_detail.salary_max)}. تغییر مرحله در موارد نیازمند تأیید، ابتدا برای مدیریت ارسال می‌شود.</div>` + formEnd('ثبت پیگیری و تصمیم');
    return html;
  }
  function evaluationForm(a) {
    let html = a.evaluations_hidden ? '<div class="rh-form-hint">برای ارزیابی مستقل، نظر ارزیاب‌های دیگر پس از ثبت ارزیابی شما نمایش داده می‌شود.</div>' : '';
    html += (a.evaluations || []).map(e => `<article class="rh-evaluation"><header><strong>${esc(e.reviewer_name)}</strong>${badge(`${n(e.total)} از 100`, 'purple')}</header><div class="rh-meta">${e.scores.map(s => badge(`${s.label}: ${n(s.score)}`)).join('')}</div><p style="margin-top:10px">${esc(e.evidence)}</p><small>${esc(faDate(e.updated_at, true))}</small></article>`).join('');
    const own = (a.evaluations || []).find(e => e.reviewer === state.current_user_id);
    html += formStart('evaluate', a.id) + `<h4>${own ? 'بازبینی ارزیابی من' : 'ثبت ارزیابی مستقل'}</h4><p class="rh-muted">به هر معیار از 0 تا 100 امتیاز دهید و شاهد مرتبط با شغل را توضیح دهید.</p><div class="rh-scores">${a.job_detail.criteria.map((c, index) => `<div class="rh-score-row"><label for="rh-score-${index}">${esc(c.label)}<small>وزن: ${n(c.weight)} از 100</small></label><input data-money-exempt="1" id="rh-score-${index}" data-score type="number" required min="0" max="100" step="1" value="${esc(own && own.scores[index] ? own.scores[index].score : '')}" aria-label="امتیاز ${esc(c.label)} از 100"></div>`).join('')}</div><div class="rh-form-grid" style="margin-top:18px">`;
    html += textarea('evidence', 'شواهد مصاحبه و آزمون عملی', own ? own.evidence : '', true, 'مثلاً نتیجهٔ تکلیف، نمونهٔ کار یا پاسخ به موقعیت شبیه‌سازی‌شده.');
    html += select('recommendation', 'نظر ارزیاب', [{value: 'advance', label: 'پیشنهاد ادامهٔ فرایند'}, {value: 'review', label: 'نیازمند بررسی بیشتر'}, {value: 'decline', label: 'پیشنهاد عدم ادامه'}], own ? own.recommendation : 'review', true, undefined, true);
    return html + '</div>' + formEnd(own ? 'ثبت بازبینی ارزیابی' : 'ثبت ارزیابی');
  }
  function probationForm(a) {
    if (!['started', 'probation', 'hired'].includes(a.stage)) return '<div class="rh-empty"><div class="rh-empty-symbol">✓</div><h3>این متقاضی هنوز شروع به کار نکرده است</h3><p>پس از شروع کار و ثبت مرحلهٔ مربوط، نتیجهٔ عملکرد و دورهٔ آزمایشی را اینجا ثبت کنید.</p><button type="button" class="rh-btn" data-detail-tab="followup">پیگیری و تصمیم</button></div>';
    return `<div class="rh-form-hint">ارزیابی دورهٔ آزمایشی را ثبت کنید. برای نهایی‌کردن استخدام، مرحلهٔ پرونده را در بخش «پیگیری و تصمیم» تغییر دهید.</div>${formStart('probation', a.id)}<div class="rh-form-grid">${input('start_date', 'تاریخ شروع کار (میلادی)', a.start_date, 'date')}${input('probation_review_at', 'تاریخ بازبینی بعدی (میلادی)', a.probation_review_at, 'date')}${textarea('probation_outcome', 'نتیجهٔ کار، آموزش و دورهٔ آزمایشی', a.probation_outcome, true, 'عملکرد واقعی را با نتیجهٔ موردانتظار این شغل مقایسه کنید.')}</div>${formEnd('ثبت ارزیابی شروع همکاری')}`;
  }
  function changeDetails(changes) {
    if (!changes || !Object.keys(changes).length) return '';
    const labels = {title:'عنوان', status:'وضعیت', stage:'مرحله', owner:'مسئول', owner_id:'مسئول', salary_min:'حداقل حقوق', salary_max:'سقف حقوق', budget_approved:'تأیید بودجه', requested_salary:'حقوق درخواستی', offered_salary:'حقوق پیشنهادی', next_action:'اقدام بعدی', next_action_at:'موعد اقدام', interview_at:'زمان مصاحبه', interview_location:'محل مصاحبه', decision_reason:'دلیل تصمیم', start_date:'شروع کار', probation_review_at:'بازبینی آزمایشی', probation_outcome:'نتیجه دوره آزمایشی', criteria:'معیارهای ارزیابی', requirements:'مهارت‌های لازم', description:'شرح کار', expected_outcomes:'نتیجه موردانتظار', headcount:'تعداد نیرو', location:'محل کار', shift:'شیفت', benefits:'مزایا', source:'منبع', source_detail:'جزئیات منبع', review_required:'نیازمند بازبینی', pending_stage:'مرحله پیشنهادی', evidence:'شواهد ارزیابی', total:'امتیاز', recommendation:'نظر ارزیاب', requires_executive_approval:'تأیید نهایی مدیریت'};
    const entries = Object.entries(changes).filter(([key]) => labels[key]);
    if (!entries.length) return '';
    const format = (key, value) => {
      if (value === null || value === undefined || value === '') return '—';
      if (typeof value === 'boolean') return value ? 'بله' : 'خیر';
      if (key === 'stage' || key === 'pending_stage') return choiceLabel('stages', value);
      if (key === 'owner' || key === 'owner_id') return staffName(value);
      if (typeof value === 'object') return Array.isArray(value) ? value.map(x => typeof x === 'object' ? (x.label || '') + (x.weight ? ' (' + x.weight + ')' : '') : String(x)).join('، ') : 'به‌روزرسانی شده';
      return String(value);
    };
    return '<details><summary class="rh-muted">جزئیات تغییر</summary>' + entries.map(([key, value]) => { const oldValue = value && typeof value === 'object' && !Array.isArray(value) && ('old' in value || 'before' in value) ? (value.old === undefined ? value.before : value.old) : undefined; const newValue = value && typeof value === 'object' && !Array.isArray(value) && ('new' in value || 'after' in value) ? (value.new === undefined ? value.after : value.new) : value; return `<p><b>${esc(labels[key])}:</b> ${oldValue === undefined ? '' : esc(format(key, oldValue)) + ' ← '}${esc(format(key, newValue))}</p>`; }).join('') + '</details>';
  }
  function history(a) {
    return `${formStart('note', a.id)}${textarea('text', 'ثبت یادداشت یا نتیجهٔ تماس', '', true)}${formEnd('افزودن یادداشت')}<h4 style="margin-top:28px">تاریخچهٔ رسیدگی</h4><div class="rh-timeline">${(a.activities || []).map(e => `<article class="rh-event"><strong>${esc(e.actor_name || 'سیستم')}</strong><small> · ${esc(faDate(e.created_at, true))}</small><p>${esc(e.text || e.kind)}</p>${changeDetails(e.changes)}</article>`).join('') || '<p class="rh-muted">هنوز سابقه‌ای ثبت نشده است.</p>'}</div>`;
  }
  function renderDetail() {
    if (!detail) return;
    const scroll = dialog.scrollTop;
    const a = detail;
    root.querySelector('#rh-dialog-title').textContent = 'پروندهٔ متقاضی';
    dialogBody.innerHTML = detailHeader(a) + ({overview, candidate: candidateForm, followup: followupForm, evaluation: evaluationForm, probation: probationForm, history}[detailTab])(a);
    dialog.scrollTop = scroll;
  }
  async function compareApplications() {
    const ids = [...selected];
    if (ids.length < 2) return;
    openDialog('مقایسهٔ متقاضیان', '<div class="rh-loading"><span class="rh-spinner"></span> در حال دریافت پرونده‌ها…</div>');
    const version = dialogVersion;
    try {
      const results = await Promise.all(ids.map(id => api(`applications/${id}/`)));
      if (!dialog.open || version !== dialogVersion) return;
      const sameJob = new Set(results.map(r => r.application.job)).size === 1;
      dialogBody.innerHTML = `${!sameJob ? '<div class="rh-form-hint">این افراد برای شغل‌های متفاوت هستند؛ امتیازهای مبتنی بر معیارهای متفاوت، مستقیماً قابل مقایسه نیستند.</div>' : ''}<div class="rh-comparison">${results.map(({application: a}) => `<article class="rh-compare-card"><h3>${esc(a.name)}</h3>${stageBadge(a)}<dl><dt>موقعیت</dt><dd>${esc(a.job_title)}</dd><dt>حقوق درخواستی</dt><dd>${money(a.requested_salary)}</dd><dt>امتیاز قابل مشاهده</dt><dd>${a.score === null ? 'هنوز قابل مشاهده نیست' : n(a.score) + ' از 100'}</dd><dt>رزومه و سوابق</dt><dd>${esc(a.candidate.resume_text || 'ثبت نشده')}</dd><dt>شواهد ارزیابی</dt><dd>${esc(a.evaluations_hidden ? 'پس از ثبت ارزیابی مستقل شما نمایش داده می‌شود.' : (a.evaluations || []).map(e => e.reviewer_name + ': ' + e.evidence).join('\n\n') || 'هنوز ارزیابی نشده است.')}</dd><dt>اقدام بعدی</dt><dd>${esc(a.next_action || 'ثبت نشده')}</dd></dl><button class="rh-btn rh-small" type="button" data-action="open-application" data-id="${a.id}" style="margin-top:16px">باز کردن پرونده</button></article>`).join('')}</div>`;
    } catch (e) { if (version === dialogVersion) dialogBody.innerHTML = `<div class="rh-form-error">${esc(e.message)}</div>`; }
  }
  root.addEventListener('click', async event => {
    const el = event.target.closest('button,[data-tab]');
    if (!el || !root.contains(el)) return;
    if (el.dataset.tab) { tab = el.dataset.tab; quick = ''; queryRefresh(); return; }
    if (el.dataset.quick) { quick = el.dataset.quick; Object.values(filters).forEach(id => root.querySelector('#' + id).value = ''); tab = quick === 'today' || quick === 'overdue' ? 'followups' : 'applications'; queryRefresh(); return; }
    if (el.dataset.detailTab) { detailTab = el.dataset.detailTab; renderDetail(); return; }
    const action = el.dataset.action;
    const id = Number(el.dataset.id);
    if (action === 'previous-page' || action === 'next-page') { page += action === 'next-page' ? 1 : -1; refresh(true).catch(() => {}); }
    if (action === 'close-dialog') closeDialog();
    if (action === 'clear' || el.id === 'rh-clear-filters') clearFilters();
    if (action === 'refresh') { el.disabled = true; try { await refresh(true); notice('اطلاعات به‌روز شد.'); } catch (_) {} finally { el.disabled = false; } }
    if (action === 'create-job') jobForm();
    if (action === 'edit-job') await editJob(id);
    if (action === 'create-application') applicationForm();
    if (action === 'create-ad') adForm();
    if (action === 'edit-ad') adForm(state.ads.find(a => a.id === id));
    if (action === 'job-applicants') { Object.values(filters).forEach(key => root.querySelector('#' + key).value = ''); quick = ''; tab = 'applications'; root.querySelector('#rh-job').value = String(id); queryRefresh(); }
    if (action === 'open-application' || action === 'open-followup') await openApplication(id, action === 'open-followup' ? 'followup' : 'overview');
    if (el.id === 'rh-compare') await compareApplications();
    if (action === 'add-criterion') dialogBody.querySelector('.rh-criteria-input').insertAdjacentHTML('beforeend', criteriaRow({label: '', weight: ''}));
    if (action === 'remove-criterion') el.closest('.rh-criterion-row').remove();
    if (action === 'approve-budget') {
      const form = el.closest('form');
      const errorBox = form.querySelector('.rh-form-error');
      errorBox.hidden = true;
      el.disabled = true;
      try { const data = new FormData(); data.set('action', 'approve_budget'); data.set('expected_updated_at', form.querySelector('[name=expected_updated_at]').value); await api(`jobs/${id}/`, data); await refresh(false); await editJob(id); notice('بودجهٔ ذخیره‌شده تأیید شد.'); }
      catch (e) { errorBox.textContent = e.message; errorBox.hidden = false; }
      finally { el.disabled = false; }
    }
  });
  root.addEventListener('change', event => {
    if (event.target.dataset.compare) {
      const id = Number(event.target.dataset.compare);
      if (event.target.checked && selected.size >= 3) { event.target.checked = false; notice('برای مقایسه، حداکثر سه متقاضی انتخاب کنید.', true); return; }
      event.target.checked ? selected.add(id) : selected.delete(id);
      render(); return;
    }
    if (event.target.matches('.rh-filters select')) queryRefresh();
    if (event.target.name === 'country') filterBranches();
  });
  root.querySelector('#rh-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(queryRefresh, 250); });
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
  dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(); } });
  root.addEventListener('submit', async event => {
    const form = event.target.closest('form[data-form]');
    if (!form) return;
    event.preventDefault();
    if (form.dataset.busy === '1' || !form.reportValidity()) return;
    const kind = form.dataset.form;
    const id = form.dataset.id;
    const data = new FormData(form);
    const errorBox = form.querySelector('.rh-form-error');
    errorBox.hidden = true;
    try {
      form.querySelectorAll('[type=datetime-local]').forEach(input => data.set(input.name, input.value ? input.value + ':00+03:30' : ''));
      if (kind === 'job') {
        const criteria = [...form.querySelectorAll('.rh-criterion-row')].map(row => ({label: row.querySelector('[data-criterion-label]').value.trim(), weight: Number(row.querySelector('[data-criterion-weight]').value)}));
        if (!criteria.length || criteria.some(c => !c.label || c.weight <= 0) || criteria.reduce((sum, c) => sum + c.weight, 0) !== 100) throw new Error('عنوان معیارها را کامل کنید؛ مجموع وزن معیارها باید 100 باشد.');
        data.set('criteria', JSON.stringify(criteria));
        data.set('requires_executive_approval', form.querySelector('[name=requires_executive_approval]').checked ? 'true' : 'false');
        data.set('action', 'save');
      }
      if (kind === 'application' || kind === 'candidate_update') {
        const file = form.querySelector('[name=resume]').files[0];
        if (file && (!/\.pdf$/i.test(file.name) || file.size > 5 * 1024 * 1024)) throw new Error('رزومه باید فایل PDF و حداکثر 5 مگابایت باشد.');
      }
      if (kind === 'evaluate') data.set('scores', JSON.stringify([...form.querySelectorAll('[data-score]')].map(input => Number(input.value))));
      if (!['job', 'application', 'ad'].includes(kind)) data.set('action', kind);
      const path = kind === 'job' ? `jobs/${id ? id + '/' : ''}` : kind === 'ad' ? `ads/${id ? id + '/' : ''}` : kind === 'application' ? 'applications/' : `applications/${id}/`;
      form.dataset.busy = '1';
      const buttons = form.querySelectorAll('button');
      buttons.forEach(button => button.disabled = true);
      const submit = form.querySelector('[type=submit]');
      const oldText = submit.textContent;
      submit.textContent = 'در حال ثبت…';
      try {
        const result = await api(path, data);
        if (kind === 'application') { tab = 'applications'; quick = ''; page = 1; }
        try { await refresh(false); } catch (_) { /* Saved successfully; keep the success distinction clear. */ }
        if (['job', 'ad', 'application'].includes(kind)) {
          closeDialog();
          if (kind === 'application') { tab = 'applications'; quick = ''; render(); }
        } else if (result.application) { detail = result.application; renderDetail(); }
        else { const resultDetail = await api(`applications/${id}/`); detail = resultDetail.application; renderDetail(); }
        notice(result.candidate_reused ? 'درخواست جدید ثبت شد؛ اطلاعات و رزومهٔ پروندهٔ موجود این فرد حفظ شد.' : 'اطلاعات با موفقیت ثبت شد.');
      } finally {
        delete form.dataset.busy;
        buttons.forEach(button => button.disabled = false);
        submit.textContent = oldText;
      }
    } catch (e) {
      errorBox.textContent = e.message;
      errorBox.hidden = false;
      errorBox.scrollIntoView({block: 'nearest'});
    }
  });
  refresh(true).catch(() => {});
})();
