(() => {
  const MAX_UI_FILES = 20;

  stageNames.reference_audition = 'Laver danske prøveudtaler';
  stageNames.reference_selection = 'Vælg reference';

  const baseRenderJob = renderJob;
  renderJob = function renderJobWithReferenceChoice(job) {
    if (job && job.state === 'needs_reference') {
      clear(buildStatus);
      state.currentJob = job;
      buildStatus.className = 'status warn';
      buildStatus.appendChild(el('strong', '', job.message || 'Vælg den bedste reference'));
      buildStatus.appendChild(
        el(
          'div',
          'muted tiny',
          'Alle afspillere er genereret dansk tale. Vælg den prøve, der lyder mest naturligt som dig — ikke nødvendigvis den med højeste signal-score.',
        ),
      );

      const grid = el('div', 'speaker-grid');
      for (const reference of job.reference_choices || []) {
        const card = el('div', 'speaker-card');
        const score = Number.isFinite(reference.quality_score)
          ? ` · signal ${reference.quality_score.toFixed(2)}`
          : '';
        card.appendChild(
          el(
            'div',
            'voice-name',
            `${reference.label || `Reference ${reference.choice}`} · ca. ${reference.reference_seconds || '?'} sek. reference${score}`,
          ),
        );
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'metadata';
        audio.src = `data:audio/wav;base64,${reference.preview_wav_base64}`;
        const choose = el('button', 'secondary', 'Brug denne reference');
        choose.onclick = () => chooseReference(reference.choice);
        card.append(audio, choose);
        grid.appendChild(card);
      }
      buildStatus.appendChild(grid);
      const cancel = el('button', 'danger', 'Annullér build');
      cancel.onclick = cancelJob;
      buildStatus.appendChild(cancel);
      return;
    }
    baseRenderJob(job);
  };

  window.chooseReference = async function chooseReference(choice) {
    if (!state.currentJob) return;
    const form = new FormData();
    form.append('choice', String(choice));
    try {
      const response = await fetch(`/api/jobs/${state.currentJob.id}/reference`, {
        method: 'POST',
        body: form,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(detail(data.detail));
      watchJob(data.job);
    } catch (error) {
      toastMsg(`Referencevalg fejlede: ${error.message}`, true);
    }
  };

  function setFiles(files) {
    const all = [...files];
    state.files = all.slice(0, MAX_UI_FILES);
    if (all.length > MAX_UI_FILES) {
      toastMsg(`VoiceRig bruger de første ${MAX_UI_FILES} filer. Fjern nogle filer, hvis du vil vælge andre.`, true);
    }
    renderFiles();
    renderButton();
  }

  picker.onchange = () => setFiles(picker.files);
  drop.addEventListener('drop', (event) => setFiles(event.dataTransfer.files));

  async function resumeReferenceJob() {
    try {
      const response = await fetch('/api/jobs?limit=20');
      const data = await response.json();
      if (!response.ok) return;
      const waiting = (data.jobs || []).find((job) => job.state === 'needs_reference');
      if (!waiting) return;
      nameEl.value = waiting.name || nameEl.value;
      watchJob(waiting);
    } catch (_) {
      // The normal app resume path handles all non-reference states.
    }
  }

  resumeReferenceJob();
})();
