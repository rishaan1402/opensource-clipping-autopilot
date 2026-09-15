/**
 * OpenSource Clipping Studio — API Client
 * 
 * Shared module for all studio pages.
 * Backend URL is stored in localStorage and configurable via the Connect modal.
 */

const StudioAPI = (() => {
  const STORAGE_KEY = 'osc_backend_url';

  /** Get the saved backend URL */
  function getBackendUrl() {
    return (localStorage.getItem(STORAGE_KEY) || '').replace(/\/+$/, '');
  }

  /** Save backend URL */
  function setBackendUrl(url) {
    localStorage.setItem(STORAGE_KEY, url.replace(/\/+$/, ''));
  }

  /** Clear backend URL */
  function clearBackendUrl() {
    localStorage.removeItem(STORAGE_KEY);
  }

  /** Check if connected (URL is set) */
  function isConfigured() {
    return !!getBackendUrl();
  }

  /** Generic fetch wrapper with error handling */
  async function request(path, options = {}) {
    const base = getBackendUrl();
    if (!base) throw new Error('Backend URL not configured. Please connect first.');

    const url = `${base}${path}`;
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
        ...(options.headers || {}),
      },
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }

    return res.json();
  }

  // ---- Health ----
  async function checkHealth() {
    return request('/api/health');
  }

  // ---- Jobs ----
  async function fetchJobs() {
    return request('/api/jobs');
  }

  async function fetchJob(jobId) {
    return request(`/api/jobs/${jobId}`);
  }

  async function createJob(payload) {
    return request('/api/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async function deleteJob(jobId) {
    return request(`/api/jobs/${jobId}`, { method: 'DELETE' });
  }

  // ---- Settings ----
  async function fetchSettings() {
    return request('/api/settings');
  }

  async function updateSettings(payload) {
    return request('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  // ---- SSE for real-time job status ----
  function createSSE(jobId, onMessage) {
    const base = getBackendUrl();
    if (!base) return null;

    const eventSource = new EventSource(`${base}/api/jobs/${jobId}/status`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('SSE parse error:', e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return eventSource;
  }

  // ---- Server Shutdown ----
  async function shutdownServer() {
    return request('/api/shutdown', { method: 'POST' });
  }

  // Public API
  return {
    getBackendUrl,
    setBackendUrl,
    clearBackendUrl,
    isConfigured,
    checkHealth,
    fetchJobs,
    fetchJob,
    createJob,
    deleteJob,
    fetchSettings,
    updateSettings,
    createSSE,
    shutdownServer,
  };
})();


// ============================================================
// Shared UI Utilities (used across all studio pages)
// ============================================================

/** Theme toggle */
function toggleTheme() {
  if (document.documentElement.classList.contains('dark')) {
    document.documentElement.classList.remove('dark');
    localStorage.setItem('theme', 'light');
  } else {
    document.documentElement.classList.add('dark');
    localStorage.setItem('theme', 'dark');
  }
}

/** Format date string to locale */
function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleString('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/** Status labels */
const STATUS_LABELS = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcribing: 'Transcribing',
  analyzing: 'Analyzing',
  rendering: 'Rendering',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

/** Mobile sidebar toggle */
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  sidebar.classList.toggle('open');
  if (sidebar.classList.contains('open')) {
    overlay.style.display = 'block';
  } else {
    overlay.style.display = 'none';
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('mobile-overlay');
  sidebar.classList.remove('open');
  overlay.style.display = 'none';
}

/** Update sidebar connection indicator */
function updateConnectIndicator() {
  const dot = document.getElementById('connect-dot');
  const label = document.getElementById('connect-label');
  const btn = document.getElementById('connect-btn');
  const stopBtn = document.getElementById('sidebar-stop-btn');
  if (!dot || !label) return;

  if (StudioAPI.isConfigured()) {
    dot.className = 'connect-dot online';
    const url = StudioAPI.getBackendUrl();
    try {
      label.textContent = new URL(url).hostname;
    } catch {
      label.textContent = 'Connected';
    }
    if (btn) btn.textContent = 'Change';
    if (stopBtn) stopBtn.classList.remove('hidden');
  } else {
    dot.className = 'connect-dot offline';
    label.textContent = 'Not connected';
    if (btn) btn.textContent = 'Connect';
    if (stopBtn) stopBtn.classList.add('hidden');
  }
}

/** Show connect modal */
function showConnectModal() {
  const existing = document.getElementById('connect-modal-backdrop');
  if (existing) existing.remove();

  const currentUrl = StudioAPI.getBackendUrl();

  const backdrop = document.createElement('div');
  backdrop.id = 'connect-modal-backdrop';
  backdrop.className = 'connect-modal-backdrop';
  backdrop.innerHTML = `
    <div class="connect-modal">
      <div class="flex items-center justify-between mb-4">
        <h3 class="font-display font-bold text-lg text-slate-900 dark:text-white">Connect to Backend</h3>
        <button onclick="closeConnectModal()" class="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
          <i data-lucide="x" class="w-5 h-5 text-slate-400"></i>
        </button>
      </div>
      <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">
        Paste the tunnel URL from your Kaggle/Colab notebook. Run the notebook first to get the URL.
      </p>
      <div class="mb-4">
        <input id="connect-url-input" type="url" value="${currentUrl}" 
          placeholder="https://xxxx-xx-xx.ngrok-free.app"
          class="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 text-slate-900 dark:text-white placeholder-slate-400 font-mono"
        />
      </div>
      <div id="connect-status-msg" class="text-sm mb-4 hidden"></div>
      <div class="flex gap-3">
        <button id="connect-test-btn" onclick="testAndConnect()" class="flex-1 px-4 py-2.5 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 transition-colors text-sm">
          Test & Connect
        </button>
        ${currentUrl ? `
          <button onclick="disconnectBackend()" title="Disconnect UI from backend" class="px-3 py-2.5 rounded-xl border border-red-200 dark:border-red-900/50 text-red-600 dark:text-red-400 font-medium hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors text-sm">
            Disconnect
          </button>
          <button id="stop-server-btn" onclick="stopBackendServer()" title="Shut down the backend process" class="px-3 py-2.5 rounded-xl border border-red-500 bg-red-600 text-white font-medium hover:bg-red-700 transition-colors text-sm">
            Stop Server
          </button>
        ` : ''}
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeConnectModal();
  });
  lucide.createIcons();
  document.getElementById('connect-url-input').focus();
}

function closeConnectModal() {
  const backdrop = document.getElementById('connect-modal-backdrop');
  if (backdrop) backdrop.remove();
}

async function testAndConnect() {
  const input = document.getElementById('connect-url-input');
  const msg = document.getElementById('connect-status-msg');
  const btn = document.getElementById('connect-test-btn');
  const url = input.value.trim();

  if (!url) {
    msg.className = 'text-sm mb-4 text-red-500';
    msg.textContent = '⚠️ Please enter a URL';
    msg.classList.remove('hidden');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner spinner-dark"></span> Testing...';
  msg.className = 'text-sm mb-4 text-slate-500 dark:text-slate-400';
  msg.textContent = '⏳ Connecting...';
  msg.classList.remove('hidden');

  try {
    StudioAPI.setBackendUrl(url);
    const health = await StudioAPI.checkHealth();
    msg.className = 'text-sm mb-4 text-emerald-600 dark:text-emerald-400';
    msg.textContent = `✅ Connected! GPU: ${health.gpu_available ? '✅' : '❌'} | FFmpeg: ${health.ffmpeg_available ? '✅' : '❌'}`;
    updateConnectIndicator();

    setTimeout(() => closeConnectModal(), 1200);
  } catch (err) {
    StudioAPI.clearBackendUrl();
    msg.className = 'text-sm mb-4 text-red-500';
    msg.textContent = `❌ Connection failed: ${err.message}`;
    updateConnectIndicator();
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Test & Connect';
  }
}

function disconnectBackend() {
  StudioAPI.clearBackendUrl();
  updateConnectIndicator();
  closeConnectModal();
}

async function stopBackendServer() {
  const btn = document.getElementById('stop-server-btn');
  const msg = document.getElementById('connect-status-msg');

  if (!confirm('Are you sure you want to STOP the Kaggle backend server? You will have to restart the notebook cell manually.')) {
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner spinner-light"></span> Stopping...';
  }

  if (msg) {
    msg.className = 'text-sm mb-4 text-slate-500 dark:text-slate-400';
    msg.textContent = '⏳ Sending shutdown signal...';
    msg.classList.remove('hidden');
  }

  try {
    await StudioAPI.shutdownServer();
    if (msg) {
      msg.className = 'text-sm mb-4 text-emerald-600 dark:text-emerald-400';
      msg.textContent = '✅ Server stopped successfully.';
    }
  } catch (err) {
    // A fetch error is expected if the server dies immediately
    console.log('Server disconnected during shutdown:', err);
  } finally {
    setTimeout(() => {
      StudioAPI.clearBackendUrl();
      updateConnectIndicator();
      closeConnectModal();
    }, 1500);
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  updateConnectIndicator();
});
