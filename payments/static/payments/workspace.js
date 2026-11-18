(function () {
  'use strict';
  const a = document.getElementById('paymentTab');
  const b = document.getElementById('expenseTab');
  const c = document.getElementById('requestPanel');
  const d = document.getElementById('expensePanel');
  function setTab(on) {
    if (!a || !b || !c || !d) return;
    a.classList.toggle('on', on); b.classList.toggle('on', !on);
    a.setAttribute('aria-selected', String(on)); b.setAttribute('aria-selected', String(!on));
    c.classList.toggle('hidden', !on); d.classList.toggle('hidden', on);
  }
  if (a && b && c && d) {
    a.addEventListener('click', () => setTab(true));
    b.addEventListener('click', () => setTab(false));
    setTab(d.dataset.active !== 'true');
  }
  const kind = document.getElementById('id_req-kind');
  const recipientFields = document.getElementById('recipientFields');
  function toggleRecipient() {
    if (!kind || !recipientFields) return;
    const petty = kind.value === 'petty_cash';
    recipientFields.classList.toggle('hidden', petty);
    ['id_req-recipient_name', 'id_req-recipient_card', 'id_req-recipient_iban'].forEach(id => {
      const input = document.getElementById(id); if (input) input.disabled = petty;
    });
  }
  if (kind) { kind.addEventListener('change', toggleRecipient); toggleRecipient(); }

  // A normal authorized detail page remains available without JavaScript.
  const dialog = document.getElementById('paymentDetailsDialog');
  const body = document.getElementById('paymentDetailsBody');
  let pending;
  let trigger;
  if (dialog && typeof dialog.showModal === 'function') {
    dialog.querySelector('[data-close-details]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
      if (pending) pending.abort();
      document.body.classList.remove('dialog-open');
      if (trigger && trigger.isConnected) trigger.focus({preventScroll: true});
    });
    document.addEventListener('click', async event => {
      const link = event.target.closest('a[data-payment-detail]');
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      trigger = link;
      if (pending) pending.abort();
      pending = new AbortController();
      const current = pending;
      body.innerHTML = '<p class="dialog-loading" role="status">در حال دریافت سابقه درخواست…</p>';
      body.setAttribute('aria-busy', 'true');
      if (!dialog.open) dialog.showModal();
      document.body.classList.add('dialog-open');
      const url = new URL(link.href, location.href);
      url.hash = ''; url.searchParams.set('panel', '1');
      try {
        const response = await fetch(url, {credentials: 'same-origin', signal: current.signal});
        if (!response.ok || response.redirected) throw new Error('detail unavailable');
        const markup = await response.text();
        if (current !== pending || !dialog.open) return;
        body.innerHTML = markup;
        body.scrollTop = 0;
        const focusSection = link.dataset.detailSection;
        if (focusSection) {
          const section = body.querySelector('[data-detail-section="' + focusSection + '"]');
          if (section) {
            if (section.tagName === 'DETAILS') section.open = true;
            section.scrollIntoView({block: 'start'});
          }
        }
      } catch (error) {
        if (error.name === 'AbortError') return;
        body.replaceChildren();
        const message = document.createElement('div'); message.className = 'dialog-loading';
        const text = document.createElement('p'); text.textContent = 'دریافت جزئیات انجام نشد. صفحه درخواست را باز کنید.';
        const fallback = document.createElement('a'); fallback.className = 'btn'; fallback.href = link.href; fallback.textContent = 'باز کردن صفحه درخواست';
        message.append(text, fallback); body.append(message);
      } finally {
        if (current === pending) body.removeAttribute('aria-busy');
      }
    });
  }
  document.addEventListener('error', event => {
    if (event.target.matches && event.target.matches('img[data-receipt-image]')) event.target.hidden = true;
  }, true);
  document.addEventListener('submit', event => {
    if (event.target.matches('[data-confirm-cancel]') && !window.confirm('این درخواست لغو و از صف پرداخت خارج شود؟ سابقه آن باقی می‌ماند.')) event.preventDefault();
  });
})();
