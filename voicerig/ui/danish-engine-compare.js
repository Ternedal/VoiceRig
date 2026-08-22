(() => {
  const button = document.querySelector('#compareRostVoice');
  const panel = document.querySelector('#rostComparePanel');
  const audio = document.querySelector('#rostCompareAudio');
  const status = document.querySelector('#rostCompareStatus');
  if (!button || !panel || !audio || !status) return;

  state.rostCompareAudioUrl = null;

  function resetRostComparison() {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    audio.hidden = true;
    panel.hidden = true;
    status.textContent = '';
    button.disabled = false;
    if (state.rostCompareAudioUrl) {
      URL.revokeObjectURL(state.rostCompareAudioUrl);
      state.rostCompareAudioUrl = null;
    }
  }

  const baseOpenVoiceTest = openVoiceTest;
  openVoiceTest = function openVoiceTestWithRostReset(voice) {
    resetRostComparison();
    baseOpenVoiceTest(voice);
  };

  const baseCloseVoiceTest = closeVoiceTest;
  closeVoiceTest = function closeVoiceTestWithRostReset() {
    resetRostComparison();
    baseCloseVoiceTest();
  };

  async function compareWithRost() {
    const voice = state.testVoice;
    const text = testVoiceText.value.trim();
    if (!voice) return;
    if (!text) {
      status.textContent = 'Skriv en dansk testtekst først.';
      panel.hidden = false;
      return;
    }

    panel.hidden = false;
    button.disabled = true;
    synthesizeVoiceButton.disabled = true;
    status.textContent = 'Starter Røst v3. Første gang hentes ca. 3,2 GB nødvendige modeldata lokalt; derefter bruges cache…';
    try {
      const response = await fetch('/api/tts/compare/rost', {
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
      if (!blob.size) throw new Error('VoiceRig returnerede ingen Røst-lyd.');
      if (state.rostCompareAudioUrl) URL.revokeObjectURL(state.rostCompareAudioUrl);
      state.rostCompareAudioUrl = URL.createObjectURL(blob);
      audio.src = state.rostCompareAudioUrl;
      audio.hidden = false;
      const duration = response.headers.get('X-VoiceRig-Duration') || '?';
      const model = response.headers.get('X-VoiceRig-Model') || 'Røst v3';
      status.textContent = `Klar · ${duration} sek. · ${model}. Sammenlign direkte med “Afspil nuværende motor” ovenfor.`;
      try { await audio.play(); } catch (_) {}
    } catch (error) {
      status.textContent = `Røst-test fejlede: ${error.message}`;
    } finally {
      button.disabled = false;
      synthesizeVoiceButton.disabled = false;
    }
  }

  button.onclick = compareWithRost;
})();
