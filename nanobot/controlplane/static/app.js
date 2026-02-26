/**
 * AgentX Control Plane - Modern UI
 */

const AUTO_REFRESH_INTERVAL = 15000;
let autoRefreshEnabled = true;
let activityInterval = null;
let eventsSource = null;
let currentProject = null; // null = all projects
let allProjects = [];
let filteredProjects = [];

// DOM Elements
const tabs = document.querySelectorAll('.nav-item');
const sections = document.querySelectorAll('.tab');

// Tab Navigation
tabs.forEach(btn => {
  btn.onclick = () => {
    tabs.forEach(b => b.classList.remove('active'));
    sections.forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const tabId = btn.dataset.tab;
    document.getElementById(tabId).classList.add('active');
    document.getElementById('pageTitle').textContent = btn.querySelector('.nav-label').textContent;
  };
});

// API Helper
const j = (o) => JSON.stringify(o, null, 2);
const getToken = () => localStorage.getItem('cp_api_token') || '';

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['X-API-Key'] = token;
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) throw new Error(await res.text());
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

// Project Management
async function loadProjects() {
  try {
    const data = await api('/api/projects');
    allProjects = data.projects || [];
    filteredProjects = allProjects;
    renderProjectChips();
  } catch (e) {
    console.error('Failed to load projects:', e);
  }
}

function renderProjectChips() {
  const container = document.getElementById('projectChips');
  
  // Add "All" chip first
  const allChip = `
    <div class="project-chip ${currentProject === null ? 'active' : ''}" data-project="all">
      All Projects
      <span class="chip-count">${allProjects.reduce((sum, p) => sum + p.taskCount, 0)}</span>
    </div>
  `;
  
  const projectChips = allProjects.map(p => {
    const isActive = currentProject === p.id;
    return `
      <div class="project-chip ${isActive ? 'active' : ''}" data-project="${p.id}">
        ${p.id}
        <span class="chip-count">${p.taskCount || 0}</span>
      </div>
    `;
  }).join('');
  
  container.innerHTML = allChip + projectChips;
  
  // Add click handlers
  container.querySelectorAll('.project-chip').forEach(chip => {
    chip.onclick = () => {
      const projectId = chip.dataset.project;
      currentProject = projectId === 'all' ? null : projectId;
      renderProjectChips();
      refreshCurrentTab();
    };
  });
}

function refreshCurrentTab() {
  const activeTab = document.querySelector('.nav-item.active')?.dataset.tab;
  if (activeTab === 'activity') {
    refreshActivity();
  } else if (activeTab === 'board') {
    refreshBoard();
  } else if (activeTab === 'usage') {
    refreshUsage();
  } else if (activeTab === 'jobs') {
    refreshJobs();
  }
}

// Activity Tab
async function refreshActivity() {
  try {
    const [agentsData, eventsData] = await Promise.all([
      api('/api/agents'),
      currentProject 
        ? api(`/api/projects/${currentProject}/events?limit=30`)
        : Promise.resolve({ events: [] }) // Show all events if "all"
    ]);
    
    renderAgents(agentsData.agents || []);
    renderEvents(eventsData.events || []);
    updateLastRefresh();
  } catch (e) {
    console.error('Failed to refresh activity:', e);
    document.getElementById('agentsView').innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
  }
}

function renderAgents(agents) {
  const container = document.getElementById('agentsView');
  if (!agents || agents.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🤖</div>
        <div class="empty-state-text">No agents running</div>
      </div>
    `;
    return;
  }

  container.innerHTML = agents.map(agent => {
    const statusClass = agent.status === 'busy' ? 'busy' : agent.status === 'idle' ? 'idle' : 'unknown';
    const statusText = agent.status === 'busy' ? 'Busy' : agent.status === 'idle' ? 'Idle' : 'Unknown';
    const taskId = agent.currentTaskId ? agent.currentTaskId.slice(0, 12) + '...' : 'No active task';
    
    return `
      <div class="agent-card">
        <div class="agent-header">
          <div>
            <div class="agent-name">${agent.name}</div>
            <div class="agent-role">${agent.role}</div>
          </div>
          <div class="agent-status">
            <span class="status-dot ${statusClass}"></span>
            <span>${statusText}</span>
          </div>
        </div>
        <div class="agent-task">${taskId}</div>
      </div>
    `;
  }).join('');
}

function renderEvents(events) {
  const container = document.getElementById('eventsView');
  const countBadge = document.getElementById('eventCount');
  
  countBadge.textContent = events.length;
  countBadge.className = 'badge ' + (events.length > 0 ? 'green' : 'muted');
  
  if (!events || events.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📋</div>
        <div class="empty-state-text">No events yet</div>
      </div>
    `;
    return;
  }

  const iconMap = {
    'task_started': '▶️',
    'task_completed': '✅',
    'task_failed': '❌',
    'task_created': '🆕',
    'agent_heartbeat': '💚'
  };

  container.innerHTML = events.map(event => {
    const icon = iconMap[event.kind] || '📝';
    const time = event.createdAt ? new Date(event.createdAt).toLocaleTimeString() : '';
    const roleBadge = event.assigneeRole ? `<span class="event-role">${event.assigneeRole}</span>` : '';
    const projectBadge = event.projectId ? `<span class="card-project">${event.projectId}</span>` : '';
    
    return `
      <div class="event-item">
        <div class="event-icon">${icon}</div>
        <div class="event-content">
          <div class="event-message">${projectBadge}${escapeHtml(event.message)}</div>
          <div class="event-meta">
            <span class="event-time">${time}</span>
            ${roleBadge}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Board Tab - Unified view of ALL projects
async function refreshBoard() {
  try {
    let allTasks = [];
    
    // Fetch board from all projects
    for (const project of allProjects) {
      try {
        const boardData = await api(`/api/projects/${project.id}/board`);
        // Flatten all columns into single task list with project info
        Object.entries(boardData).forEach(([column, tasks]) => {
          tasks.forEach(task => {
            allTasks.push({
              ...task,
              _column: column,
              _project: project.id
            });
          });
        });
      } catch (e) {
        console.warn(`Failed to fetch board for ${project.id}:`, e);
      }
    }
    
    renderUnifiedBoard(allTasks);
  } catch (e) {
    console.error('Failed to refresh board:', e);
    document.getElementById('boardView').innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
  }
}

function renderUnifiedBoard(tasks) {
  const container = document.getElementById('boardView');
  if (!tasks || tasks.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">▦</div>
        <div class="empty-state-text">No tasks across all projects</div>
      </div>
    `;
    return;
  }

  // Group by column
  const columnOrder = ['Backlog', 'Ready', 'In Progress', 'Review', 'Done', 'Blocked'];
  const grouped = {};
  columnOrder.forEach(col => grouped[col] = []);
  tasks.forEach(task => {
    const col = task._column || 'Backlog';
    if (!grouped[col]) grouped[col] = [];
    grouped[col].push(task);
  });

  container.innerHTML = columnOrder.map(column => {
    const cards = grouped[column] || [];
    
    return `
      <div class="board-column">
        <div class="column-header">
          <span class="column-title">${column}</span>
          <span class="column-count">${cards.length}</span>
        </div>
        <div class="column-cards">
          ${cards.map(card => `
            <div class="board-card">
              <div class="card-title">
                <span class="card-project">${card._project}</span>
                ${escapeHtml(card.title)}
              </div>
              <div class="card-meta">
                <span class="card-role">${card.assigneeRole || 'unassigned'}</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }).join('');
}

// Usage Tab
async function refreshUsage() {
  try {
    // Fetch usage for each project
    const usagePromises = allProjects.map(async (p) => {
      try {
        const usage = await api(`/api/usage?projectId=${p.id}`);
        return { project: p.id, usage };
      } catch (e) {
        return { project: p.id, usage: null };
      }
    });
    
    const results = await Promise.all(usagePromises);
    
    // Calculate totals
    let totalInput = 0, totalOutput = 0, totalTasks = 0;
    results.forEach(r => {
      if (r.usage) {
        totalInput += r.usage.totalInputTokens || 0;
        totalOutput += r.usage.totalOutputTokens || 0;
        totalTasks += r.usage.totalTasks || 0;
      }
    });
    const total = totalInput + totalOutput;
    
    // Render summary
    const summaryContainer = document.getElementById('usageSummary');
    summaryContainer.innerHTML = `
      <div class="usage-stat">
        <span class="usage-stat-label">Total Tokens</span>
        <span class="usage-stat-value blue">${formatNumber(total)}</span>
      </div>
      <div class="usage-stat">
        <span class="usage-stat-label">Input</span>
        <span class="usage-stat-value purple">${formatNumber(totalInput)}</span>
      </div>
      <div class="usage-stat">
        <span class="usage-stat-label">Output</span>
        <span class="usage-stat-value green">${formatNumber(totalOutput)}</span>
      </div>
      <div class="usage-stat">
        <span class="usage-stat-label">Tasks</span>
        <span class="usage-stat-value orange">${totalTasks}</span>
      </div>
    `;
    
    // Render breakdown
    const breakdownContainer = document.getElementById('usageBreakdown');
    const maxTokens = Math.max(...results.filter(r => r.usage).map(r => (r.usage.totalInputTokens || 0) + (r.usage.totalOutputTokens || 0)), 1);
    
    breakdownContainer.innerHTML = results.map(r => {
      const input = r.usage?.totalInputTokens || 0;
      const output = r.usage?.totalOutputTokens || 0;
      const taskCount = r.usage?.totalTasks || 0;
      const totalProj = input + output;
      const pct = (totalProj / maxTokens) * 100;
      
      return `
        <div class="usage-project-row">
          <div class="usage-project-name">
            <span class="card-project">${r.project}</span>
            ${taskCount} tasks
          </div>
          <div class="usage-project-bars">
            <div class="usage-bar-container">
              <div class="usage-bar">
                <div class="usage-bar-fill input" style="width: ${(input / totalProj) * 100}%"></div>
              </div>
              <span class="usage-bar-value">${formatNumber(input)}</span>
            </div>
            <div class="usage-bar-container">
              <div class="usage-bar">
                <div class="usage-bar-fill output" style="width: ${(output / totalProj) * 100}%"></div>
              </div>
              <span class="usage-bar-value">${formatNumber(output)}</span>
            </div>
            <span class="usage-bar-value" style="font-weight: 600; color: var(--text-primary)">${formatNumber(totalProj)}</span>
          </div>
        </div>
      `;
    }).join('');
    
    // Raw JSON
    const rawData = {};
    results.forEach(r => { if (r.usage) rawData[r.project] = r.usage; });
    document.getElementById('usageView').textContent = j(rawData);
    
    updateLastRefresh();
  } catch (e) {
    console.error('Failed to refresh usage:', e);
    document.getElementById('usageView').textContent = `Error: ${e.message}`;
  }
}

function formatNumber(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return num.toString();
}

// Jobs Tab - DataTable
async function refreshJobs() {
  try {
    const jobs = await api('/api/schedules');
    renderJobsTable(jobs.jobs || []);
  } catch (e) {
    console.error('Failed to refresh jobs:', e);
    document.getElementById('jobsView').innerHTML = `<tr><td colspan="7">Error: ${e.message}</td></tr>`;
  }
}

function renderJobsTable(jobs) {
  const tbody = document.getElementById('jobsView');
  const infoEl = document.getElementById('jobsInfo');
  
  infoEl.textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''}`;
  
  if (!jobs || jobs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">⚙</div>
            <div class="empty-state-text">No scheduled jobs</div>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = jobs.map(job => {
    const jobId = job.id ? job.id.slice(0, 12) : '—';
    const name = job.name || jobId;
    const schedule = job.schedule || '—';
    const nextRun = job.nextRun ? formatDateTime(job.nextRun) : '—';
    const lastRun = job.lastRun ? formatDateTime(job.lastRun) : '—';
    const status = job.enabled !== false ? 'active' : 'paused';
    const statusLabel = job.enabled !== false ? 'Active' : 'Paused';
    
    return `
      <tr>
        <td class="job-id">${jobId}</td>
        <td class="job-name">${escapeHtml(name)}</td>
        <td class="job-schedule">${escapeHtml(schedule)}</td>
        <td class="job-time">${nextRun}</td>
        <td class="job-time">${lastRun}</td>
        <td><span class="job-status ${status}">● ${statusLabel}</span></td>
        <td class="job-actions">
          <button class="job-btn" title="Edit">✏️</button>
          <button class="job-btn" title="${status === 'active' ? 'Pause' : 'Resume'}">${status === 'active' ? '⏸' : '▶'}</button>
          <button class="job-btn danger" title="Delete">🗑</button>
        </td>
      </tr>
    `;
  }).join('');
}

function formatDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { 
    month: 'short', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  });
}

// Terminal
let currentSessionId = null;

document.getElementById('createSession').onclick = async () => {
  try {
    const cmd = document.getElementById('termCommand').value || 'bash';
    const session = await api('/api/terminal/sessions', {
      method: 'POST',
      body: JSON.stringify({ command: cmd })
    });
    currentSessionId = session.id;
    document.getElementById('termOutput').textContent = `Session created: ${session.id}\n`;
  } catch (e) {
    document.getElementById('termOutput').textContent = `Error: ${e.message}`;
  }
};

document.getElementById('sendTerm').onclick = async () => {
  if (!currentSessionId) return;
  const text = prompt('Enter command:');
  if (!text) return;
  try {
    await api(`/api/terminal/sessions/${currentSessionId}/write`, {
      method: 'POST',
      body: JSON.stringify({ text })
    });
  } catch (e) {
    alert(e.message);
  }
};

document.getElementById('readTerm').onclick = async () => {
  if (!currentSessionId) return;
  try {
    const data = await api(`/api/terminal/sessions/${currentSessionId}/read?limit=200`);
    document.getElementById('termOutput').textContent = data.lines?.join('\n') || 'No output';
  } catch (e) {
    document.getElementById('termOutput').textContent = `Error: ${e.message}`;
  }
};

// Config
document.getElementById('loadConfig').onclick = async () => {
  try {
    const config = await api('/api/config');
    document.getElementById('configView').value = j(config);
  } catch (e) {
    alert(e.message);
  }
};

document.getElementById('saveConfig').onclick = async () => {
  try {
    const config = JSON.parse(document.getElementById('configView').value);
    await api('/api/config', {
      method: 'POST',
      body: JSON.stringify(config)
    });
    alert('Config saved!');
  } catch (e) {
    alert(e.message);
  }
};

// Token
document.getElementById('saveToken').onclick = () => {
  const token = document.getElementById('apiToken').value || '';
  localStorage.setItem('cp_api_token', token);
  startEventStream();
  refreshActivity();
};

document.getElementById('apiToken').value = getToken();

// Auto-refresh toggle
const autoRefreshToggle = document.getElementById('autoRefreshToggle');
autoRefreshToggle.onclick = () => {
  autoRefreshEnabled = !autoRefreshEnabled;
  autoRefreshToggle.classList.toggle('active', autoRefreshEnabled);
  autoRefreshToggle.querySelector('.toggle-label').textContent = autoRefreshEnabled ? '15s' : 'OFF';
  if (autoRefreshEnabled) {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
};

// Refresh buttons
document.getElementById('refreshActivity').onclick = refreshActivity;
document.getElementById('refreshUsage').onclick = refreshUsage;
document.getElementById('refreshJobs').onclick = refreshJobs;
document.getElementById('addJob').onclick = () => {
  alert('Add job dialog coming soon!');
};

// Event Stream
function startEventStream() {
  if (eventsSource) eventsSource.close();
  const token = encodeURIComponent(getToken());
  const projectPath = currentProject ? `/${currentProject}` : '';
  const url = `/api/projects${projectPath}/events/stream?token=${token}`;
  eventsSource = new EventSource(url);
  eventsSource.addEventListener('team_event', (ev) => {
    try {
      const payload = JSON.parse(ev.data || '{}');
      const iconMap = {
        'task_started': '▶️',
        'task_completed': '✅',
        'task_failed': '❌',
        'task_created': '🆕',
        'agent_heartbeat': '💚'
      };
      const icon = iconMap[payload.kind] || '📝';
      const time = payload.createdAt ? new Date(payload.createdAt).toLocaleTimeString() : '';
      const roleBadge = payload.assigneeRole ? `<span class="event-role">${payload.assigneeRole}</span>` : '';
      const projectBadge = payload.projectId ? `<span class="card-project">${payload.projectId}</span>` : '';
      
      const eventHtml = `
        <div class="event-item">
          <div class="event-icon">${icon}</div>
          <div class="event-content">
            <div class="event-message">${projectBadge}${escapeHtml(payload.message)}</div>
            <div class="event-meta">
              <span class="event-time">${time}</span>
              ${roleBadge}
            </div>
          </div>
        </div>
      `;
      const eventsView = document.getElementById('eventsView');
      eventsView.insertAdjacentHTML('afterbegin', eventHtml);
      
      const events = eventsView.querySelectorAll('.event-item');
      if (events.length > 30) {
        events[events.length - 1].remove();
      }
    } catch (e) {
      console.error(e);
    }
  });
}

// Auto-refresh
function startAutoRefresh() {
  if (activityInterval) clearInterval(activityInterval);
  if (autoRefreshEnabled) {
    activityInterval = setInterval(() => {
      refreshCurrentTab();
    }, AUTO_REFRESH_INTERVAL);
  }
}

function stopAutoRefresh() {
  if (activityInterval) {
    clearInterval(activityInterval);
    activityInterval = null;
  }
}

function updateLastRefresh() {
  const el = document.getElementById('lastUpdate');
  if (el) {
    el.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }
}

// Initialize
async function init() {
  await loadProjects();
  refreshActivity();
  refreshBoard();
  refreshUsage();
  refreshJobs();
  startEventStream();
  startAutoRefresh();
}

init();