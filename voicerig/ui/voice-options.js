(() => {
  const localeSelect = document.querySelector('#voiceLocale');
  const accentField = document.querySelector('#voiceAccentField');
  const accentSelect = document.querySelector('#voiceAccent');
  const accentHelp = document.querySelector('#voiceAccentHelp');
  if (!localeSelect || !accentField || !accentSelect || !accentHelp) return;

  let options = [];

  function selectedLocale() {
    return options.find((item) => item.code === localeSelect.value) || null;
  }

  function accentLabel(localeCode, accentCode) {
    if (!accentCode) return '';
    const locale = options.find((item) => item.code === localeCode);
    const accent = (locale?.accents || []).find((item) => item.code === accentCode);
    return accent?.label || accentCode;
  }

  function renderAccent(preferred = null) {
    const locale = selectedLocale();
    const accents = Array.isArray(locale?.accents) ? locale.accents : [];
    accentSelect.replaceChildren();
    if (!accents.length) {
      accentField.hidden = true;
      accentSelect.disabled = true;
      accentHelp.textContent = '';
      return;
    }

    accentField.hidden = false;
    accentSelect.disabled = false;
    const automatic = document.createElement('option');
    automatic.value = '';
    automatic.textContent = 'Fra reference / ikke angivet';
    accentSelect.appendChild(automatic);
    for (const accent of accents) {
      const option = document.createElement('option');
      option.value = accent.code;
      option.textContent = accent.label;
      accentSelect.appendChild(option);
    }
    if (preferred && accents.some((item) => item.code === preferred)) {
      accentSelect.value = preferred;
    }
    accentHelp.textContent = 'Accentprofilen er reference-led metadata. Chatterbox bruger fortsat language_id=en; den faktiske regionale accent skal være til stede i referenceklippet. VoiceRig gemmer profilen, så en dedikeret regional motor senere kan routes uden formatbrud.';
  }

  function syncJobVoiceOptions(job) {
    if (!job || !options.length) return;
    const locale = options.find((item) => item.code === job.language);
    if (locale) localeSelect.value = locale.code;
    renderAccent(job.accent || null);
  }

  async function loadOptions() {
    try {
      const response = await fetch('/api/voice-options');
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.locales) || !data.locales.length) {
        throw new Error(detail(data.detail || 'Ingen sprogvarianter returneret.'));
      }
      options = data.locales;
      const desiredLocale = state.currentJob?.language || data.default_locale;
      localeSelect.replaceChildren();
      for (const locale of options) {
        const option = document.createElement('option');
        option.value = locale.code;
        option.textContent = locale.label;
        if (locale.code === desiredLocale) option.selected = true;
        localeSelect.appendChild(option);
      }
      if (!options.some((item) => item.code === localeSelect.value)) {
        localeSelect.value = data.default_locale;
      }
      renderAccent(state.currentJob?.accent || null);
    } catch (error) {
      options = [{ code: 'da-DK', label: 'Dansk — Danmark', accents: [] }];
      localeSelect.replaceChildren();
      const option = document.createElement('option');
      option.value = 'da-DK';
      option.textContent = 'Dansk — Danmark';
      localeSelect.appendChild(option);
      accentField.hidden = true;
      accentSelect.disabled = true;
      toastMsg(`Sproglisten kunne ikke indlæses; bruger dansk som fallback: ${error.message}`, true);
    }
  }

  localeSelect.onchange = () => renderAccent();

  async function submitBuildWithVoiceOptions() {
    state.building = true;
    renderButton();
    buildStatus.className = 'status';
    buildStatus.textContent = 'Uploader klippene sikkert til den lokale VoiceRig-jobkø…';
    const form = new FormData();
    form.append('name', nameEl.value.trim());
    form.append('language', localeSelect.value || 'da-DK');
    if (!accentSelect.disabled && accentSelect.value) form.append('accent', accentSelect.value);
    form.append('install_in_modelrig', 'true');
    state.files.forEach((file) => form.append('files', file));
    try {
      const response = await fetch('/api/jobs/voices', { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(detail(data.detail));
      watchJob(data.job);
    } catch (error) {
      state.building = false;
      renderButton();
      buildStatus.className = 'status bad';
      buildStatus.textContent = `Fejl: ${error.message}`;
    }
  }

  // app.js binds the original submitBuild function directly to onclick. Rebind
  // after this deferred script loads so locale/accent values are sent through
  // the exact same persistent-job flow rather than creating a second job path.
  submitBuild = submitBuildWithVoiceOptions;
  createButton.onclick = submitBuildWithVoiceOptions;

  const baseWatchJob = watchJob;
  watchJob = function watchJobWithVoiceOptions(job) {
    syncJobVoiceOptions(job);
    baseWatchJob(job);
  };

  const baseRenderLibrary = renderLibrary;
  renderLibrary = function renderLibraryWithAccentBadges() {
    baseRenderLibrary();
    const voices = state.library?.voices || [];
    const cards = [...document.querySelectorAll('.voice-card')];
    voices.forEach((voice, index) => {
      if (!voice.accent || !cards[index]) return;
      const badges = cards[index].querySelector('.badges');
      if (badges) badges.appendChild(badge(accentLabel(voice.language, voice.accent), 'accent'));
    });
  };

  const baseOpenVoiceTest = openVoiceTest;
  openVoiceTest = function openVoiceTestForLocale(voice) {
    baseOpenVoiceTest(voice);
    const isDanish = String(voice?.language || '').toLowerCase().split('-', 1)[0] === 'da';
    for (const id of ['compareRostVoice', 'compareOmniVoice', 'compareRostReferences']) {
      const button = document.querySelector(`#${id}`);
      if (button) button.hidden = !isDanish;
    }
    if (!isDanish) {
      for (const id of ['rostComparePanel', 'omnivoiceComparePanel', 'rostReferencePanel']) {
        const panel = document.querySelector(`#${id}`);
        if (panel) panel.hidden = true;
      }
    }
    const accent = voice?.accent ? ` · ${accentLabel(voice.language, voice.accent)}` : '';
    testVoiceStatus.textContent = `Tester ${voice.package} · ${voice.language || 'ukendt locale'}${accent} uden at ændre ModelRig-default.`;
  };

  loadOptions();
})();
