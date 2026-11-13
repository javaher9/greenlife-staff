(() => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/customer/sw.js', {scope: '/customer/'}).catch(() => {});
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (standalone) {
    const panel = document.getElementById('school-install');
    if (panel) panel.hidden = true;
    document.querySelectorAll('.activation-form').forEach(form => {
      form.elements.standalone.value = '1';
      form.querySelector('button').disabled = false;
    });
  }
  let prompt;
  const button = document.getElementById('install-button');
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); prompt = event;
    if (button) button.hidden = false;
  });
  if (button) button.addEventListener('click', async () => {
    if (!prompt) return;
    await prompt.prompt();
    const result = await prompt.userChoice;
    if (result.outcome === 'accepted') document.getElementById('install-status').textContent = 'حالا اپ را از صفحهٔ اصلی باز کنید.';
    prompt = null; button.hidden = true;
  });
})();
