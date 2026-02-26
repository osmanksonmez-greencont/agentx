const tabs = document.querySelectorAll('nav button');
const sections = document.querySelectorAll('.tab');
let eventsSource = null;

for (const btn of tabs) {
  btn.onclick = () => {
    tabs.forEach(b => b.classList.remove('active'));
    sections.forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  };
}

const j = (o) => JSON.stringify(o, null, 2);
const getProject = () => document.getElementById('projectId').value || 'default';
const getToken = () => localStorage.getItem('cp_api_token') || '';

async function api(path, opts = {}) {
  const headers = {'Content-Type': 'application/json', ...(opts.headers || {})};
  const token = getToken();
  if (token) headers['X-API-Key'] = token;
  const res = await fetch(path, {...opts, headers});
  if (!res.ok) throw new Error(await res.text());
  return res.headers.get('content-type')?.includes('application/json') ? res.json() : res.text();
}

function startEventStream() {
  if (eventsSource) eventsSource.close();
  const pid = getProject();
  const token = encodeURIComponent(getToken());
  const url = `/api/projects/${pid}/events/stream?token=${token}`;
  eventsSource = new EventSource(url);
  eventsSource.addEventListener('team_event', (ev) => {
    try {
      const payload = JSON.parse(ev.data || '{}');
      const box = document.getElementById('eventsView');
      const existing = box.textContent.trim();
      const parsed = existing ? JSON.parse(existing) : [];
      const lines = Array.isArray(parsed) ? parsed : (parsed.events || []);
      lines.unshift(payload);
      box.textContent = j(lines.slice(0, 40));
    } catch (e) {
      console.error(e);
    }
  });
}

async function refreshActivity() {
  const pid = getProject();
  const agents = await api('/api/agents');
  const events = await api(`/api/projects/${pid}/events?limit=40`);
  document.getElementById('agentsView').textContent = j(agents);
  document.getElementById('eventsView').textContent = j(events.events || []);
}

async function refreshBoard() {
  const pid = getProject();
  const board = await api(`/api/projects/${pid}/board`);
  const wrap = document.getElementById('boardView');
  wrap.innerHTML = '';
  for (const [name, cards] of Object.entries(board)) {
    const col = document.createElement('div');
    col.className = 'col';
    col.innerHTML = `<h4>${name}</h4>`;
    for (const c of cards) {
      const card = document.createElement('div');
      card.className = 'card';
      card.textContent = `[${c.assigneeRole}] ${c.title}`;
      col.appendChild(card);
    }
    wrap.appendChild(col);
  }
}

async function refreshUsage() {
  const pid = getProject();
  document.getElementById('usageView').textContent = j(await api(`/api/usage?projectId=${encodeURIComponent(pid)}`));
}

async function refreshJobs() {
  const jobs = await api('/api/schedules');
  const dlq = await api('/api/queue/dlq?limit=20');
  document.getElementById('jobsView').textContent = j({jobs, dlq});
}

async function createSession() {
  const command = document.getElementById('termCommand').value || 'bash';
  const out = await api('/api/terminal/sessions', {method: 'POST', body: JSON.stringify({command})});
  document.getElementById('sessionId').value = out.id || '';
  document.getElementById('terminalView').textContent = j(out);
}

async function sendTerm() {
  const id = document.getElementById('sessionId').value;
  const text = document.getElementById('termInput').value;
  const out = await api(`/api/terminal/sessions/${id}/write`, {method: 'POST', body: JSON.stringify({text})});
  document.getElementById('terminalView').textContent = j(out);
}

async function readTerm() {
  const id = document.getElementById('sessionId').value;
  const out = await api(`/api/terminal/sessions/${id}/read?limit=200`);
  document.getElementById('terminalView').textContent = out.lines.join('\n');
}

async function loadConfig() {
  const cfg = await api('/api/config');
  document.getElementById('configEditor').value = j(cfg);
}

async function saveConfig() {
  const text = document.getElementById('configEditor').value;
  const out = await api('/api/config', {method: 'POST', body: text});
  alert(out.message || 'saved');
}

document.getElementById('refreshActivity').onclick = refreshActivity;
document.getElementById('refreshBoard').onclick = refreshBoard;
document.getElementById('refreshUsage').onclick = refreshUsage;
document.getElementById('refreshJobs').onclick = refreshJobs;
document.getElementById('createSession').onclick = createSession;
document.getElementById('sendTerm').onclick = sendTerm;
document.getElementById('readTerm').onclick = readTerm;
document.getElementById('loadConfig').onclick = loadConfig;
document.getElementById('saveConfig').onclick = saveConfig;
document.getElementById('saveToken').onclick = () => {
  const token = document.getElementById('apiToken').value || '';
  localStorage.setItem('cp_api_token', token);
  startEventStream();
  refreshActivity().catch(console.error);
};

document.getElementById('apiToken').value = getToken();

refreshActivity().catch(console.error);
refreshBoard().catch(console.error);
refreshUsage().catch(console.error);
startEventStream();
