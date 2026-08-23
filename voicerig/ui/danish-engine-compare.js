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

  if (engines.some((engine) => !engine.button || !engine.panel || !engine.audio || !engine.status)) return;

  for (const engine of engines) state[`${engine.key}CompareAudioUrl`] = null;

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

  function resetComparisons() {
    for (const engine of engines) resetEngine(engine);
  }

  function setComparisonBusy(busy) {
    synthesizeVoiceButton.disabled = busy;
    for (const engine of engines) engine.button.disabled = busy;
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
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const data = await response.json();
          message = detail(data.detail);
        } catch (_) {}
        throw new Error(message);
      }
      const blob = await response.blob();
      if (!blob.size) throw new Error(`VoiceRig returnerede ingen ${engine.label}-lyd.`);
      const stateKey = `${engine.key}CompareAudioUrl`;
      if (state[stateKey]) URL.revokeObjectURL(state[stateKey]);
      state[stateKey] = URL.createObjectURL(blob);
      engine.audio.src = state[stateKey];
      engine.audio.hidden = false;
      const duration = response.headers.get('X-VoiceRig-Duration') || '?';
      const model = decodedHeader(response.headers.get('X-VoiceRig-Model'), engine.label);
      engine.status.textContent = `Klar · ${duration} sek. · ${model}. Brug præcis samme tekst til alle tre motorer.`;
      try { await engine.audio.play(); } catch (_) {}
    } catch (error) {
      engine.status.textContent = `${engine.label}-test fejlede: ${error.message}`;
    } finally {
      setComparisonBusy(false);
    }
  }

  for (const engine of engines) {
    engine.button.onclick = () => compare(engine);
  }
})();
