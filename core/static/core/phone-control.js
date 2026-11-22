'use strict';

(() => {
  const control = document.getElementById('phone-control');
  if (!control) return;

  const find = id => document.getElementById(id);
  const liveList = find('live-list');
  const liveSummary = find('live-summary');
  const liveStatus = find('live-status');
  const liveRefresh = find('live-refresh');
  const queueLists = ['queue-assistants', 'queue-requests', 'queue-jobs'].map(find);
  const queueStatus = find('queue-status');
  const queueFilter = find('queue-filter');
  const queueRefresh = document.querySelector('[data-queue-refresh]');
  const csrf = document.querySelector('#phone-control-csrf input');
  const digits = new Intl.NumberFormat('fa-IR');
  const dates = new Intl.DateTimeFormat('fa-IR', {
    dateStyle: 'medium', timeZone: 'Asia/Tehran'
  });
  const appointments = new Intl.DateTimeFormat('fa-IR', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran'
  });
  const liveModes = {
    listen: 'فقط شنیدن', whisper: 'راهنمایی خصوصی', join: 'ورود به مکالمه'
  };
  let liveAvailable = false;
  let liveVisible = true;
  let readingLive = null;
  let startingLive = false;
  let liveSignature = '';
  let queueBusy = false;
  let selectedAssistant = '';
  let jobPage = 1;
  let requestPage = 1;

  function node(tag, classes = '', value) {
    const element = document.createElement(tag);
    if (classes) element.className = classes;
    if (value !== undefined) element.textContent = value;
    return element;
  }

  function button(text, onClick, style = '') {
    const element = node('button', 'btn compact ' + style, text);
    element.type = 'button';
    element.addEventListener('click', onClick);
    return element;
  }

  function row(heading, detail) {
    const item = node('article', 'control-item');
    const copy = node('div', 'control-item-copy');
    copy.append(node('h3', '', heading), node('p', 'small', detail));
    const actions = node('div', 'row control-item-actions');
    item.append(copy, actions);
    return {item, actions, copy};
  }

  function showStatus(region, message, tone = '') {
    region.textContent = message;
    region.dataset.tone = tone;
  }

  async function request(url, payload) {
    const options = {headers: {'Accept': 'application/json'}, cache: 'no-store'};
    if (payload) {
      if (!csrf?.value) throw new Error('برای ادامه صفحه را دوباره باز کنید.');
      options.method = 'POST';
      options.headers['X-CSRFToken'] = csrf.value;
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }
    const controller = new AbortController();
    options.signal = controller.signal;
    const timer = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, options);
      if (response.redirected || response.status === 401 || response.status === 403) {
        throw new Error('دسترسی رد شد. نشست استاف و سطح دسترسی را بررسی کنید.');
      }
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || data.error || 'درخواست انجام نشد.');
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError' || error instanceof TypeError || error instanceof SyntaxError) {
        const message = payload
          ? 'نتیجهٔ درخواست مشخص نشد. پیش از تلاش دوباره، وضعیت را تازه کنید.'
          : 'دریافت اطلاعات ممکن نشد. دوباره تازه‌سازی کنید.';
        throw new Error(message);
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function dateLabel(raw) {
    if (!raw) return 'بدون موعد';
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw);
    const value = dateOnly ? raw + 'T12:00:00Z' : raw;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'موعد نامشخص' : (dateOnly ? dates : appointments).format(date);
  }

  function callDuration(seconds) {
    if (seconds === null || seconds === undefined) return 'زمان مکالمه نامشخص';
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    return digits.format(Math.floor(total / 60)) + ' دقیقه و ' + digits.format(total % 60) + ' ثانیه';
  }

  function renderLive(data) {
    const calls = data.available && Array.isArray(data.calls) ? data.calls : [];
    const able = data.available && data.can_start !== false;
    const modes = (data.modes || []).map(mode => typeof mode === 'string' ? {id: mode} : mode)
      .filter(mode => Object.hasOwn(liveModes, mode.id));
    liveAvailable = data.available === true;
    liveSummary.textContent = liveAvailable
      ? digits.format(calls.length) + ' مکالمهٔ قابل نظارت' : 'نظارت در دسترس نیست';
    const signature = JSON.stringify([calls.map(call => [call.id, call.operator, call.extension]), modes, able, data.reason]);
    if (signature === liveSignature) {
      // A poll may update call durations while the operator is using a button.
      calls.forEach((call, index) => {
        const detail = liveList.children[index]?.querySelector('.control-call-duration');
        if (detail) detail.textContent = callDuration(call.elapsed_seconds);
      });
      return;
    }
    liveSignature = signature;
    if (!calls.length) {
      const reason = liveAvailable ? 'مکالمه‌ای برای نظارت در جریان نیست.' : data.reason || 'وضعیت اتصال در دسترس نیست.';
      liveList.replaceChildren(node('p', 'small control-empty', reason));
      return;
    }
    const rows = calls.map(call => {
      const {item, actions, copy} = row(call.operator || 'اپراتور', '');
      const detail = copy.querySelector('p');
      const extension = node('bdi', '', call.extension);
      extension.dir = 'ltr';
      detail.append('داخلی ', extension, ' · ', node('span', 'control-call-duration', callDuration(call.elapsed_seconds)));
      for (const mode of modes) {
        const action = button(mode.label || liveModes[mode.id], () => startObservation(call.id, mode.id));
        action.disabled = !able;
        actions.append(action);
      }
      return item;
    });
    if (data.reason && !able) rows.push(node('p', 'small', data.reason));
    liveList.replaceChildren(...rows);
  }

  function refreshLive(manual = false) {
    if (readingLive) return readingLive;
    if (startingLive) return;
    if (manual) showStatus(liveStatus, 'در حال دریافت تماس‌های زنده…');
    readingLive = request(control.dataset.liveUrl).then(data => {
      if (startingLive) return;
      renderLive(data);
      if (manual) showStatus(liveStatus, data.available ? 'فهرست تماس‌ها به‌روز شد.' : '');
    }).catch(error => {
      if (startingLive) return;
      renderLive({available: false, reason: 'وضعیت تماس‌ها دریافت نشد.'});
      showStatus(liveStatus, error.message, 'error');
    }).finally(() => { readingLive = null; });
    return readingLive;
  }

  async function startObservation(callId, mode) {
    if (startingLive || !liveAvailable) return;
    if (mode === 'join' && !window.confirm('با ورود به مکالمه، مشتری و اپراتور صدای شما را می‌شنوند. ادامه می‌دهید؟')) return;
    startingLive = true;
    liveRefresh.disabled = true;
    const buttons = [...liveList.querySelectorAll('button:not(:disabled)')];
    buttons.forEach(element => { element.disabled = true; });
    showStatus(liveStatus, 'در حال ارسال درخواست به مرکز تلفن…');
    try {
      const data = await request(control.dataset.liveUrl, {call_id: callId, mode});
      if (data.accepted !== true) throw new Error('مرکز تلفن درخواست را تأیید نکرد.');
      showStatus(liveStatus, data.message || 'درخواست فرستاده شد. تماس را از داخلی نظارت پاسخ دهید.', 'success');
    } catch (error) {
      showStatus(liveStatus, error.message, 'error');
    } finally {
      await readingLive;
      startingLive = false;
      liveRefresh.disabled = false;
      liveSignature = '';
      await refreshLive();
    }
  }

  function pageControls(label, page, update) {
    const block = node('nav', 'row control-pagination');
    block.setAttribute('aria-label', label);
    if (page.pages < 2) {
      block.hidden = true;
      return block;
    }
    const previous = button('قبلی', () => update(page.page - 1));
    const next = button('بعدی', () => update(page.page + 1));
    previous.disabled = page.page <= 1;
    next.disabled = page.page >= page.pages;
    block.append(previous, node('span', 'small', digits.format(page.page) + ' از ' + digits.format(page.pages)), next);
    return block;
  }

  function renderQueue(data) {
    const {queues, jobs, candidates, can_manage: canManage} = data;
    const [assistants, requests, planned] = queueLists;
    const names = new Map(queues.map(queue => [queue.assistant, queue.name]));
    const summaries = queues.map(queue => {
      const state = queue.paused ? 'متوقف' : 'در حال پذیرش برنامه';
      const {item, actions, copy} = row(queue.name, state);
      const counts = node('div', 'row control-counts');
      for (const [label, count] of [
        ['در صف', queue.queued_count], ['تلاش مجدد', queue.retry_count],
        ['مسدود', queue.blocked_count], ['انجام‌شده', queue.completed_count],
        ['ناموفق', queue.failed_count], ['لغوشده', queue.cancelled_count]
      ]) {
        counts.append(node('span', 'chip', label + ' ' + digits.format(count || 0)));
      }
      copy.append(counts);
      if (canManage) {
        const change = queue.paused ? 'resume' : 'pause';
        actions.append(button(queue.paused ? 'باز کردن صف' : 'توقف صف',
          () => refreshQueue({action: change, assistant: queue.assistant})));
      }
      return item;
    });
    assistants.replaceChildren(...summaries);

    const eligible = candidates.items.map(candidate => {
      const {item, actions} = row(candidate.name || 'درخواست بدون نام', 'موعد ' + dateLabel(candidate.scheduled_for));
      if (canManage) {
        const add = button('افزودن به برنامه', () => refreshQueue({
          action: 'enqueue', assistant: selectedAssistant, lead_id: candidate.lead_id
        }));
        add.dataset.planAdd = '';
        add.disabled = !names.has(selectedAssistant);
        actions.append(add);
      }
      return item;
    });
    if (eligible.length && canManage) {
      const picker = node('label', 'control-assistant-picker', 'دستیار برای افزودن به برنامه');
      const select = node('select');
      const prompt = node('option', '', 'انتخاب دستیار');
      prompt.value = '';
      select.append(prompt);
      for (const [id, name] of names) {
        const option = node('option', '', name);
        option.value = id;
        select.append(option);
      }
      select.value = names.has(selectedAssistant) ? selectedAssistant : '';
      select.addEventListener('change', () => {
        selectedAssistant = select.value;
        requests.querySelectorAll('[data-plan-add]').forEach(action => {
          action.disabled = !names.has(selectedAssistant);
        });
      });
      picker.append(select);
      eligible.unshift(picker);
    }
    if (!eligible.length) eligible.push(node('p', 'small control-empty', 'درخواست واجد شرایطی برای افزودن به برنامه وجود ندارد.'));
    requests.replaceChildren(...eligible, pageControls('صفحه‌های درخواست‌ها', candidates, page => {
      requestPage = page;
      refreshQueue();
    }));

    const plannedRows = jobs.items.map(job => {
      const name = names.get(job.assistant) || 'دستیار';
      const {item, actions, copy} = row(job.lead_name || 'درخواست بدون نام',
        name + ' · ' + dateLabel(job.scheduled_for) + ' · ' + digits.format(job.attempts || 0) + ' تلاش');
      copy.append(node('span', 'chip', job.status_label || 'وضعیت نامشخص'));
      if (canManage && ['queued', 'retry', 'blocked'].includes(job.status)) {
        actions.append(button('لغو درخواست', () => {
          if (window.confirm('این درخواست از برنامهٔ دستیار لغو شود؟')) {
            refreshQueue({action: 'cancel', job_id: job.id});
          }
        }));
      }
      return item;
    });
    if (!plannedRows.length) plannedRows.push(node('p', 'small control-empty', 'در این فهرست درخواست برنامه‌ریزی‌شده‌ای وجود ندارد.'));
    planned.replaceChildren(...plannedRows, pageControls('صفحه‌های برنامه', jobs, page => {
      jobPage = page;
      refreshQueue();
    }));
  }

  function queueURL() {
    const url = new URL(control.dataset.queueUrl, window.location.origin);
    const assistant = queueFilter.querySelector('[name="assistant"]').value;
    const status = queueFilter.querySelector('[name="status"]').value;
    if (assistant) url.searchParams.set('assistant', assistant);
    if (status) url.searchParams.set('status', status);
    url.searchParams.set('page', jobPage);
    url.searchParams.set('candidate_page', requestPage);
    return url;
  }

  async function refreshQueue(payload = null) {
    if (queueBusy) return;
    queueBusy = true;
    const controls = [queueRefresh, ...queueFilter.querySelectorAll('select, button'),
      ...queueLists.flatMap(list => [...list.querySelectorAll('select, button')])];
    const enabled = controls.filter(element => !element.disabled);
    enabled.forEach(element => { element.disabled = true; });
    showStatus(queueStatus, payload ? 'در حال ثبت تغییر…' : 'در حال دریافت برنامه…');
    let saved = false;
    try {
      if (payload) {
        const result = await request(control.dataset.queueUrl, payload);
        if (result.ok !== true) throw new Error('ثبت تغییر تأیید نشد.');
        saved = true;
      }
      const data = await request(queueURL());
      jobPage = data.jobs.page;
      requestPage = data.candidates.page;
      renderQueue(data);
      showStatus(queueStatus, saved ? 'تغییر ذخیره شد.' : '', saved ? 'success' : '');
    } catch (error) {
      const message = saved ? 'تغییر ذخیره شد. تازه‌سازی فهرست لازم است.' : error.message;
      showStatus(queueStatus, message, 'error');
    } finally {
      queueBusy = false;
      enabled.forEach(element => { element.disabled = false; });
    }
  }

  const menu = find('control-menu');
  const sidebar = find('control-sidebar');
  if (menu && sidebar) {
    const setMenu = open => {
      sidebar.classList.toggle('open', open);
      menu.setAttribute('aria-expanded', String(open));
    };
    menu.addEventListener('click', () => setMenu(menu.getAttribute('aria-expanded') !== 'true'));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
        setMenu(false);
        menu.focus();
      }
    });
  }

  function changeFilter(event) {
    event.preventDefault();
    jobPage = 1;
    refreshQueue();
  }

  queueFilter.addEventListener('submit', changeFilter);
  queueFilter.addEventListener('change', changeFilter);
  queueRefresh.addEventListener('click', () => refreshQueue());
  liveRefresh.addEventListener('click', () => refreshLive(true));
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(([entry]) => { liveVisible = entry.isIntersecting; });
    observer.observe(liveSummary);
  }
  window.setInterval(() => {
    if (liveAvailable && liveVisible && !document.hidden) refreshLive();
  }, 15000);
  refreshLive();
  refreshQueue();
})();
