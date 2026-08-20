const state = {
  files: [],
  runtimeReady: false,
  building: false,
  readiness: null,
  health: null,
  library: null,
  modelrig: null,
  modelrigConfig: null,
  currentJob: null,
  pollTimer: null,
  testVoice: null,
  testAudioUrl: null,
};

const $ = (selector) => document.querySelector(selector);
const picker = $('#picker');
const drop = $('#drop');
const filesEl = $('#files');
const nameEl = $('#name');
const createButton = $('#create');
const buildStatus = $('#buildStatus');
const readinessEl = $('#readiness');
const headerState = $('#headerState');
const libraryEl = $('#library');
const invalidEl = $('#invalidProfiles');
const importPicker = $('#importPicker');
const systemGrid = $('#systemGrid');
const systemMessages = $('#systemMessages');
const toast = $('#toast');
const voiceTester = $('#voiceTester');
const testVoiceName = $('#testVoiceName');
const testVoiceText = $('#testVoiceText');
const testVoiceStatus = $('#testVoiceStatus');
const testVoiceAudio = $('#testVoiceAudio');
const synthesizeVoiceButton = $('#synthesizeVoice');
const modelrigTokenInput = $('#modelrigToken');
const modelrigTokenState = $('#modelrigTokenState');
const saveModelrigTokenButton = $('#saveModelrigToken');
const clearModelrigTokenButton = $('#clearModelrigToken');

function clear(node) {
  node.replaceChildren();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function detail(value) {
  if (typeof value === 'string') return value;
  if (value && typeof value.message === 'string') return value.message;
  return 'Ukendt fejl';
}

function bytes(value) {
  if (!Number.isFinite(value)) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1048576).toFixed(1)} MB`;
}

function toastMsg(message, bad = false) {
  toast.textContent = message;
  toast.className = bad ? 'show bad' : 'show';
  clearTimeout(toastMsg.timer);
  toastMsg.timer = setTimeout(() => { toast.className = ''; }, 4200);
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === name);
  });
  document.querySelectorAll('.panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `panel-${name}`);
  });
  if (name === 'library') refreshLibrary();
  if (name === 'system') refreshSystem();
}

document.querySelectorAll('.tab').forEach((button) => {
  button.onclick = () => switchTab(button.dataset.tab);
});

function renderFiles() {
  clear(filesEl);
  state.files.forEach((file, index) => {
    const row = el('div', 'file-row');
    const fileName = el('div', 'file-name', file.name);
    const size = el('span', 'muted tiny', bytes(file.size));
    const remove = el('button', 'iconbtn', 'Fjern');
    remove.onclick = () => {
      state.files.splice(index, 1);
      renderFiles();
      renderButton();
    };
    row.append(fileName, size, remove);
    filesEl.appendChild(row);
  });
}

function renderButton() {
  createButton.disabled = state.building || !state.runtimeReady || !state.files.length || !nameEl.value.trim();
}

function renderReadiness() {
  const data = state.readiness || {};
  const hardware = data.hardware || {};
  clear(readinessEl);

  const dot = el('span', `dot ${data.ready ? 'ok' : 'warn'}`);
  const body = el('div');
  body.appendChild(el('strong', '', data.ready ? 'Klar til at oprette stemmer' : 'Opsætningen er ikke klar endnu'));
  const parts = [hardware.gpu || 'GPU ikke fundet'];
  if (hardware.vram_total_gb) parts.push(`${hardware.vram_total_gb} GB VRAM`);
  parts.push('speaker-analyse på CPU');
  const reason = data.ready ? (data.warnings || [])[0] : (data.blockers || [])[0];
  body.appendChild(el('div', 'muted tiny', parts.join(' · ') + (reason ? ` · ${reason}` : '')));
  readinessEl.append(dot, body);

  state.runtimeReady = Boolean(data.ready);
  renderButton();
  clear(headerState);
  headerState.append(
    el('span', `dot ${data.ready ? 'ok' : 'warn'}`),
    el('span', '', data.ready ? 'System klar' : 'Opsætning mangler'),
  );
}

const stageNames = {
  queued: 'I kø',
  starting: 'Starter',
  decoding: 'Normaliserer lyd/video',
  diarization: 'Finder speakers',
  speaker_selection: 'Speaker-valg',
  reference: 'Vælger reference',
  conditioning: 'Bygger stemme',
  packaging: 'Pakker profil',
  installing: 'Installerer i ModelRig',
  complete: 'Færdig',
  cancelling: 'Annullerer',
};

function renderJob(job) {
  clear(buildStatus);
  state.currentJob = job;
  const status = job.state;

  if (status === 'needs_speaker') {
    buildStatus.className = 'status warn';
    buildStatus.appendChild(el('strong', '', job.message || 'Vælg speaker'));
    const grid = el('div', 'speaker-grid');
    for (const speaker of job.speaker_choices || []) {
      const card = el('div', 'speaker-card');
      card.appendChild(el('div', 'voice-name', `${speaker.label || 'Stemme'} · ca. ${speaker.speech_seconds || '?'} sek. tale`));
      const audio = document.createElement('audio');
      audio.controls = true;
      audio.preload = 'metadata';
      audio.src = `data:audio/wav;base64,${speaker.preview_wav_base64}`;
      const choose = el('button', 'secondary', 'Brug denne stemme');
      choose.onclick = () => chooseSpeaker(speaker.anchor);
      card.append(audio, choose);
      grid.appendChild(card);
    }
    buildStatus.appendChild(grid);
    const cancel = el('button', 'danger', 'Annullér build');
    cancel.onclick = cancelJob;
    buildStatus.appendChild(cancel);
    return;
  }

  if (status === 'succeeded') {
    buildStatus.className = 'status good';
    const result = job.result || {};
    const voice = result.voice || {};
    buildStatus.textContent = `✓ ${voice.name || job.name} er klar.${result.installed_in_modelrig ? ' Den er aktiv i ModelRig.' : ' Profilen er gemt lokalt.'}`;
    finishJob(true);
    return;
  }
  if (status === 'failed') {
    buildStatus.className = 'status bad';
    buildStatus.textContent = `Fejl: ${job.error || job.message || 'Voice-build fejlede.'}`;
    finishJob(false);
    return;
  }
  if (status === 'cancelled') {
    buildStatus.className = 'status warn';
    buildStatus.textContent = job.message || 'Voice-build blev annulleret.';
    finishJob(false);
    return;
  }

  buildStatus.className = 'status';
  buildStatus.appendChild(el('strong', '', job.message || stageNames[job.stage] || 'Arbejder…'));
  const progress = el('div', 'progress');
  const fill = el('div');
  fill.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
  progress.appendChild(fill);
  buildStatus.appendChild(progress);
  const actions = el('div', 'job-actions');
  actions.append(el('span', 'muted tiny', `${stageNames[job.stage] || job.stage || 'Job'} · ${job.progress || 0}%`));
  const cancel = el('button', 'danger', 'Annullér');
  cancel.onclick = cancelJob;
  actions.appendChild(cancel);
  buildStatus.appendChild(actions);
}

async function pollJob() {
  if (!state.currentJob) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(state.currentJob.id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    renderJob(data.job);
    if (['queued', 'running', 'cancelling'].includes(data.job.state)) {
      state.pollTimer = setTimeout(pollJob, 800);
    }
  } catch (error) {
    buildStatus.className = 'status bad';
    buildStatus.textContent = `Kunne ikke hente jobstatus: ${error.message}`;
    state.pollTimer = setTimeout(pollJob, 1800);
  }
}

function watchJob(job) {
  clearTimeout(state.pollTimer);
  state.currentJob = job;
  state.building = true;
  renderButton();
  renderJob(job);
  if (['queued', 'running', 'cancelling'].includes(job.state)) {
    state.pollTimer = setTimeout(pollJob, 350);
  }
}

function finishJob(success) {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.currentJob = null;
  state.building = false;
  renderButton();
  if (success) {
    state.files = [];
    renderFiles();
    refreshLibrary();
    refreshSystem();
  }
}

async function submitBuild() {
  state.building = true;
  renderButton();
  buildStatus.className = 'status';
  buildStatus.textContent = 'Uploader klippene sikkert til den lokale VoiceRig-jobkø…';
  const form = new FormData();
  form.append('name', nameEl.value.trim());
  form.append('language', 'da');
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

async function chooseSpeaker(anchor) {
  if (!state.currentJob) return;
  const form = new FormData();
  form.append('anchor', anchor);
  try {
    const response = await fetch(`/api/jobs/${state.currentJob.id}/speaker`, { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    watchJob(data.job);
  } catch (error) {
    toastMsg(`Speaker-valg fejlede: ${error.message}`, true);
  }
}

async function cancelJob() {
  if (!state.currentJob) return;
  try {
    const response = await fetch(`/api/jobs/${state.currentJob.id}/cancel`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    renderJob(data.job);
    if (data.job.state === 'cancelling') state.pollTimer = setTimeout(pollJob, 500);
  } catch (error) {
    toastMsg(`Kunne ikke annullere: ${error.message}`, true);
  }
}

async function resumeJob() {
  try {
    const response = await fetch('/api/jobs?limit=20');
    const data = await response.json();
    if (!response.ok) return;
    const active = (data.jobs || []).find((job) => ['queued', 'running', 'needs_speaker', 'cancelling'].includes(job.state));
    if (active) {
      nameEl.value = active.name || '';
      watchJob(active);
    }
  } catch (_) {
    // A missing historic job should not block the UI from loading.
  }
}

function openVoiceTest(voice) {
  state.testVoice = voice;
  voiceTester.hidden = false;
  testVoiceName.textContent = voice.name;
  testVoiceStatus.textContent = `Tester ${voice.package} uden at ændre ModelRig-default.`;
  testVoiceAudio.hidden = true;
  if (state.testAudioUrl) {
    URL.revokeObjectURL(state.testAudioUrl);
    state.testAudioUrl = null;
  }
  voiceTester.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  testVoiceText.focus();
}

function closeVoiceTest() {
  state.testVoice = null;
  voiceTester.hidden = true;
  testVoiceStatus.textContent = '';
  testVoiceAudio.pause();
  testVoiceAudio.removeAttribute('src');
  testVoiceAudio.load();
  if (state.testAudioUrl) {
    URL.revokeObjectURL(state.testAudioUrl);
    state.testAudioUrl = null;
  }
}

async function synthesizeVoiceTest() {
  const voice = state.testVoice;
  const text = testVoiceText.value.trim();
  if (!voice) return;
  if (!text) {
    testVoiceStatus.textContent = 'Skriv en tekst først.';
    return;
  }

  synthesizeVoiceButton.disabled = true;
  testVoiceStatus.textContent = 'Genererer testlyd lokalt…';
  try {
    const response = await fetch('/api/tts/synthesize', {
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
    if (!blob.size) throw new Error('VoiceRig returnerede ingen lyd.');
    if (state.testAudioUrl) URL.revokeObjectURL(state.testAudioUrl);
    state.testAudioUrl = URL.createObjectURL(blob);
    testVoiceAudio.src = state.testAudioUrl;
    testVoiceAudio.hidden = false;
    testVoiceStatus.textContent = `Klar · ${response.headers.get('X-VoiceRig-Duration') || '?'} sek. · ${response.headers.get('X-VoiceRig-Device') || 'lokal runtime'}`;
    try { await testVoiceAudio.play(); } catch (_) {}
  } catch (error) {
    testVoiceStatus.textContent = `Test fejlede: ${error.message}`;
  } finally {
    synthesizeVoiceButton.disabled = false;
  }
}

function badge(text, extra = '') {
  return el('span', `badge ${extra}`.trim(), text);
}

function renderLibrary() {
  clear(libraryEl);
  clear(invalidEl);
  const data = state.library || { voices: [], invalid: [] };
  if (!data.voices.length) {
    libraryEl.appendChild(el('div', 'empty', 'Ingen stemmer endnu. Opret en stemme eller importér en .mrvoice.'));
  }

  for (const voice of data.voices) {
    const card = el('article', 'voice-card');
    const top = el('div', 'voice-top');
    const left = el('div');
    left.append(el('div', 'voice-name', voice.name), el('div', 'muted tiny', voice.package));
    const badges = el('div', 'badges');
    if (voice.is_default) badges.appendChild(badge('Aktiv', 'default'));
    if (voice.installed_in_modelrig) badges.appendChild(badge('ModelRig'));
    if (voice.in_library) badges.appendChild(badge('VoiceRig'));
    top.append(left, badges);
    card.appendChild(top);
    card.appendChild(el('div', 'muted tiny', `${voice.language} · ${(voice.engine || {}).model || 'model'} · ${bytes(voice.size_bytes)}`));

    const audio = document.createElement('audio');
    audio.controls = true;
    audio.preload = 'none';
    audio.src = voice.preview_url;
    card.appendChild(audio);

    const actions = el('div', 'actions');
    const test = el('button', 'secondary', 'Test stemme');
    test.onclick = () => openVoiceTest(voice);
    actions.appendChild(test);
    if (!voice.is_default) {
      const activate = el('button', 'secondary', 'Brug i ModelRig');
      activate.onclick = () => activateVoice(voice.package);
      actions.appendChild(activate);
    }
    const download = el('a', 'secondary', 'Eksportér');
    download.href = voice.download_url;
    download.download = voice.package;
    actions.appendChild(download);
    const remove = el('button', 'danger', 'Slet');
    remove.onclick = () => deleteVoice(voice);
    actions.appendChild(remove);
    card.appendChild(actions);
    libraryEl.appendChild(card);
  }

  if ((data.invalid || []).length) {
    const box = el('div', 'invalid-box');
    box.appendChild(el('strong', '', 'Profiler med fejl'));
    for (const item of data.invalid) box.appendChild(el('div', 'tiny', `${item.package}: ${item.detail}`));
    invalidEl.appendChild(box);
  }
}

async function refreshLibrary() {
  try {
    const response = await fetch('/api/voices');
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    state.library = data;
    renderLibrary();
  } catch (error) {
    clear(libraryEl);
    libraryEl.appendChild(el('div', 'empty', `Kunne ikke hente stemmer: ${error.message}`));
  }
}

async function activateVoice(packageName) {
  try {
    const response = await fetch(`/api/voices/${encodeURIComponent(packageName)}/default`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    toastMsg(`${data.voice.name} er nu aktiv i ModelRig.`);
    await refreshLibrary();
    await refreshSystem();
  } catch (error) {
    toastMsg(`Kunne ikke aktivere stemmen: ${error.message}`, true);
  }
}

async function deleteVoice(voice) {
  if (!confirm(`Slet stemmen “${voice.name}”? Profilen fjernes både fra VoiceRig og ModelRig på denne maskine.`)) return;
  try {
    const response = await fetch(`/api/voices/${encodeURIComponent(voice.package)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    if (state.testVoice && state.testVoice.package === voice.package) closeVoiceTest();
    toastMsg(`${voice.name} er slettet.`);
    await refreshLibrary();
    await refreshSystem();
  } catch (error) {
    toastMsg(`Kunne ikke slette stemmen: ${error.message}`, true);
  }
}

async function importVoice(file) {
  const form = new FormData();
  form.append('voice', file);
  form.append('make_default', 'false');
  try {
    toastMsg('Importerer stemme…');
    const response = await fetch('/api/voices/import', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    toastMsg(`${data.voice.name} er importeret.`);
    await refreshLibrary();
    switchTab('library');
  } catch (error) {
    toastMsg(`Import fejlede: ${error.message}`, true);
  } finally {
    importPicker.value = '';
  }
}

function metric(title, value, description = '') {
  const box = el('div', 'metric');
  box.append(el('div', 'muted tiny', title), el('div', 'metric-value', value || '—'));
  if (description) box.appendChild(el('div', 'metric-detail', description));
  systemGrid.appendChild(box);
}

function renderModelrigConfig() {
  const configured = Boolean(state.modelrigConfig && state.modelrigConfig.token_configured);
  modelrigTokenState.textContent = configured
    ? 'Et ModelRig-token er gemt lokalt. Værdien vises aldrig igen.'
    : 'Intet ModelRig-token er gemt. Det er kun nødvendigt, hvis ModelRig kræver backend-auth.';
  modelrigTokenInput.placeholder = configured ? 'Indsæt nyt token for at erstatte det' : 'Indsæt ModelRig device-token';
  clearModelrigTokenButton.disabled = !configured;
}

function renderSystem() {
  clear(systemGrid);
  clear(systemMessages);
  const readiness = state.readiness || {};
  const hardware = readiness.hardware || {};
  const health = state.health || {};
  const models = readiness.models || {};
  const tts = health.tts || {};
  const source = health.source || readiness.source || {};
  const modelrig = state.modelrig || {};
  const modelrigTts = modelrig.tts || {};

  metric('VoiceRig', health.version || '—', `PID ${health.pid || '—'}`);
  metric('GPU', hardware.gpu || 'Ikke fundet', hardware.vram_total_gb ? `${hardware.vram_total_gb} GB VRAM · ${hardware.vram_free_gb ?? '—'} GB fri` : hardware.cuda_available ? 'CUDA fundet' : 'CUDA ikke klar');
  metric('Chatterbox', hardware.chatterbox_device || '—', models.verified ? 'Modelcache verificeret' : 'Modelcache ikke verificeret');
  metric('Speaker-analyse', hardware.diarization_available ? 'Klar' : 'Mangler', `${hardware.diarization_device || 'cpu'} · separat runtime`);
  metric('VoiceRig aktiv stemme', tts.voice || 'Ingen', tts.package || tts.detail || 'Ingen aktiv .mrvoice');
  metric('ModelRig', !modelrig.configured ? 'Ikke konfigureret' : !modelrig.reachable ? 'Offline' : (modelrigTts.provider || 'Online'), modelrigTts.package || modelrigTts.voice || modelrig.detail || modelrig.base_url || '');
  metric('ModelRig auth', state.modelrigConfig && state.modelrigConfig.token_configured ? 'Token gemt' : 'Intet token', 'Tokenværdien returneres aldrig fra VoiceRig');
  metric('Git revision', source.revision || source.head || '—', source.clean === false ? 'Checkout har ændringer' : 'Service source identity');

  const messages = [...(readiness.blockers || []), ...(readiness.warnings || [])];
  if (messages.length) {
    const box = el('div', 'status warn');
    messages.forEach((message) => box.appendChild(el('div', '', message)));
    systemMessages.appendChild(box);
  }

  const desired = state.library && state.library.default_package;
  const needsRepair = modelrig.configured && (
    !modelrig.reachable ||
    !modelrigTts.ok ||
    modelrigTts.provider !== 'voicerig' ||
    (desired && modelrigTts.package && modelrigTts.package !== desired)
  );
  if (needsRepair) {
    const box = el('div', 'status warn system-action');
    const text = el('div');
    text.append(
      el('strong', '', 'ModelRig bruger ikke den forventede VoiceRig-stemme'),
      el('div', 'tiny muted', modelrig.detail || modelrigTts.detail || 'Reinstallér den aktive profil og kontrollér status igen.'),
    );
    const repair = el('button', 'secondary', 'Reparér ModelRig');
    repair.onclick = repairModelRig;
    box.append(text, repair);
    systemMessages.appendChild(box);
  }
  renderModelrigConfig();
}

async function refreshSystem() {
  try {
    const [readinessResponse, healthResponse, modelrigResponse, configResponse] = await Promise.all([
      fetch('/api/readiness'),
      fetch('/api/health'),
      fetch('/api/modelrig/status'),
      fetch('/api/modelrig/config'),
    ]);
    if (!readinessResponse.ok || !healthResponse.ok || !modelrigResponse.ok || !configResponse.ok) {
      throw new Error('Et eller flere status-endpoints fejlede.');
    }
    state.readiness = await readinessResponse.json();
    state.health = await healthResponse.json();
    state.modelrig = await modelrigResponse.json();
    state.modelrigConfig = await configResponse.json();
    renderReadiness();
    renderSystem();
  } catch (error) {
    clear(systemGrid);
    systemGrid.appendChild(el('div', 'empty', `Kunne ikke hente systemstatus: ${error.message}`));
  }
}

async function repairModelRig() {
  try {
    toastMsg('Reparerer ModelRig…');
    const form = new FormData();
    const defaultPackage = state.library && state.library.default_package;
    if (defaultPackage) form.append('package', defaultPackage);
    const response = await fetch('/api/modelrig/repair', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    await refreshLibrary();
    await refreshSystem();
    toastMsg(data.ok ? 'ModelRig er repareret og VoiceRig er aktiv.' : 'Profilen blev installeret, men ModelRig er stadig ikke klar.', !data.ok);
  } catch (error) {
    toastMsg(`ModelRig-reparation fejlede: ${error.message}`, true);
  }
}

async function saveModelrigToken() {
  const token = modelrigTokenInput.value.trim();
  if (!token) {
    toastMsg('Indsæt et token, eller brug “Ryd token”.', true);
    return;
  }
  saveModelrigTokenButton.disabled = true;
  clearModelrigTokenButton.disabled = true;
  try {
    const form = new FormData();
    form.append('token', token);
    const response = await fetch('/api/modelrig/config', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    modelrigTokenInput.value = '';
    state.modelrigConfig = { ok: true, token_configured: Boolean(data.token_configured) };
    state.modelrig = data.modelrig || state.modelrig;
    renderSystem();
    toastMsg(data.modelrig && data.modelrig.ok ? 'ModelRig-token gemt og forbindelsen er klar.' : 'ModelRig-token gemt. ModelRig er endnu ikke helt klar.', !(data.modelrig && data.modelrig.ok));
  } catch (error) {
    modelrigTokenInput.value = '';
    toastMsg(`Kunne ikke gemme ModelRig-token: ${error.message}`, true);
  } finally {
    saveModelrigTokenButton.disabled = false;
    renderModelrigConfig();
  }
}

async function clearModelrigToken() {
  clearModelrigTokenButton.disabled = true;
  saveModelrigTokenButton.disabled = true;
  try {
    const form = new FormData();
    form.append('token', '');
    const response = await fetch('/api/modelrig/config', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(detail(data.detail));
    modelrigTokenInput.value = '';
    state.modelrigConfig = { ok: true, token_configured: false };
    state.modelrig = data.modelrig || state.modelrig;
    renderSystem();
    toastMsg('ModelRig-token er ryddet fra VoiceRig.');
  } catch (error) {
    toastMsg(`Kunne ikke rydde ModelRig-token: ${error.message}`, true);
  } finally {
    saveModelrigTokenButton.disabled = false;
    renderModelrigConfig();
  }
}

picker.onchange = () => {
  state.files = [...picker.files].slice(0, 10);
  renderFiles();
  renderButton();
};
nameEl.oninput = renderButton;
createButton.onclick = submitBuild;
drop.onclick = () => picker.click();
drop.onkeydown = (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    picker.click();
  }
};
['dragenter', 'dragover'].forEach((name) => drop.addEventListener(name, (event) => {
  event.preventDefault();
  drop.classList.add('drag');
}));
['dragleave', 'drop'].forEach((name) => drop.addEventListener(name, (event) => {
  event.preventDefault();
  drop.classList.remove('drag');
}));
drop.addEventListener('drop', (event) => {
  state.files = [...event.dataTransfer.files].slice(0, 10);
  renderFiles();
  renderButton();
});

$('#importButton').onclick = () => importPicker.click();
importPicker.onchange = () => {
  const file = importPicker.files && importPicker.files[0];
  if (file) importVoice(file);
};
$('#refreshSystem').onclick = refreshSystem;
$('#closeVoiceTester').onclick = closeVoiceTest;
synthesizeVoiceButton.onclick = synthesizeVoiceTest;
saveModelrigTokenButton.onclick = saveModelrigToken;
clearModelrigTokenButton.onclick = clearModelrigToken;

Promise.all([refreshLibrary(), refreshSystem(), resumeJob()]).finally(renderButton);
