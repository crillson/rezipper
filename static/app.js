const state = {
  page: 1,
  pages: 1,
  search: '',
  lang: 'en',
  i18n: {}
};

const el = {
  statusMessage: document.getElementById('statusMessage'),
  currentFile: document.getElementById('currentFile'),
  queueStats: document.getElementById('queueStats'),
  progressBar: document.getElementById('progressBar'),
  historyBody: document.getElementById('historyBody'),
  pageInfo: document.getElementById('pageInfo'),
  logOutput: document.getElementById('logOutput'),
  searchInput: document.getElementById('searchInput'),
  settingsForm: document.getElementById('settingsForm'),
  debugScanOutput: document.getElementById('debugScanOutput')
};

async function post(url, body = {}) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function t(key, fallback = '') {
  return state.i18n[key] || fallback || key;
}

function apiErrorToMessage(data) {
  if (data?.error_code) {
    return t(`error_${data.error_code}`, data.error_code);
  }
  return data?.error || t('msg_run_start_failed', 'Start failed.');
}

async function loadLanguage(lang) {
  const chosen = (lang || 'en').toLowerCase();
  let next = chosen;
  try {
    const r = await fetch(`/static/i18n/${chosen}.json`, {cache: 'no-cache'});
    if (!r.ok) throw new Error('missing language');
    state.i18n = await r.json();
  } catch (_) {
    next = 'en';
    const fallback = await fetch('/static/i18n/en.json', {cache: 'no-cache'});
    state.i18n = await fallback.json();
  }
  state.lang = next;
  applyTranslations();
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    const key = node.dataset.i18n;
    const value = t(key, node.textContent);
    node.textContent = value;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    const key = node.dataset.i18nPlaceholder;
    const value = t(key, node.getAttribute('placeholder') || '');
    node.setAttribute('placeholder', value);
  });
  updatePageInfo();
}

function updatePageInfo() {
  el.pageInfo.textContent = `${t('page_label', 'Page')} ${state.page} / ${state.pages}`;
}

async function refreshStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  el.currentFile.textContent = s.current_file || '-';
  el.queueStats.textContent = `${s.processed_files} / ${s.total_files}`;
  el.progressBar.style.width = `${s.progress_percent}%`;
}

function setStatusMessage(msg, isError = false) {
  el.statusMessage.textContent = msg || '-';
  el.statusMessage.style.color = isError ? '#cc2b2b' : '';
}

async function runDebugScan() {
  const r = await fetch('/api/debug/scan');
  const data = await r.json();
  el.debugScanOutput.textContent = JSON.stringify(data, null, 2);
}

async function refreshHistory() {
  const p = new URLSearchParams({
    page: String(state.page),
    per_page: '20',
    search: state.search
  });
  const r = await fetch(`/api/history?${p}`);
  const data = await r.json();

  state.pages = data.pages || 1;
  state.page = data.page || state.page;
  updatePageInfo();
  el.historyBody.innerHTML = '';

  for (const row of data.items) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.filename}</td>
      <td>${fmtBytes(row.original_size)}</td>
      <td>${fmtBytes(row.new_size)}</td>
      <td>${row.savings_percent.toFixed(2)}%</td>
      <td>${row.ratio.toFixed(2)}</td>
      <td>${row.status}</td>
      <td>${new Date(row.created_at + 'Z').toLocaleString()}</td>
    `;
    el.historyBody.appendChild(tr);
  }
}

async function loadSettings() {
  const r = await fetch('/api/settings');
  const s = await r.json();
  for (const [k, v] of Object.entries(s)) {
    const input = el.settingsForm.querySelector(`[name="${k}"]`);
    if (!input) continue;
    if (input.type === 'checkbox') {
      input.checked = ['1', 'true', 'yes', 'on'].includes(String(v).toLowerCase());
    } else {
      input.value = v;
    }
  }
  const language = s.language || 'en';
  await loadLanguage(language);
}

function connectLogs() {
  const source = new EventSource('/api/log-stream');
  source.onmessage = (ev) => {
    el.logOutput.textContent += ev.data + '\n';
    el.logOutput.scrollTop = el.logOutput.scrollHeight;
  };
}

document.getElementById('startBtn').onclick = async () => {
  const r = await post('/api/start');
  const data = await r.json();
  if (data.ok) {
    setStatusMessage(t('msg_run_started', 'Run started.'));
  } else {
    setStatusMessage(apiErrorToMessage(data), true);
  }
  await refreshStatus();
};
document.getElementById('pauseBtn').onclick = async () => { await post('/api/pause'); };
document.getElementById('resumeBtn').onclick = async () => { await post('/api/resume'); };
document.getElementById('debugScanBtn').onclick = runDebugScan;

document.getElementById('searchBtn').onclick = async () => {
  state.search = el.searchInput.value.trim();
  state.page = 1;
  await refreshHistory();
};

document.getElementById('prevPage').onclick = async () => {
  if (state.page > 1) {
    state.page -= 1;
    await refreshHistory();
  }
};

document.getElementById('nextPage').onclick = async () => {
  if (state.page < state.pages) {
    state.page += 1;
    await refreshHistory();
  }
};

el.settingsForm.onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(el.settingsForm);
  const payload = Object.fromEntries(fd.entries());
  payload.debug_logging = document.getElementById('debugLogging').checked ? 'true' : 'false';
  await post('/api/settings', payload);
  setStatusMessage(t('msg_settings_saved', 'Settings saved. Check system log for cron validation.'));
  await loadSettings();
};

async function init() {
  await loadSettings();
  await Promise.all([refreshStatus(), refreshHistory()]);
  await runDebugScan();
  connectLogs();
  setInterval(refreshStatus, 1500);
  setInterval(refreshHistory, 8000);
}

init();