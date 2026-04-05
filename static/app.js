const state = {
  page: 1,
  pages: 1,
  search: '',
  lang: 'en',
  i18n: {}
};

const el = {
  topLanguageSelect: document.getElementById('topLanguageSelect'),
  navButtons: Array.from(document.querySelectorAll('.nav-btn')),
  views: Array.from(document.querySelectorAll('.view')),
  statusMessage: document.getElementById('statusMessage'),
  currentFile: document.getElementById('currentFile'),
  currentStage: document.getElementById('currentStage'),
  queueStats: document.getElementById('queueStats'),
  threadStatusList: document.getElementById('threadStatusList'),
  progressBar: document.getElementById('progressBar'),
  historyBody: document.getElementById('historyBody'),
  historyTotalSavings: document.getElementById('historyTotalSavings'),
  pageInfo: document.getElementById('pageInfo'),
  logOutput: document.getElementById('logOutput'),
  searchInput: document.getElementById('searchInput'),
  clearHistoryBtn: document.getElementById('clearHistoryBtn'),
  settingsForm: document.getElementById('settingsForm'),
  passwordForm: document.getElementById('passwordForm'),
  currentPassword: document.getElementById('currentPassword'),
  newPassword: document.getElementById('newPassword'),
  debugScanOutput: document.getElementById('debugScanOutput'),
  whatsNewVersion: document.getElementById('whatsNewVersion'),
  whatsNewContent: document.getElementById('whatsNewContent'),
  sysCpu: document.getElementById('sysCpu'),
  sysRam: document.getElementById('sysRam'),
  sysLoad: document.getElementById('sysLoad'),
  sysUptime: document.getElementById('sysUptime')
};

async function post(url, body = {}, method = 'POST') {
  return fetch(url, {
    method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

function fmtBytes(n) {
  if (typeof n !== 'number' || Number.isNaN(n)) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fmtUptime(seconds) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds)) return '-';
  const s = Math.floor(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  return `${hours}h ${mins}m`;
}

function t(key, fallback = '') {
  return state.i18n[key] || fallback || key;
}

function apiErrorToMessage(data) {
  if (data?.error_code) {
    return t(`error_${data.error_code}`, data.error_code);
  }
  return data?.error || t('msg_generic_error', 'Operation failed.');
}

function applyTheme(theme) {
  const next = (theme || 'dark').toLowerCase() === 'light' ? 'light' : 'dark';
  document.body.setAttribute('data-theme', next);
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

function showView(viewId) {
  el.views.forEach((view) => {
    view.classList.toggle('active-view', view.id === viewId);
  });
  el.navButtons.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.view === viewId);
  });
}

function setStatusMessage(msg, isError = false) {
  el.statusMessage.textContent = msg || '-';
  el.statusMessage.style.color = isError ? '#cc2b2b' : '';
}

async function refreshStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  el.currentFile.textContent = s.current_file || '-';
  const stageKey = s.current_stage ? `stage_${s.current_stage}` : '';
  el.currentStage.textContent = stageKey ? t(stageKey, s.current_stage) : '-';
  el.queueStats.textContent = `${s.processed_files} / ${s.total_files}`;
  el.progressBar.style.width = `${s.progress_percent}%`;

  el.threadStatusList.innerHTML = '';
  const statuses = Array.isArray(s.thread_statuses) ? s.thread_statuses : [];
  for (const item of statuses) {
    const li = document.createElement('li');
    const activityKey = item.activity ? `stage_${item.activity}` : '';
    const activityText = activityKey ? t(activityKey, item.activity || '-') : (item.activity || '-');
    const fileText = item.file || '-';
    const suffix = item.threads ? ` (${t('threads_label', 'threads')}: ${item.threads})` : '';
    li.textContent = `${item.name || 'worker'}: ${activityText} • ${fileText}${suffix}`;
    el.threadStatusList.appendChild(li);
  }
}

async function refreshSummary() {
  const r = await fetch('/api/history/summary');
  if (!r.ok) return;
  const data = await r.json();
  el.historyTotalSavings.textContent = fmtBytes(data.total_savings_bytes || 0);
}

async function runDebugScan() {
  const r = await fetch('/api/debug/scan');
  const data = await r.json();
  el.debugScanOutput.textContent = JSON.stringify(data, null, 2);
}

async function refreshSystemStatus() {
  const r = await fetch('/api/system-status');
  if (!r.ok) return;
  const data = await r.json();
  const cpuText = data.cpu_percent == null
    ? t('sys_waiting_sample', 'sampling...')
    : `${data.cpu_percent.toFixed(1)}% (${data.cpu_cores} ${t('sys_cores', 'cores')})`;

  const memory = data.memory || {};
  const used = fmtBytes(memory.used);
  const total = fmtBytes(memory.total);
  const ramText = (used === '-' || total === '-') ? '-' : `${used} / ${total}`;
  const load = data.load_avg || {};
  const loadText = [load['1m'], load['5m'], load['15m']].filter((v) => v != null).join(' / ') || '-';

  el.sysCpu.textContent = cpuText;
  el.sysRam.textContent = ramText;
  el.sysLoad.textContent = loadText;
  el.sysUptime.textContent = fmtUptime(data.uptime_seconds);
}

async function refreshWhatsNew() {
  const r = await fetch('/api/whats-new');
  if (!r.ok) return;
  const data = await r.json();
  el.whatsNewVersion.textContent = data.version || '-';
  el.whatsNewContent.textContent = data.content || '';
}

async function deleteHistoryRow(id) {
  if (!confirm(t('confirm_delete_history_row', 'Delete this history row?'))) return;
  const r = await post(`/api/history/${id}`, {}, 'DELETE');
  const data = await r.json();
  if (!data.ok) {
    setStatusMessage(t('error_history_delete_failed', 'Could not delete history row.'), true);
    return;
  }
  setStatusMessage(t('msg_history_row_deleted', 'History row removed.'));
  await refreshHistory();
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

  const historyLabels = {
    filename: t('th_filename', 'Filename'),
    originalSize: t('th_original_size', 'Original size'),
    newSize: t('th_new_size', 'New size'),
    savings: t('th_savings', 'Savings (%)'),
    ratio: t('th_ratio', 'Ratio'),
    status: t('th_status', 'Status'),
    time: t('th_time', 'Time'),
    actions: t('th_actions', 'Actions')
  };

  for (const row of data.items) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td data-label="${historyLabels.filename}">${row.filename}</td>
      <td data-label="${historyLabels.originalSize}">${fmtBytes(row.original_size)}</td>
      <td data-label="${historyLabels.newSize}">${fmtBytes(row.new_size)}</td>
      <td data-label="${historyLabels.savings}">${row.savings_percent.toFixed(2)}%</td>
      <td data-label="${historyLabels.ratio}">${row.ratio.toFixed(2)}</td>
      <td data-label="${historyLabels.status}">${row.status}</td>
      <td data-label="${historyLabels.time}">${new Date(row.created_at + 'Z').toLocaleString()}</td>
      <td data-label="${historyLabels.actions}"><button class="danger history-delete-btn" data-id="${row.id}">${t('btn_delete', 'Delete')}</button></td>
    `;
    el.historyBody.appendChild(tr);
  }

  Array.from(document.querySelectorAll('.history-delete-btn')).forEach((btn) => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.id || '0');
      if (id > 0) await deleteHistoryRow(id);
    };
  });

  await refreshSummary();
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
  applyTheme(s.theme || 'dark');
  const language = s.language || 'en';
  el.topLanguageSelect.value = language;
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

document.getElementById('pauseBtn').onclick = async () => {
  await post('/api/pause');
  setStatusMessage(t('msg_run_paused', 'Run paused.'));
};

document.getElementById('resumeBtn').onclick = async () => {
  await post('/api/resume');
  setStatusMessage(t('msg_run_resumed', 'Run resumed.'));
};

document.getElementById('stopBtn').onclick = async () => {
  const r = await post('/api/stop');
  const data = await r.json();
  if (data.ok) {
    setStatusMessage(t('msg_stop_requested', 'Stop requested.'));
  } else {
    setStatusMessage(t('msg_stop_not_running', 'No run is currently active.'), true);
  }
};

document.getElementById('debugScanBtn').onclick = runDebugScan;

el.clearHistoryBtn.onclick = async () => {
  if (!confirm(t('confirm_clear_history', 'Clear all history?'))) return;
  await post('/api/history/clear');
  setStatusMessage(t('msg_history_cleared', 'History cleared.'));
  state.page = 1;
  await refreshHistory();
};

el.navButtons.forEach((btn) => {
  btn.onclick = async () => {
    showView(btn.dataset.view);
    if (btn.dataset.view === 'whatsNewView') {
      await refreshWhatsNew();
    }
  };
});

el.topLanguageSelect.onchange = async () => {
  const chosen = el.topLanguageSelect.value;
  await post('/api/settings', {language: chosen});
  await loadSettings();
};

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
  const r = await post('/api/settings', payload);
  const data = await r.json();
  if (!r.ok || !data.ok) {
    setStatusMessage(apiErrorToMessage(data), true);
    return;
  }
  applyTheme(payload.theme || 'dark');
  setStatusMessage(t('msg_settings_saved', 'Settings saved. Check system log for cron validation.'));
  await loadSettings();
  await runDebugScan();
  await refreshSystemStatus();
};

el.passwordForm.onsubmit = async (e) => {
  e.preventDefault();
  const r = await post('/api/change-password', {
    current_password: el.currentPassword.value,
    new_password: el.newPassword.value
  });
  const data = await r.json();
  if (!r.ok || !data.ok) {
    setStatusMessage(apiErrorToMessage(data), true);
    return;
  }
  el.currentPassword.value = '';
  el.newPassword.value = '';
  setStatusMessage(t('msg_password_changed', 'Password changed.'));
};

async function init() {
  showView('dashboardView');
  await loadSettings();
  await Promise.all([refreshStatus(), refreshHistory(), runDebugScan(), refreshSystemStatus(), refreshWhatsNew()]);
  connectLogs();
  setInterval(refreshStatus, 1500);
  setInterval(refreshHistory, 8000);
  setInterval(refreshSystemStatus, 3000);
}

init();