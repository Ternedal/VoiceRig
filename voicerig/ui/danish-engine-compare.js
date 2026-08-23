(() => {
  const engines = [
    {
      key: 'rost',
      button: document.querySelector('#compareRostVoice'),
      panel: document.querySelector('#rostComparePanel'),
      audio: document.querySelector('#rostCompareAudio'),
      status: document.querySelector('#rostCompareStatus'),
      endpoint: '/api/tts/compare/rost',
      label: 'Røst',
      waiting: 'Starter Røst v3. Første gang hentes ca. 3,2 GB nødvendige modeldata lokalt; derefter bruges cache…',
    },
    {
      key: 'omnivoice',
      button: document.querySelector('#compareOmniVoice'),
      panel: document.querySelector('#omnivoiceComparePanel'),
      audio: document.querySelector('#omnivoiceCompareAudio'),
      status: document.querySelector('#omnivoiceCompareStatus'),
      endpoint: '/api/tts/compare/omnivoice',
      label: 'OmniVoice',
      waiting: 'Starter OmniVoice. Første gang oprettes et isoleret runtime-miljø og pinnede OmniVoice/Whisper-modeller hentes lokalt; det kan tage flere minutter…',
    },
  ];

  const rostReferenceButton = document.querySelector('#compareRostReferences');
  const rostReferencePanel = document.querySelector('#rostReferencePanel');
  const rostReferenceChoices = document.querySelector('#rostReferenceChoices');
  const rostReferenceStatus = document.querySelector('#rostReferenceStatus');

  if (
    engines.some((engine) => !engine.button || !engine.panel || !engine.audio || !engine.status)
    || !rostReferenceButton || !rostReferencePanel || !rostReferenceChoices || !rostReferenceStatus
  ) return;

  for (const engine of engines) state[`${engine.key}CompareAudioUrl`] = null;
  state.rostReferenceAudioUrls = [];

  function resetEngine(engine) {
    engine.audio.pause();
    engine.audio.removeAttribute('src');
    engine.audio.load();
    engine.audio.hidden = true;
    engine.panel.hidden = true;
    engine.status.textContent = '';
    engine.button.disabled = false;
    const stateKey = `${engine.key}CompareAudioUrl`;
    if (state[stateKey]) {
      URL.revokeObjectURL(state[stateKey]);
      state[stateKey] = null;
    }
  }

  function resetRostReferences() {
    for (const url of state.rostReferenceAudioUrls) URL.revokeObjectURL(url);
    state.rostReferenceAudioUrls = [];
    rostReferenceChoices.innerHTML = '';
    rostReferenceStatus.textContent = '';
    rostReferencePanel.hidden = true;
    rostReferenceButton.disabled = false;
  }

  function resetComparisons() {
    for (const engine of engines) resetEngine(engine);
    resetRostReferences();
  }

  function setComparisonBusy(busy) {
    synthesizeVoiceButton.disabled = busy;
    for (const engine of engines) engine.button.disabled = busy;
    rostReferenceButton.disabled = busy;
    for (const button of rostReferenceChoices.querySelectorAll('button')) button.disabled = busy;
  }

  const baseOpenVoiceTest = openVoiceTest;
  openVoiceTest = function openVoiceTestWithComparisonReset(voice) {
    resetComparisons();
    baseOpenVoiceTest(voice);
  };

  const baseCloseVoiceTest = closeVoiceTest;
  closeVoiceTest = function closeVoiceTestWithComparisonReset() {
    resetComparisons();
    baseCloseVoiceTest();
  };

  function decodedHeader(value, fallback) {
    if (!value) return fallback;
    try { return decodeURIComponent(value); } catch (_) { return value; }
  }

  async function responseError(response) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      message = detail(data.detail);
    } catch (_) {}
    return message;
  }

  async function compare(engine) {
    const voice = state.testVoice;
    const text = testVoiceText.value.trim();
    if (!voice) return;
    if (!text) {
      engine.status.textContent = 'Skriv en dansk testtekst først.';
      engine.panel.hidden = false;
      return;
    }

    engine.panel.hidden = false;
    setComparisonBusy(true);
    engine.status.textContent = engine.waiting;
    try {
      const response = await fetch(engine.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice_package: voice.package }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const blob = await response.blob();
      if (!blob.size) throw new Error(`VoiceRig returnerede ingen ${engine.label}-lyd.`);
      const stateKey = `${engine.key}CompareAudioUrl`;
      if (state[stateKey]) URL.revokeObjectURL(state[stateKey]);
      state[stateKey] = URL.createObjectURL(blob);
      engine.audio.src = state[stateKey];
      engine.audio.hidden = false;
      const duration = response.headers.get('X-VoiceRig-Duration') || '?';
      const model = decodedHeader(response.headers.get('X-VoiceRig-Model'), engine.label);
      engine.status.textContent = `Klar · ${duration} sek. · ${model}. Brug præcis samme tekst til alle motorer.`;
      try { await engine.audio.play(); } catch (_) {}
    } catch (error) {
      engine.status.textContent = `${engine.label}-test fejlede: ${error.message}`;
    } finally {
      setComparisonBusy(false);
    }
  }

  function makeRostReferenceRow(reference) {
    const row = document.createElement('div');
    row.className = 'status';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = `Afspil ${reference.label}`;

    const audio = document.createElement('audio');
    audio.controls = true;
    audio.hidden = true;

    const status = document.createElement('div');
    status.className = 'muted tiny';

    button.onclick = async () => {
      const voice = state.testVoice;
      const text = testVoiceText.value.trim();
      if (!voice) return;
      if (!text) {
        status.textContent = 'Skriv en dansk testtekst først.';
        return;
      }
      setComparisonBusy(true);
      status.textContent = `Genererer ${reference.label} med samme Røst-model og parametre…`;
      try {
        const response = await fetch('/api/tts/compare/rost/reference', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text,
            voice_package: voice.package,
            reference_index: reference.index,
          }),
        });
        if (!response.ok) throw new Error(await responseError(response));
        const blob = await response.blob();
        if (!blob.size) throw new Error('VoiceRig returnerede ingen Røst-lyd.');
        const url = URL.createObjectURL(blob);
        state.rostReferenceAudioUrls.push(url);
        audio.src = url;
        audio.hidden = false;
        const duration = response.headers.get('X-VoiceRig-Duration') || '?';
        status.textContent = `Klar · ${duration} sek. · ${reference.label}. Lyt efter hvilken prøve der ligner stemmen mest.`;
        try { await audio.play(); } catch (_) {}
      } catch (error) {
        status.textContent = `${reference.label} fejlede: ${error.message}`;
      } finally {
        setComparisonBusy(false);
      }
    };

    row.append(button, audio, status);
    return row;
  }

  async function loadRostReferences() {
    const voice = state.testVoice;
    if (!voice) return;
    rostReferencePanel.hidden = false;
    setComparisonBusy(true);
    rostReferenceStatus.textContent = 'Finder de gemte referencekandidater i stemmeprofilen…';
    try {
      const response = await fetch('/api/tts/compare/rost/references', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_package: voice.package }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json();
      const references = Array.isArray(data.references) ? data.references : [];
      if (!references.length) throw new Error('Stemmeprofilen indeholder ingen brugbare referencer.');
      rostReferenceChoices.innerHTML = '';
      for (const reference of references) rostReferenceChoices.appendChild(makeRostReferenceRow(reference));
      rostReferenceStatus.textContent = references.length > 1
        ? `Klar: ${references.length} referencer. Brug samme tekst og find den der ligner stemmen mest.`
        : 'Profilen indeholder kun den primære reference; der er ingen backup-reference at sammenligne med.';
    } catch (error) {
      rostReferenceStatus.textContent = `Røst-referencer kunne ikke indlæses: ${error.message}`;
    } finally {
      setComparisonBusy(false);
    }
  }

  for (const engine of engines) engine.button.onclick = () => compare(engine);
  rostReferenceButton.onclick = loadRostReferences;
})();
