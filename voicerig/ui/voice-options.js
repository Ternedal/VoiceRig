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

  function renderAccent() {
    const locale = selectedLocale();
    const accents = Array.isArray(locale?.accents) ? locale.accents : [];
    accentSelect.replaceChildren();
    if (!accents.length) {
      accentField.hidden = true;
      accentSelect.disabled = true;
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
    accentHelp.textContent = 'Accentprofilen er reference-led metadata. Den aktive Chatterbox-motor bruger fortsat language_id=en; referenceklippet bærer den faktiske regionale accent.';
  }

  async function loadOptions() {
    try {
      const response = await fetch('/api/voice-options');
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.locales) || !data.locales.length) {
        throw new Error(detail(data.detail || 'Ingen sprogvarianter returneret.'));
      }
      options = data.locales;
      localeSelect.replaceChildren();
      for (const locale of options) {
        const option = document.createElement('option');
        option.value = locale.code;
        option.textContent = locale.label;
        if (locale.code === data.default_locale) option.selected = true;
        localeSelect.appendChild(option);
      }
      renderAccent();
    } catch (error) {
      options = [{ code: 'da-DK', label: 'Dansk — Danmark', accents: [] }];
      localeSelect.replaceChildren();
      const option = document.createElement('option');
      option.value = 'da-DK';
      option.textContent = 'Dansk — Danmark';
      localeSelect.appendChild(option);
      accentField.hidden = true;
      toastMsg(`Sproglisten kunne ikke indlæses; bruger dansk som fallback: ${error.message}`, true);
    }
  }

  localeSelect.onchange = renderAccent;

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
  // after this deferred script loads so locale/accent values are sent with the
  // exact same persistent-job flow rather than creating a second code path.
  submitBuild = submitBuildWithVoiceOptions;
  createButton.onclick = submitBuildWithVoiceOptions;

  loadOptions();
})();
