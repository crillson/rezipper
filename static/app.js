const state = {
  page: 1,
  pages: 1,
  search: ''
};

const el = {
  currentFile: document.getElementById('currentFile'),
  queueStats: document.getElementById('queueStats'),
  progressBar: document.getElementById('progressBar'),
  historyBody: document.getElementById('historyBody'),
  pageInfo: document.getElementById('pageInfo'),
  logOutput: document.getElementById('logOutput'),
  searchInput: document.getElementById('searchInput'),
  settingsForm: document.getElementById('settingsForm')
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

async function refreshStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  el.currentFile.textContent = s.current_file || '-';
  el.queueStats.textContent = `${s.processed_files} / ${s.total_files}`;
  el.progressBar.style.width = `${s.progress_percent}%`;
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
  el.pageInfo.textContent = `Sida ${data.page} / ${data.pages}`;
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
    if (input) input.value = v;
  }
}

function connectLogs() {
  const source = new EventSource('/api/log-stream');
  source.onmessage = (ev) => {
    el.logOutput.textContent += ev.data + '\n';
    el.logOutput.scrollTop = el.logOutput.scrollHeight;
  };
}

document.getElementById('startBtn').onclick = async () => { await post('/api/start'); };
document.getElementById('pauseBtn').onclick = async () => { await post('/api/pause'); };
document.getElementById('resumeBtn').onclick = async () => { await post('/api/resume'); };

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
  await post('/api/settings', payload);
  await loadSettings();
};

async function init() {
  await Promise.all([refreshStatus(), refreshHistory(), loadSettings()]);
  connectLogs();
  setInterval(refreshStatus, 1500);
  setInterval(refreshHistory, 8000);
}

init();