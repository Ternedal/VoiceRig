(() => {
  const MAX_UI_FILES = 20;

  stageNames.reference_audition = 'Laver prøveudtaler';
  stageNames.reference_selection = 'Vælg reference';

  const baseRenderFiles = renderFiles;
  renderFiles = function renderFilesWithCount() {
    baseRenderFiles();
    if (state.files.length) {
      filesEl.appendChild(
        el('div', 'muted tiny', `${state.files.length}/${MAX_UI_FILES} filer valgt`),
      );
    }
  };

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
          `Alle afspillere er genereret tale med profilens valgte sprog/region (${job.language || 'ukendt'}) og samme produktionsmotor. Vælg den prøve, der bedst bevarer stemmeidentiteten — ikke nødvendigvis den med højeste signal-score.`,
        ),
      );

      const grid = el('div', 'speaker-grid');
      for (const reference of job.reference_choices || []) {
        const card = el('div', 'speaker-card');
        const score = Number.isFinite(reference.quality_score)
          ? ` · signal ${reference.quality_score.toFixed(2)}`
          : '';
        const sourceCount = Number(reference.source_clip_count || 1);
        const sources = sourceCount > 1
          ? ` · samlet fra ${sourceCount} klip`
          : ' · fra ét klip';
        const engine = reference.engine_label ? ` · ${reference.engine_label}` : '';
        card.appendChild(
          el(
            'div',
            'voice-name',
            `${reference.label || `Reference ${reference.choice}`} · ca. ${reference.reference_seconds || '?'} sek. reference${sources}${engine}${score}`,
          ),
        );
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'metadata';
        audio.src = `data:audio/wav;base64,${reference.preview_wav_base64}`;
        const choose = el('button', 'secondary', 'Brug denne reference');
        choose.onclick = () => window.chooseReference(reference.choice);
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

  function fileIdentity(file) {
    return `${file.name}\u0000${file.size}\u0000${file.lastModified}\u0000${file.type}`;
  }

  function addFiles(files) {
    const incoming = [...files];
    const merged = [...state.files];
    const known = new Set(merged.map(fileIdentity));
    let duplicateCount = 0;
    let overflowCount = 0;

    for (const file of incoming) {
      const key = fileIdentity(file);
      if (known.has(key)) {
        duplicateCount += 1;
        continue;
      }
      if (merged.length >= MAX_UI_FILES) {
        overflowCount += 1;
        continue;
      }
      merged.push(file);
      known.add(key);
    }

    state.files = merged;
    renderFiles();
    renderButton();

    if (overflowCount) {
      toastMsg(`VoiceRig kan bruge højst ${MAX_UI_FILES} filer. ${overflowCount} fil(er) blev ikke tilføjet.`, true);
    } else if (duplicateCount) {
      toastMsg(`${duplicateCount} dubletfil(er) var allerede valgt og blev sprunget over.`);
    }
  }

  // The base V1 UI replaced the whole selection on every picker/drop action.
  // RC17-style additive selection keeps earlier files and lets the user build a
  // source set in several small batches. Resetting the picker value also lets a
  // removed file be selected again later.
  picker.onchange = () => {
    addFiles(picker.files);
    picker.value = '';
  };

  // Intercept drop in the capture phase so the older app.js bubble listener
  // cannot replace the accumulated selection with only the latest dropped set.
  drop.addEventListener('drop', (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    drop.classList.remove('drag');
    addFiles(event.dataTransfer.files);
  }, true);

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
