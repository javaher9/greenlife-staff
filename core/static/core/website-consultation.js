(() => {
  'use strict';
  const form = document.getElementById('websiteLeadForm');
  if (!form) return;
  const phone = form.elements.namedItem('phone');
  const submit = document.getElementById('submitLeadBtn');
  const label = submit.textContent;
  function latinDigits(value) {
    return value.replace(/[۰-۹٠-٩]/g, ch => String(ch.charCodeAt(0) - (ch <= '٩' ? 0x660 : 0x6f0)));
  }
  if (phone) {
    phone.addEventListener('input', () => {
      const normalized = latinDigits(phone.value);
      if (normalized !== phone.value) {
        const start = phone.selectionStart, end = phone.selectionEnd;
        phone.value = normalized;
        if (start !== null) phone.setSelectionRange(start, end);
      }
    });
  }
  form.addEventListener('invalid', event => {
    const details = event.target.closest('details');
    if (details) details.open = true;
  }, true);
  form.addEventListener('submit', event => {
    if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
    if (!form.checkValidity()) return;
    form.dataset.submitting = 'true';
    submit.disabled = true;
    submit.textContent = 'در حال ثبت درخواست…';
  });
  window.addEventListener('pageshow', () => {
    delete form.dataset.submitting;
    submit.disabled = false;
    submit.textContent = label;
  });
  const invalid = form.querySelector('[aria-invalid="true"]');
  if (invalid) {
    const details = invalid.closest('details');
    if (details) details.open = true;
    invalid.focus();
  }
})();
