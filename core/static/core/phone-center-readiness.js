(function () {
  'use strict';

  const reportSchema = 'greenlife-voip-preflight/1';
  const maximumReportSize = 65536;
  const maximumNoteLength = 240;
  const checkStates = {
    pass: ['تأیید شد', 'green'],
    fail: ['نیاز به بررسی', 'red'],
    pending: ['در انتظار', 'amber'],
  };
  const filterLabels = {
    all: 'همه', fail: 'نیاز به بررسی', pending: 'در انتظار', pass: 'تأیید شده',
  };
  const routes = {
    legacy: 'مسیر قبلی', pilot: 'دستیار آزمایشی', unknown: 'نامشخص',
  };
  const testOutcomes = {
    reached: ['تماس به مقصد رسید', 'green'],
    issue: ['تماس رسید و ایراد داشت', 'amber'],
    missed: ['تماس به مقصد نرسید', 'red'],
  };
  const checks = [
    {id: 'pbx', name: 'دسترسی به Asterisk', source: 'pbx',
      instruction: 'ابزار بررسی را روی سرور تلفن اجرا کنید تا پاسخ رابط Asterisk در گزارش بیاید.'},
    {id: 'functions', name: 'کنترل مسیر تماس', source: 'pbx',
      instruction: 'در گزارش سرور، فعال‌بودن توابع خواندن مسیر ذخیره‌شده و بررسی مقصد تماس را کنترل کنید.'},
    {id: 'pilot', name: 'داخلی آزمایشی و دستیار', source: 'pbx',
      instruction: 'ثبت داخلی آزمایشی، برنامهٔ دستیار و مقصد تماس در صورت اختلال را در گزارش کنترل کنید.'},
    {id: 'trunk', name: 'ترانک شاتل', source: 'pbx',
      instruction: 'هنگام تهیهٔ گزارش، نام نقطهٔ اتصال شاتل را وارد کنید تا وجود آن در Asterisk بررسی شود.'},
    {id: 'did', name: 'مسیریابی شمارهٔ اصلی', source: 'pbx',
      instruction: 'ورودی شمارهٔ اصلی در مسیر شاتل و مقصد جایگزین آن را با گزارش تطبیق دهید.'},
    {id: 'carrier_path', name: 'ثبت SIP یا تطبیق IP', source: 'pbx',
      instruction: 'نوع اتصال اعلام‌شده از سوی شاتل را هنگام تهیهٔ گزارش مشخص کنید تا ثبت SIP یا تطبیق IP بررسی شود.'},
    {id: 'fallback', name: 'مقصد پذیرش قبلی', source: 'pbx',
      instruction: 'مقصد فعلی پذیرش را هنگام تهیهٔ گزارش مشخص کنید تا مسیر بازگشت با آن تطبیق داده شود.'},
    {id: 'carrier', name: 'تنظیمات تأییدشدهٔ اپراتور', source: 'operator',
      instruction: 'مسئول فنی تنظیمات تحویلی شاتل و مقصد فعلی پذیرش را تطبیق دهد و نتیجه را در گزارش ثبت کند.'},
    {id: 'inbound_call', name: 'تماس از بیرون', source: 'operator',
      instruction: 'با تلفنی خارج از مرکز به شمارهٔ اصلی زنگ بزنید و رسیدن تماس به مقصد مورد انتظار را ثبت کنید.'},
    {id: 'duplex', name: 'صدای دوطرفه و کلیدها', source: 'operator',
      instruction: 'در همان تماس آزمایشی، شنیدن صدا در هر دو طرف و پاسخ به کلیدهای تلفن را بررسی کنید.'},
    {id: 'handoff', name: 'انتقال به پذیرش', source: 'operator',
      instruction: 'از مسیر آزمایشی به پذیرش منتقل شوید و رسیدن تماس و پاسخ‌گویی را ثبت کنید.'},
    {id: 'restore', name: 'آزمون بازگشت به مسیر قبلی', source: 'operator',
      instruction: 'مسئول فنی بازگشت به مسیر قبلی را در آزمون هماهنگ‌شده بررسی کند و رسیدن تماس به پذیرش را ثبت کند.'},
  ];
  const formatCount = new Intl.NumberFormat('fa-IR');
  const formatTimestamp = new Intl.DateTimeFormat('fa-IR', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran',
  });
  const formatTestDate = new Intl.DateTimeFormat('fa-IR', {
    dateStyle: 'medium', timeZone: 'Asia/Tehran',
  });
  const tehranInputDate = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Asia/Tehran',
  });

  function todayInTehran() {
    const parts = Object.fromEntries(tehranInputDate.formatToParts().map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function timestamp(value) {
    return typeof value === 'string' && value.length <= 40 && Number.isFinite(Date.parse(value));
  }

  function normalizeReport(value, mainPhone) {
    if (value?.schema !== reportSchema || value.number !== mainPhone || !timestamp(value.checked_at) ||
        typeof value.route !== 'string' || !Object.hasOwn(routes, value.route)) return null;

    const results = {};
    for (const {id, source} of checks) {
      const check = value.checks?.[id];
      if (!check || typeof check.status !== 'string' || !Object.hasOwn(checkStates, check.status) ||
          typeof check.detail !== 'string' || check.source !== source) return null;
      results[id] = {status: check.status, detail: check.detail.slice(0, 300), source};
    }
    return {schema: reportSchema, number: mainPhone, checked_at: value.checked_at, route: value.route, checks: results};
  }

  function normalizeTest(value, inboundPhone) {
    if (value?.number !== inboundPhone || typeof value.outcome !== 'string' || !Object.hasOwn(testOutcomes, value.outcome) ||
        !timestamp(value.savedAt) || typeof value.testedOn !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(value.testedOn) || value.testedOn > todayInTehran() ||
        typeof value.note !== 'string') return null;

    const date = new Date(`${value.testedOn}T12:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value.testedOn) return null;
    return {
      number: inboundPhone, outcome: value.outcome, testedOn: value.testedOn,
      savedAt: value.savedAt, note: value.note.trim().slice(0, maximumNoteLength),
    };
  }

  function readLocal(key) {
    try {
      return JSON.parse(localStorage.getItem(key));
    } catch {
      return null;
    }
  }

  function writeLocal(key, record) {
    try {
      if (record === null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(record));
      return true;
    } catch {
      return false;
    }
  }

  window.createPhoneCenterReadiness = function ({key, mainPhone, inboundPhone, e, chip, notify}) {
    const reportKey = `${key}:readiness:${mainPhone}`;
    const testKey = `${key}:inbound-test:${inboundPhone}`;
    const byId = id => document.getElementById(id);
    let report = normalizeReport(readLocal(reportKey), mainPhone);
    let inboundTest = normalizeTest(readLocal(testKey), inboundPhone);
    let activeFilter = 'all';
    let uploadVersion = 0;
    let reportNotice = {text: '', state: ''};

    function counts() {
      const result = {all: checks.length, pass: 0, fail: 0, pending: 0};
      for (const {id} of checks) result[report?.checks[id].status ?? 'pending'] += 1;
      return result;
    }

    function manualTestBadge() {
      return inboundTest ? chip(...testOutcomes[inboundTest.outcome]) : chip('آزمون ثبت نشده', 'amber');
    }

    function manualDate() {
      return formatTestDate.format(new Date(`${inboundTest.testedOn}T12:00:00Z`));
    }

    function summaryCards() {
      const {all, pass} = counts();
      const reportBadge = report ? chip(`${formatCount.format(pass)} از ${formatCount.format(all)} بررسی تأیید شد`, pass === all ? 'green' : 'amber') : chip('گزارش بارگذاری نشده', 'amber');
      const reportMeta = report ? `<time datetime="${e(report.checked_at)}">${e(formatTimestamp.format(new Date(report.checked_at)))}</time> · ${e(routes[report.route])}` : 'گزارش سرور، نتیجهٔ ۱۲ بررسی را نشان می‌دهد.';
      const inboundMeta = inboundTest ? `آزمون ثبت دستی در ${e(manualDate())}` : 'ثبت دستی نتیجه پس از تماس آزمایشی';
      return `<div class="phone-lines">
        <article class="phone-line-card">
          <div class="line-card-head"><div class="line-card-title"><h3>خط اصلی</h3><bdi>${e(mainPhone)}</bdi></div>${reportBadge}</div>
          <p class="small">${reportMeta}</p>
          <div class="line-card-actions"><button type="button" class="btn compact" data-tab="main-line">بررسی خط اصلی</button></div>
        </article>
        <article class="phone-line-card">
          <div class="line-card-head"><div class="line-card-title"><h3>خط ورودی</h3><bdi>${e(inboundPhone)}</bdi></div>${chip('فقط ورودی', 'violet')}</div>
          <p class="small">${inboundMeta}</p>
          <div class="line-card-actions">${manualTestBadge()}<button type="button" class="btn compact" data-tab="main-line" data-focus-target="inbound-only-line">آزمون خط ورودی</button></div>
        </article>
      </div>`;
    }

    function countCards(currentCounts) {
      return ['pass', 'fail', 'pending'].map(status => `
        <div class="report-count" data-status="${status}"><strong>${formatCount.format(currentCounts[status])}</strong><span>${checkStates[status][0]}</span></div>`).join('');
    }

    function checklist() {
      const visible = checks.filter(({id}) => activeFilter === 'all' ||
        (report?.checks[id].status ?? 'pending') === activeFilter);
      if (!visible.length) return '<p class="empty-state">در این وضعیت موردی برای نمایش وجود ندارد.</p>';

      return visible.map(({id, name, source, instruction}) => {
        const result = report?.checks[id];
        const sourceLabel = source === 'operator' ? 'تأیید مسئول فنی' : 'بررسی سرور';
        const evidence = result?.detail || 'نتیجه‌ای برای این مورد ثبت نشده است.';
        return `<details class="check-row" data-check="${id}">
          <summary class="check-row-head"><strong>${e(name)}</strong>${chip(...checkStates[result?.status ?? 'pending'])}</summary>
          <div class="check-evidence"><span class="small">${sourceLabel}</span><p>${e(evidence)}</p>
            <p class="check-instruction">${e(instruction)}</p></div>
        </details>`;
      }).join('');
    }

    function reportResults() {
      const currentCounts = counts();
      const progress = `${formatCount.format(currentCounts.pass)} از ${formatCount.format(currentCounts.all)} بررسی تأیید شد`;
      const checkedAt = report ? `<time datetime="${e(report.checked_at)}">${e(formatTimestamp.format(new Date(report.checked_at)))}</time>` : 'گزارش بارگذاری نشده';
      return `<section class="report-summary" aria-label="نتیجهٔ گزارش خط اصلی">
        <div class="spread"><strong>${progress}</strong><span class="small">${checkedAt} · مسیر ثبت‌شده ${e(routes[report?.route ?? 'unknown'])}</span></div>
        <progress class="report-meter" value="${currentCounts.pass}" max="${currentCounts.all}" aria-label="${progress}"></progress>
        <div class="report-counts">${countCards(currentCounts)}</div>
      </section>
      <div class="check-filters" role="group" aria-label="فیلتر بررسی‌ها">${Object.entries(filterLabels).map(([status, label]) =>
        `<button type="button" class="btn compact" data-action="readiness-filter" data-status="${status}" aria-pressed="${status === activeFilter}">${label}</button>`).join('')}</div>
      <div id="readiness-check-list" class="stack">${checklist()}</div>`;
    }

    function testRecord() {
      if (!inboundTest) return '<p class="small">آزمون تماس ورودی هنوز ثبت نشده است.</p>';

      return `<div class="spread"><div class="row">${manualTestBadge()}${chip('ثبت دستی', 'violet')}</div>
        <button type="button" class="btn compact" data-action="readiness-clear-test">حذف نتیجهٔ آزمون</button></div>
        <p class="small">تاریخ تماس ${e(manualDate())} · زمان ثبت ${e(formatTimestamp.format(new Date(inboundTest.savedAt)))}</p>
        ${inboundTest.note ? `<p class="operator-note">${e(inboundTest.note)}</p>` : ''}`;
    }

    function reportTools() {
      return `<div class="report-tools">
        <div class="report-upload spread"><span id="report-upload-label">گزارش بررسی Asterisk برای <bdi>${e(mainPhone)}</bdi></span>
          <input id="main-line-report" type="file" accept=".json,application/json" hidden>
          <button type="button" class="btn" data-action="readiness-pick-report" aria-describedby="report-upload-label main-line-message">انتخاب فایل گزارش</button></div>
        <div class="report-actions"><button type="button" class="btn compact" data-action="readiness-clear-report" ${report ? '' : 'hidden'}>حذف گزارش</button></div>
        <p class="small report-message" id="main-line-message" role="status" data-state="${reportNotice.state}">${e(reportNotice.text)}</p>
      </div>`;
    }

    function mainLine() {
      const today = todayInTehran();
      return `<div class="stack">
        <section class="panel" aria-labelledby="main-line-title">
          <div class="panel-head spread"><div><h2 id="main-line-title">بررسی خط اصلی <bdi>${e(mainPhone)}</bdi></h2>
            <p class="small">گزارش و نتایج آزمون در مرورگر همین حساب ذخیره می‌شوند.</p></div>
            <button type="button" class="btn compact ghost" data-tab="main-line" data-focus-target="inbound-only-line">آزمون خط ورودی <bdi>${e(inboundPhone)}</bdi></button></div>
          ${reportTools()}
          <div id="main-line-results" class="stack">${reportResults()}</div>
        </section>
        <section class="panel" id="inbound-only-line" tabindex="-1" aria-labelledby="inbound-line-title">
          <div class="panel-head spread"><div><h2 id="inbound-line-title">آزمون خط ورودی <bdi>${e(inboundPhone)}</bdi></h2></div>${chip('فقط ورودی', 'violet')}</div>
          <div class="check-evidence" id="inbound-test-record" role="status">${testRecord()}</div>
          <details class="check-row" id="inbound-test-editor">
            <summary class="check-row-head"><strong>ثبت نتیجهٔ تماس آزمایشی</strong></summary>
            <form id="inbound-test-form" class="test-form form-grid">
              <p class="small wide">با تلفنی خارج از مرکز به خط ورودی زنگ بزنید و نتیجهٔ همان تماس را ثبت کنید.</p>
              <label>تاریخ تماس<input type="date" name="testedOn" value="${today}" max="${today}" required></label>
              <label>نتیجهٔ تماس<select name="outcome" required><option value="">انتخاب کنید</option>${Object.entries(testOutcomes).map(([status, [label]]) => `<option value="${status}">${label}</option>`).join('')}</select></label>
              <label class="wide">یادداشت اختیاری<textarea name="note" rows="2" maxlength="${maximumNoteLength}" aria-describedby="inbound-note-count"></textarea><span class="small" id="inbound-note-count">${formatCount.format(0)} از ${formatCount.format(maximumNoteLength)} نویسه</span></label>
              <div class="wide"><button class="btn primary" type="submit">ذخیرهٔ نتیجه</button></div>
            </form>
          </details>
        </section>
      </div>`;
    }

    function setReportNotice(text, state) {
      reportNotice = {text, state};
      const message = byId('main-line-message');
      if (!message) return;
      message.textContent = text;
      message.dataset.state = state;
    }

    function refreshReportResults() {
      const target = byId('main-line-results');
      if (target) target.innerHTML = reportResults();
      const clear = document.querySelector('[data-action="readiness-clear-report"]');
      if (clear) clear.hidden = !report;
    }

    async function importReport(file, version) {
      if (file.size > maximumReportSize) {
        setReportNotice('حجم گزارش باید حداکثر ۶۴ کیلوبایت باشد.', 'error');
        return;
      }
      try {
        const data = JSON.parse(await file.text());
        if (version !== uploadVersion) return;
        if (data?.schema === reportSchema && data.number !== mainPhone) {
          setReportNotice(`گزارش باید برای خط اصلی ${mainPhone} باشد.`, 'error');
          return;
        }
        const checked = normalizeReport(data, mainPhone);
        if (!checked) throw new Error('Invalid report');

        report = checked;
        const persisted = writeLocal(reportKey, checked);
        refreshReportResults();
        setReportNotice(persisted ? 'گزارش بررسی بارگذاری و در مرورگر ذخیره شد.' :
          'گزارش بررسی برای همین نشست بارگذاری شد. ذخیره در مرورگر در دسترس نیست.', persisted ? 'success' : 'notice');
      } catch {
        if (version === uploadVersion) setReportNotice('این فایل، گزارش معتبر بررسی خط اصلی نیست.', 'error');
      }
    }

    function updateTestRecord() {
      const target = byId('inbound-test-record');
      if (target) target.innerHTML = testRecord();
    }

    function handleClick(control) {
      const action = control?.dataset.action;
      if (action === 'readiness-pick-report') {
        byId('main-line-report')?.click();
        return true;
      }
      if (action === 'readiness-filter') {
        const status = control.dataset.status;
        if (Object.hasOwn(filterLabels, status) && status !== activeFilter) {
          activeFilter = status;
          document.querySelectorAll('[data-action="readiness-filter"]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.status === activeFilter));
          });
          byId('readiness-check-list').innerHTML = checklist();
        }
        return true;
      }
      if (action === 'readiness-clear-report') {
        if (!report || !window.confirm('گزارش خط اصلی از مرورگر این حساب حذف شود؟')) return true;
        uploadVersion += 1;
        report = null;
        activeFilter = 'all';
        const removed = writeLocal(reportKey, null);
        refreshReportResults();
        document.querySelector('[data-action="readiness-pick-report"]')?.focus();
        setReportNotice(removed ? 'گزارش خط اصلی از مرورگر حذف شد.' : 'گزارش از این نشست پاک شد. حافظهٔ مرورگر در دسترس نیست.', removed ? 'success' : 'notice');
        return true;
      }
      if (action === 'readiness-clear-test') {
        if (!inboundTest || !window.confirm('نتیجهٔ ثبت‌شدهٔ آزمون ورودی از مرورگر این حساب حذف شود؟')) return true;
        inboundTest = null;
        const removed = writeLocal(testKey, null);
        updateTestRecord();
        byId('inbound-test-editor')?.querySelector('summary')?.focus();
        notify(removed ? 'نتیجهٔ آزمون ورودی از مرورگر حذف شد.' : 'نتیجهٔ آزمون از این نشست پاک شد. حافظهٔ مرورگر در دسترس نیست.');
        return true;
      }
      return false;
    }

    function handleChange(target) {
      if (target?.id !== 'main-line-report') return false;
      const file = target.files[0];
      if (file) {
        target.value = '';
        setReportNotice('در حال خواندن گزارش…', 'notice');
        importReport(file, ++uploadVersion);
      }
      return true;
    }

    function handleInput(target) {
      if (target?.form?.id !== 'inbound-test-form' || target.name !== 'note') return false;
      byId('inbound-note-count').textContent = `${formatCount.format(target.value.length)} از ${formatCount.format(maximumNoteLength)} نویسه`;
      return true;
    }

    function handleSubmit(form) {
      if (form?.id !== 'inbound-test-form') return false;
      const values = new FormData(form);
      const checked = normalizeTest({
        number: inboundPhone, savedAt: new Date().toISOString(), testedOn: values.get('testedOn'),
        outcome: values.get('outcome'), note: values.get('note'),
      }, inboundPhone);
      if (!checked) {
        notify('تاریخ تماس و نتیجهٔ آزمون ورودی را بررسی کنید.');
        return true;
      }
      inboundTest = checked;
      const persisted = writeLocal(testKey, checked);
      updateTestRecord();
      form.reset();
      handleInput(form.elements.note);
      const editor = byId('inbound-test-editor');
      editor.open = false;
      editor.querySelector('summary')?.focus();
      notify(persisted ? 'نتیجهٔ تماس ورودی در مرورگر ثبت شد.' : 'نتیجهٔ آزمون برای همین نشست ثبت شد. ذخیره در مرورگر در دسترس نیست.');
      return true;
    }

    return {mainLine, summaryCards, handleClick, handleInput, handleChange, handleSubmit};
  };
})();
