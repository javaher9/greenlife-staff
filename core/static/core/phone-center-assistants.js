'use strict';

window.createPhoneCenterAssistants = function (workspace) {
  const template = document.getElementById('phone-assistants-template');
  const samples = new Map();
  const rows = () => [...workspace.querySelectorAll('[data-assistant]')];
  const player = row => row.querySelector('audio');
  const status = (row, message) => {
    row.querySelector('.assistant-audio-status').textContent = message;
  };

  function attachSample(row, sample) {
    player(row).src = sample.url;
    const play = row.querySelector('.assistant-play');
    play.disabled = false;
    play.classList.add('primary');
    row.querySelector('[data-action="assistant-choose"]').classList.remove('primary');
    status(row, 'آمادهٔ پخش · ' + sample.name);
  }

  function restore() {
    rows().forEach(row => {
      const audio = player(row);
      const play = row.querySelector('.assistant-play');
      const name = row.querySelector('h3').textContent;
      const reflectPlayback = () => {
        const active = !audio.paused && !audio.ended;
        const label = active ? 'توقف پخش' : 'پخش نمونه';
        play.setAttribute('aria-label', label + ' ' + name);
        play.querySelector('.assistant-play-icon').textContent = active ? '⏸︎' : '▶︎';
        play.querySelector('.assistant-play-text').textContent = label;
      };
      ['play', 'pause', 'ended'].forEach(event => audio.addEventListener(event, reflectPlayback));
      const sample = samples.get(row.dataset.assistant);
      if (sample) attachSample(row, sample);
    });
  }

  function handleClick(control) {
    const row = control.closest('[data-assistant]');
    if (!row) return false;
    if (control.dataset.action === 'assistant-choose') {
      row.querySelector('.assistant-file').click();
      return true;
    }
    if (control.dataset.action !== 'assistant-play') return false;

    const audio = player(row);
    if (audio.paused) {
      rows().forEach(other => {
        if (other !== row) player(other).pause();
      });
      audio.play().catch(error => {
        if (row.isConnected && error.name !== 'AbortError') {
          status(row, 'پخش فایل ممکن نبود. یک فایل WAV یا MP3 سالم انتخاب کنید.');
        }
      });
    } else {
      audio.pause();
    }
    return true;
  }

  function handleChange(input) {
    if (!input.matches('.assistant-file')) return false;
    const file = input.files[0];
    if (!file) return true;
    const row = input.closest('[data-assistant]');
    if (!/\.(wav|mp3)$/i.test(file.name) || file.size === 0 || file.size > 10 * 1024 * 1024) {
      status(row, 'یک فایل WAV یا MP3 تا ۱۰ مگابایت انتخاب کنید.');
    } else {
      const id = row.dataset.assistant;
      const previous = samples.get(id);
      const sample = {url: URL.createObjectURL(file), name: file.name};
      player(row).pause();
      samples.set(id, sample);
      attachSample(row, sample);
      if (previous) URL.revokeObjectURL(previous.url);
    }
    input.value = '';
    return true;
  }

  return {
    view: () => template.innerHTML,
    pause: () => rows().forEach(row => player(row).pause()),
    restore,
    handleClick,
    handleChange
  };
};
