(() => {
  const panel = document.getElementById('gl-flow');
  if (!panel) return;
  const viewport = panel.querySelector('[data-map-viewport]');
  const control = panel.querySelector('[data-map-tools]');
  const dialog = document.getElementById('gl-map-dialog');
  const expand = control.querySelector('[data-expand]');
  const plus = control.querySelector('[data-zoom="in"]');
  const minus = control.querySelector('[data-zoom="out"]');
  const reset = control.querySelector('[data-zoom="reset"]');
  const anchor = document.createComment('atlas position');
  panel.before(anchor);
  let scale = 100;

  function zoom(next) {
    const halfwayX = (viewport.scrollLeft + viewport.clientWidth / 2) / scale;
    const halfwayY = (viewport.scrollTop + viewport.clientHeight / 2) / scale;
    scale = Math.max(100, Math.min(300, next));
    viewport.style.setProperty('--atlas-width', scale + '%');
    viewport.classList.toggle('flow-zoomed',scale > 100);
    reset.textContent = new Intl.NumberFormat('fa-IR-u-nu-latn').format(scale) + '٪';
    plus.disabled = scale === 300;
    minus.disabled = scale === 100;
    viewport.scrollLeft = halfwayX * scale - viewport.clientWidth / 2;
    viewport.scrollTop = halfwayY * scale - viewport.clientHeight / 2;
  }
  plus.addEventListener('click', () => zoom(scale + 25));
  minus.addEventListener('click', () => zoom(scale - 25));
  reset.addEventListener('click', () => zoom(100));
  expand.addEventListener('click', () => {
    if (dialog.open) { dialog.close(); return; }
    dialog.append(panel);
    dialog.showModal();
    expand.textContent = 'بستن نمای بزرگ';
    expand.setAttribute('aria-expanded', 'true');
    expand.focus();
  });
  dialog.addEventListener('close', () => {
    anchor.after(panel);
    expand.textContent = 'نمای بزرگ';
    expand.setAttribute('aria-expanded', 'false');
    expand.focus();
  });
  zoom(100);
})();
