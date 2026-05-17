/* ============================================================
   Windrose Save Tool UI — app.js
   Vanilla JS, no build step required.
   ============================================================ */

'use strict';

// ---- Configuration ----
const API = 'http://127.0.0.1:8765';

// ---- Module state ----
const S = {
  status: null,
  reportMeta: null,
  // Inventory — add tab
  addItems: [],
  addPlan: null,
  // Inventory — counts tab
  shipItems: [],
  // Coins
  coinMapping: null,
  // Backups
  backupDb: 'players',
};

let _catalogResults = [];
let _confirmResolve = null;
let _reportGenerating = false;

// ============================================================
// API client
// ============================================================
async function apiCall(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  const data = await res.json().catch(() => ({ detail: `HTTP ${res.status} — non-JSON response` }));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const get  = (path)        => apiCall('GET',  path);
const post = (path, body)  => apiCall('POST', path, body);
const put  = (path, body)  => apiCall('PUT',  path, body);

// ============================================================
// Utilities
// ============================================================
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function badge(text, cls) {
  return `<span class="badge badge-${cls}">${escHtml(text)}</span>`;
}

function confidenceBadge(conf) {
  const map = {
    manifest:            ['manifest',  'green'],
    confirmed:           ['confirmed', 'blue'],
    'explicit-unverified': ['explicit', 'orange'],
    assumed:             ['assumed',   'yellow'],
    high:                ['high',      'green'],
    medium:              ['medium',    'yellow'],
    low:                 ['low',       'red'],
  };
  const [label, cls] = map[conf] || [conf || '?', 'gray'];
  return badge(label, cls);
}

function statusDot(ok) {
  return `<span class="dot ${ok ? 'dot-ok' : 'dot-err'}"></span>`;
}

function spinner() {
  return `<span class="spinner"></span>`;
}

function card(content, cls = '') {
  return `<div class="card ${cls}">${content}</div>`;
}

// ============================================================
// Router
// ============================================================
const VIEWS = ['config', 'report', 'inventory', 'coins', 'backups'];

function currentView() {
  const h = location.hash.replace('#', '') || 'config';
  return VIEWS.includes(h) ? h : 'config';
}

async function render() {
  const view = currentView();
  document.querySelectorAll('#sidebar a').forEach(a => {
    a.classList.toggle('active', a.dataset.view === view);
  });
  const content = document.getElementById('content');
  content.innerHTML = `<div>${spinner()} Loading…</div>`;
  try {
    switch (view) {
      case 'config':    await renderConfig(content);    break;
      case 'report':    await renderReport(content);    break;
      case 'inventory': await renderInventory(content); break;
      case 'coins':     await renderCoins(content);     break;
      case 'backups':   await renderBackups(content);   break;
    }
  } catch (e) {
    content.innerHTML = card(`<p class="err">Failed to render screen: ${escHtml(e.message)}</p>`, 'card-err');
  }
}

window.addEventListener('hashchange', render);

// ============================================================
// Confirmation modal
// ============================================================
function showConfirm(title, bodyHtml) {
  return new Promise(resolve => {
    _confirmResolve = resolve;
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('confirm-modal').showModal();
  });
}

function _modalAction(ok) {
  document.getElementById('confirm-modal').close();
  if (_confirmResolve) { _confirmResolve(ok); _confirmResolve = null; }
}

// ============================================================
// Toast notifications
// ============================================================
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ============================================================
// Shared: apply result card
// ============================================================
function renderApplyResult(result, title) {
  const backup = result.backup_path
    ? `<p class="ok">✓ Backup: <span class="mono">${escHtml(result.backup_path)}</span></p>`
    : '';
  const tag = result.dry_run ? badge('DRY RUN — nothing written', 'yellow') : badge('WRITTEN', 'green');
  return card(`
    <h4>${escHtml(title)}</h4>
    <p>${tag}</p>
    ${backup}
    <details><summary class="muted small">Raw JSON</summary>
    <pre>${escHtml(JSON.stringify(result, null, 2))}</pre></details>
  `, result.dry_run ? 'card-info' : 'card-success');
}

// ============================================================
// CONFIG SCREEN
// ============================================================
async function renderConfig(container) {
  container.innerHTML = `
    <h2>Configuration</h2>
    <div class="form-group">
      <label>Save Root <small>(leave blank to auto-detect from AppData)</small></label>
      <div class="input-row">
        <input id="cfg-save-root" type="text" placeholder="Auto-detect" />
        <button onclick="clearField('cfg-save-root')">Clear</button>
      </div>
    </div>
    <div class="form-group">
      <label>Windrose Manifest Path <small>(leave blank to auto-detect from Steam)</small></label>
      <div class="input-row">
        <input id="cfg-manifest" type="text" placeholder="Auto-detect" />
        <button onclick="clearField('cfg-manifest')">Clear</button>
      </div>
    </div>
    <div class="form-group" id="captain-selector-group" style="display:none">
      <label><strong>Captain</strong> <small>(multiple captains found — select which one to edit)</small></label>
      <select id="cfg-captain" onchange="saveConfig()"></select>
    </div>
    <div class="btn-row">
      <button class="btn-primary" onclick="saveConfig()">Save Config</button>
    </div>
    <div id="config-status">${spinner()} Checking…</div>
  `;
  await loadConfigStatus();
}

async function loadConfigStatus() {
  const statusDiv = document.getElementById('config-status');
  if (!statusDiv) return;
  try {
    S.status = await get('/api/config');
    const saveRootInput = document.getElementById('cfg-save-root');
    const manifestInput = document.getElementById('cfg-manifest');
    if (saveRootInput) saveRootInput.value = S.status.save_root || '';
    if (manifestInput) manifestInput.value = S.status.manifest_path || '';
    renderCaptainSelector(S.status);
    updateSidebarCaptain(S.status);
    renderConfigStatus(statusDiv, S.status);
  } catch (e) {
    statusDiv.innerHTML = card(`<p class="err">Could not reach API: ${escHtml(e.message)}</p>`, 'card-err');
  }
}

function getActiveCaptainName(status) {
  if (!status) return null;
  const captains = status.captains || [];
  if (!captains.length) return null;
  if (captains.length === 1) return captains[0].name;
  const uuid = status.captain_uuid;
  if (uuid) {
    const match = captains.find(c => c.uuid === uuid);
    if (match) return match.name;
  }
  const def = captains.find(c => c.is_default);
  return def ? def.name : captains[0].name;
}

function updateSidebarCaptain(status) {
  const el = document.getElementById('sidebar-captain');
  const nameEl = document.getElementById('sidebar-captain-name');
  if (!el || !nameEl) return;
  const name = getActiveCaptainName(status);
  if (name) {
    nameEl.textContent = name;
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
}

function renderCaptainSelector(status) {
  const group = document.getElementById('captain-selector-group');
  const select = document.getElementById('cfg-captain');
  if (!group || !select) return;
  const captains = status.captains || [];
  if (captains.length <= 1) {
    group.style.display = 'none';
    return;
  }
  group.style.display = '';
  const currentUuid = status.captain_uuid || '';
  select.innerHTML = captains.map(c => {
    const label = `${escHtml(c.name)} — ${escHtml(c.uuid.slice(0, 8))}…${c.is_default ? ' (last used)' : ''}`;
    const selected = c.uuid === currentUuid || (!currentUuid && c.is_default) ? 'selected' : '';
    return `<option value="${escHtml(c.uuid)}" ${selected}>${label}</option>`;
  }).join('');
}

function renderConfigStatus(container, status) {
  const saveOk = !!status.resolved_save_root;
  const maniOk = !!status.manifest_found;
  const d = status.doctor;

  let rows = `
    <tr>
      <td>Save Root</td>
      <td class="mono">${escHtml(status.resolved_save_root || '—')}</td>
      <td>${statusDot(saveOk)} ${saveOk ? 'Found' : escHtml(status.save_root_error || 'Not found')}</td>
    </tr>
    <tr>
      <td>Manifest</td>
      <td class="mono">${escHtml(status.resolved_manifest_path || '—')}</td>
      <td>${statusDot(maniOk)} ${maniOk ? 'Found' : 'Not found — built-in aliases only'}</td>
    </tr>
  `;

  if (d) {
    rows += `
      <tr>
        <td>Players DB</td>
        <td class="mono">${escHtml(d.players?.path || '—')}</td>
        <td>${statusDot(!!d.players?.path)} ${d.players?.file_count || 0} files</td>
      </tr>
      <tr>
        <td>Accounts DB</td>
        <td class="mono">${escHtml(d.accounts?.path || '—')}</td>
        <td>${statusDot(!!d.accounts?.path)} ${d.accounts?.file_count || 0} files</td>
      </tr>
    `;
    const wr = d.windrose;
    if (wr?.found) {
      const divCount = d.divergence ? d.divergence.a_only.length + d.divergence.b_only.length : 0;
      rows += `
        <tr>
          <td>Windrose Mirror</td>
          <td class="mono">${escHtml(wr.path || '—')}</td>
          <td>${statusDot(divCount === 0)} ${divCount === 0 ? 'In sync' : `⚠ Diverged (+${d.divergence.a_only.length} R5, +${d.divergence.b_only.length} Windrose)`}</td>
        </tr>
      `;
    } else {
      rows += `
        <tr>
          <td>Windrose Mirror</td>
          <td class="mono">—</td>
          <td>${statusDot(false)} Not found (normal if Windrose is not installed)</td>
        </tr>
      `;
    }
  }

  container.innerHTML = card(`
    <h3>Status</h3>
    <table class="status-table">
      <thead><tr><th>Component</th><th>Resolved Path</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `);
}

async function saveConfig() {
  const save_root = (document.getElementById('cfg-save-root')?.value || '').trim() || null;
  const manifest_path = (document.getElementById('cfg-manifest')?.value || '').trim() || null;
  const captainEl = document.getElementById('cfg-captain');
  const captain_uuid = captainEl ? (captainEl.value || '').trim() || null : null;
  try {
    S.status = await put('/api/config', { save_root, manifest_path, captain_uuid });
    await loadConfigStatus();
    toast('Config saved', 'success');
  } catch (e) {
    toast(`Save failed: ${e.message}`, 'error');
  }
}

function clearField(id) {
  const el = document.getElementById(id);
  if (el) el.value = '';
}

// ============================================================
// REPORT SCREEN
// ============================================================
async function renderReport(container) {
  container.innerHTML = `
    <h2>Save Report</h2>
    <div class="btn-row">
      <button class="btn-primary" id="gen-btn" onclick="generateReport()">Generate Report</button>
      <button onclick="refreshReport()">↺ Refresh</button>
      <span id="report-meta" class="muted small"></span>
    </div>
    <div id="no-report" class="no-report" style="display:none">
      <p class="muted">No report yet — click Generate Report to create one.</p>
    </div>
    <div id="report-frame-wrap" style="display:none">
      <iframe id="report-frame" title="Windrose Save Report"
              sandbox="allow-scripts allow-same-origin"></iframe>
    </div>
  `;
  await refreshReport();
}

async function generateReport() {
  if (_reportGenerating) return;
  _reportGenerating = true;
  const btn = document.getElementById('gen-btn');
  const meta = document.getElementById('report-meta');
  if (btn) btn.disabled = true;
  if (meta) meta.innerHTML = spinner() + ' Generating…';
  try {
    S.reportMeta = await post('/api/report/generate', {});
    toast('Report generated', 'success');
    await refreshReport();
  } catch (e) {
    toast(`Failed: ${e.message}`, 'error');
    if (meta) meta.textContent = 'Generation failed';
  } finally {
    _reportGenerating = false;
    if (btn) btn.disabled = false;
  }
}

async function refreshReport() {
  const frame = document.getElementById('report-frame');
  const wrap = document.getElementById('report-frame-wrap');
  const noReport = document.getElementById('no-report');
  const meta = document.getElementById('report-meta');
  if (!frame) return;

  // Probe with GET because this backend returns 405 for HEAD on FileResponse routes.
  try {
    const res = await fetch(`${API}/api/report/latest?_probe=${Date.now()}`, {
      method: 'GET',
      cache: 'no-store',
    });
    if (res.ok) {
      frame.src = `${API}/api/report/latest?_ts=${Date.now()}`;
      if (wrap)     wrap.style.display = '';
      if (noReport) noReport.style.display = 'none';
      if (meta && S.reportMeta) meta.textContent = `Generated ${S.reportMeta.generated_at}`;
    } else {
      if (wrap)     wrap.style.display = 'none';
      if (noReport) noReport.style.display = '';
      if (meta) meta.textContent = '';
    }
  } catch (_) {
    if (wrap)     wrap.style.display = 'none';
    if (noReport) noReport.style.display = '';
  }
}

// ============================================================
// INVENTORY SCREEN
// ============================================================
async function renderInventory(container) {
  container.innerHTML = `
    <h2>Inventory</h2>
    <div class="tab-bar">
      <button class="tab active" onclick="switchInvTab('add', this)">Add Items to Ship</button>
      <button class="tab" onclick="switchInvTab('counts', this)">Edit Ship Stack Counts</button>
    </div>
    <div id="inv-content"></div>
  `;
  renderInvAdd(document.getElementById('inv-content'));
}

async function switchInvTab(tab, btn) {
  document.querySelectorAll('.tab-bar .tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const content = document.getElementById('inv-content');
  if (!content) return;
  if (tab === 'add') {
    renderInvAdd(content);
  } else {
    await renderInvCounts(content);
  }
}

// ---- Add Items Tab ----
function renderInvAdd(container) {
  container.innerHTML = `
    <div class="inv-add-toolbar">
      <button class="btn-primary" onclick="openItemPicker()">+ Add Item</button>
    </div>
    <div id="add-items-list">
      ${S.addItems.length === 0
        ? '<p class="muted empty-hint">No items added. Click "+ Add Item" to begin.</p>'
        : buildAddItemsTable()}
    </div>
    <div class="btn-row" id="add-actions" style="${S.addItems.length === 0 ? 'display:none' : ''}">
      <button onclick="dryRunShipAdd()">Dry Run Preview</button>
      <button class="btn-primary" onclick="applyShipAdd()">Apply ▶</button>
      <button class="btn-ghost" onclick="clearAddItems()">Clear All</button>
    </div>
    <div id="add-result"></div>
  `;
  searchItemCatalog('');
}

function buildAddItemsTable() {
  return `
    <table class="items-table">
      <thead><tr><th>Item</th><th>Asset</th><th>Confidence</th><th>Count</th><th></th></tr></thead>
      <tbody>
        ${S.addItems.map((item, i) => `
          <tr>
            <td class="item-cell">
              <strong>${escHtml(item.displayLabel)}</strong>
              ${item.inGameLabel && item.inGameLabel !== item.displayLabel
                ? `<div class="small muted">In-game label: ${escHtml(item.inGameLabel)}</div>`
                : ''}
            </td>
            <td class="mono asset-cell">${escHtml(item.assetPath.split('/').pop() || item.assetPath)}</td>
            <td>${confidenceBadge(item.confidence)}</td>
            <td>
              <input type="number" class="count-input" value="${item.count}" min="1" max="99999"
                     oninput="updateAddCount(${i}, this.value)" />
            </td>
            <td><button class="btn-icon" onclick="removeAddItem(${i})">✕</button></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function searchItemCatalog(query) {
  const resultsDiv = document.getElementById('picker-results');
  if (!resultsDiv) return;
  try {
    const data = await get(`/api/inventory/catalog?query=${encodeURIComponent(query || '')}&limit=25`);
    _catalogResults = data.results;
    if (!_catalogResults.length) {
      resultsDiv.innerHTML = '<p class="muted" style="padding:12px">No items found.</p>';
      return;
    }
    resultsDiv.innerHTML = _catalogResults.map((item, i) => `
      <div class="picker-item" onclick="selectItem(${i})">
        <div class="picker-item-name">${escHtml(item.in_game_label || item.display_label)}</div>
        <div class="picker-item-meta">
          ${confidenceBadge(item.mapping_confidence)}
          <span class="small muted">${escHtml(item.asset_name || '')}</span>
          <span class="small muted">${escHtml(item.asset_path.split('/').pop() || '')}</span>
        </div>
      </div>
    `).join('');
  } catch (e) {
    resultsDiv.innerHTML = `<p class="err" style="padding:12px">Search failed: ${escHtml(e.message)}</p>`;
  }
}

function openItemPicker() {
  const overlay = document.getElementById('item-picker-overlay');
  if (overlay) {
    overlay.classList.remove('hidden');
    const search = document.getElementById('picker-search');
    if (search) { search.value = ''; search.focus(); }
    searchItemCatalog('');
  }
}

function closeItemPicker() {
  document.getElementById('item-picker-overlay')?.classList.add('hidden');
}

function selectItem(i) {
  const item = _catalogResults[i];
  if (!item) return;
  const alreadyAdded = S.addItems.some(a => a.assetPath === item.asset_path);
  if (!alreadyAdded) {
    S.addItems.push({
      target: item.alias || item.asset_name || item.requested_value,
      displayLabel: item.display_label,
      inGameLabel: item.in_game_label || item.display_label,
      assetPath: item.asset_path,
      confidence: item.mapping_confidence,
      count: 10,
    });
  }
  closeItemPicker();
  const listDiv = document.getElementById('add-items-list');
  const actionsDiv = document.getElementById('add-actions');
  if (listDiv) listDiv.innerHTML = buildAddItemsTable();
  if (actionsDiv) actionsDiv.style.display = '';
}

function updateAddCount(idx, val) {
  if (S.addItems[idx]) S.addItems[idx].count = Math.max(1, parseInt(val) || 1);
}

function removeAddItem(idx) {
  S.addItems.splice(idx, 1);
  const listDiv = document.getElementById('add-items-list');
  const actionsDiv = document.getElementById('add-actions');
  if (listDiv) listDiv.innerHTML = S.addItems.length === 0
    ? '<p class="muted empty-hint">No items added. Click "+ Add Item" to begin.</p>'
    : buildAddItemsTable();
  if (actionsDiv) actionsDiv.style.display = S.addItems.length === 0 ? 'none' : '';
}

function clearAddItems() {
  S.addItems = [];
  renderInvAdd(document.getElementById('inv-content'));
}

async function dryRunShipAdd() {
  if (!S.addItems.length) return;
  const resultDiv = document.getElementById('add-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Planning…';
  try {
    const result = await post('/api/inventory/ship-add', {
      targets: S.addItems.map(i => ({ target: i.target, count: i.count })),
      dry_run: true,
    });
    S.addPlan = result;
    if (resultDiv) resultDiv.innerHTML = buildShipAddPreview(result);
  } catch (e) {
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

function buildShipAddPreview(result) {
  const items = result.planned_updates || [];
  const assumed = result.assumed_mappings || [];
  const warnHtml = assumed.length
    ? `<p class="warn">⚠ ${assumed.length} item(s) use assumed asset IDs — verify before applying.</p>`
    : '';
  const rows = items.map(p => `
    <tr>
      <td class="item-cell">${escHtml(p.requested)}</td>
      <td class="mono asset-cell">${escHtml(p.asset_path.split('/').pop() || '')}</td>
      <td>${escHtml(String(p.count))}</td>
      <td>Slot ${escHtml(String(p.slot_index ?? '?'))}</td>
      <td>${confidenceBadge(p.mapping_confidence)}</td>
    </tr>
  `).join('');
  return card(`
    <h4>Dry Run Preview — ${items.length} item(s)</h4>
    ${warnHtml}
    <table class="items-table">
      <thead><tr><th>Item</th><th>Asset</th><th>Count</th><th>Slot</th><th>Confidence</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="muted small">Ship key: ${escHtml((result.key_hex || '').slice(0, 24))}…</p>
  `, 'card-info');
}

async function applyShipAdd() {
  if (!S.addItems.length) return;
  const hasAssumed = S.addItems.some(i => i.confidence === 'assumed');
  const listHtml = `<ul>${S.addItems.map(i =>
    `<li>${escHtml(i.displayLabel)} × ${i.count} ${confidenceBadge(i.confidence)}</li>`
  ).join('')}</ul>`;
  const warnHtml = hasAssumed
    ? '<p class="warn">⚠ Some items use assumed asset IDs. Proceed carefully.</p>'
    : '';
  const ok = await showConfirm(
    'Apply Ship Inventory Add',
    `<p>Write ${S.addItems.length} item(s) to ship chest:</p>${listHtml}
     <p>A backup will be created automatically before writing.</p>${warnHtml}`
  );
  if (!ok) return;

  const resultDiv = document.getElementById('add-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Applying…';
  try {
    const result = await post('/api/inventory/ship-add', {
      targets: S.addItems.map(i => ({ target: i.target, count: i.count })),
      dry_run: false,
      allow_assumed_assets: hasAssumed,
    });
    toast('Items added to ship', 'success');
    if (resultDiv) resultDiv.innerHTML = renderApplyResult(result, 'Ship Add Applied');
    S.addItems = [];
    const listDiv = document.getElementById('add-items-list');
    const actionsDiv = document.getElementById('add-actions');
    if (listDiv) listDiv.innerHTML = '<p class="muted empty-hint">Done. Click "+ Add Item" to add more.</p>';
    if (actionsDiv) actionsDiv.style.display = 'none';
  } catch (e) {
    toast(`Failed: ${e.message}`, 'error');
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

// ---- Edit Ship Counts Tab ----
async function renderInvCounts(container) {
  container.innerHTML = `<p>${spinner()} Loading ship inventory…</p>`;
  try {
    const data = await get('/api/inventory/inspect');
    S.shipItems = (data.items || []).filter(i => i.inventory_scope === 'ship_storage');
    const cap = data.capacity || {};

    if (!S.shipItems.length) {
      container.innerHTML = card(`
        <h4>Ship Storage</h4>
        <p class="muted">No items found in ship storage slots.</p>
        <p class="muted small">${cap.ship_used_slots_observed || 0} / ${cap.ship_total_capacity || 28} slots used</p>
      `);
      return;
    }

    // Group items by ship_name (falling back to key_hex prefix)
    const groups = new Map();
    S.shipItems.forEach((item, i) => {
      const shipLabel = item.ship_name || item.key_hex?.slice(0, 8) || 'Unknown Ship';
      if (!groups.has(shipLabel)) groups.set(shipLabel, []);
      groups.get(shipLabel).push({ item, idx: i });
    });

    let html = '';
    groups.forEach((entries, shipLabel) => {
      const rows = entries.map(({ item, idx }) => {
        const assetTail = (item.item_params || '').split('/').pop() || '?';
        return `
          <tr>
            <td class="item-cell"><strong>${escHtml(item.item_name || '?')}</strong></td>
            <td class="mono asset-cell">${escHtml(assetTail)}</td>
            <td>${item.count ?? '?'}</td>
            <td>
              <div class="input-row compact">
                <input type="number" class="count-input" id="cnt-${idx}"
                       value="${item.count ?? 0}" min="0" max="99999" />
                <button onclick="applyShipCount(${idx})">Set</button>
              </div>
            </td>
            <td>${confidenceBadge('confirmed')}</td>
          </tr>
        `;
      }).join('');

      const slotCount = entries.length;
      html += card(`
        <div class="card-header-row">
          <h4>⚓ ${escHtml(shipLabel)}</h4>
          <span class="muted small">${slotCount} item stack${slotCount !== 1 ? 's' : ''}</span>
        </div>
        <table class="items-table">
          <thead><tr><th>Item</th><th>Asset</th><th>Current</th><th>New Count</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `);
    });

    html += `<p class="muted small" style="margin-top:0.5rem">${cap.ship_used_slots_observed || 0} / ${cap.ship_total_capacity || 28} total slots used, ${cap.ship_free_slots || 0} free</p>`;
    html += `<div id="count-result"></div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = card(`<p class="err">Failed: ${escHtml(e.message)}</p>`, 'card-err');
  }
}

async function applyShipCount(idx) {
  const item = S.shipItems[idx];
  if (!item) return;
  const input = document.getElementById(`cnt-${idx}`);
  const newCount = parseInt(input?.value ?? '0', 10);
  const currentCount = typeof item.count === 'number' ? item.count : null;

  const ok = await showConfirm(
    'Edit Ship Stack Count',
    `<p>Change <strong>${escHtml(item.item_name || '?')}</strong> from <strong>${currentCount ?? '?'}</strong> → <strong>${newCount}</strong></p>
     <p>A backup will be created before writing.</p>`
  );
  if (!ok) return;

  const resultDiv = document.getElementById('count-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Applying…';
  try {
    const result = await post('/api/inventory/ship-count', {
      target: item.item_params || item.item_name,
      new_count: newCount,
      expected_current_count: currentCount,
      dry_run: false,
    });
    toast(`Updated ${item.item_name} to ${newCount}`, 'success');
    if (resultDiv) resultDiv.innerHTML = renderApplyResult(result, 'Count Updated');
    // Reload to show fresh counts
    setTimeout(() => renderInvCounts(document.getElementById('inv-content')), 800);
  } catch (e) {
    toast(`Failed: ${e.message}`, 'error');
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

// ============================================================
// COINS SCREEN
// ============================================================
async function renderCoins(container) {
  container.innerHTML = `
    <h2>Coins</h2>
    <div class="warn-box">
      <strong>⚠ Advanced tool</strong> — coin edits use offset calibration.
      Guinea and calibrated ship piastre are reliable.
      Player piastre has lower confidence; use with care.
    </div>

    <div class="section-block">
      <h3>Step 1 — Enter Current Coin Values</h3>
      <p class="muted small">Enter the coin counts visible in-game right now to calibrate save offsets.</p>
      <div class="coin-grid">
        <div class="form-group">
          <label>Person Piastre <span class="warn-label">⚠ lower confidence</span></label>
          <input id="coin-pp" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>Person Guinea</label>
          <input id="coin-pg" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>Ship Piastre</label>
          <input id="coin-sp" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>Ship Guinea</label>
          <input id="coin-sg" type="number" value="0" min="0" />
        </div>
      </div>
      <div class="btn-row">
        <button class="btn-primary" onclick="calibrateCoins()">Calibrate Offsets</button>
      </div>
      <div id="calib-result"></div>
    </div>

    <div class="section-block" id="coin-set-block" style="display:none">
      <h3>Step 2 — Set New Values</h3>
      <p class="muted small">Leave a field at 0 to skip that coin type.</p>
      <div class="coin-grid">
        <div class="form-group">
          <label>New Person Piastre <span class="warn-label">⚠ lower confidence</span></label>
          <input id="new-pp" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>New Person Guinea <span class="ok-label">✓ reliable</span></label>
          <input id="new-pg" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>New Ship Piastre <span class="ok-label">✓ calibrated</span></label>
          <input id="new-sp" type="number" value="0" min="0" />
        </div>
        <div class="form-group">
          <label>New Ship Guinea <span class="ok-label">✓ reliable</span></label>
          <input id="new-sg" type="number" value="0" min="0" />
        </div>
      </div>
      <div class="btn-row">
        <button onclick="dryRunCoins()">Dry Run Preview</button>
        <button class="btn-primary" onclick="applyCoins()">Apply ▶</button>
      </div>
      <div id="coin-apply-result"></div>
    </div>
  `;
}

async function calibrateCoins() {
  const resultDiv = document.getElementById('calib-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Calibrating…';

  const pp = parseInt(document.getElementById('coin-pp')?.value || '0', 10);
  const pg = parseInt(document.getElementById('coin-pg')?.value || '0', 10);
  const sp = parseInt(document.getElementById('coin-sp')?.value || '0', 10);
  const sg = parseInt(document.getElementById('coin-sg')?.value || '0', 10);

  try {
    S.coinMapping = await post('/api/coins/map', {
      person_piastre: pp, person_guinea: pg,
      ship_piastre: sp,   ship_guinea: sg,
    });

    const mappings = S.coinMapping.mappings || {};
    const rows = Object.entries(mappings).map(([label, m]) => {
      if (!m) return `<tr><td>${escHtml(label)}</td><td colspan="3" class="err">Not found</td></tr>`;
      return `
        <tr>
          <td>${escHtml(label)}</td>
          <td>${confidenceBadge(m.confidence)}</td>
          <td class="mono">offset ${m.value_offset ?? '?'}  dist ${m.distance ?? '?'}</td>
          <td class="muted small">${escHtml(m.source || '?')}</td>
        </tr>
      `;
    }).join('');

    if (resultDiv) resultDiv.innerHTML = card(`
      <h4>Calibration Result</h4>
      <table class="items-table">
        <thead><tr><th>Coin</th><th>Confidence</th><th>Offset</th><th>Source</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `, 'card-info');

    // Reveal set section and pre-fill with current values
    const setBlock = document.getElementById('coin-set-block');
    if (setBlock) {
      setBlock.style.display = '';
      document.getElementById('new-pp').value = pp;
      document.getElementById('new-pg').value = pg;
      document.getElementById('new-sp').value = sp;
      document.getElementById('new-sg').value = sg;
    }

    toast('Calibration complete', 'success');
  } catch (e) {
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
    toast(`Calibration failed: ${e.message}`, 'error');
  }
}

function _coinSetPayload(dry_run) {
  const int = (id) => parseInt(document.getElementById(id)?.value || '0', 10);
  const nonzero = (n) => n > 0 ? n : null;
  return {
    known_person_piastre: int('coin-pp'), known_person_guinea: int('coin-pg'),
    known_ship_piastre:   int('coin-sp'), known_ship_guinea:   int('coin-sg'),
    new_person_piastre:  nonzero(int('new-pp')),
    new_person_guinea:   nonzero(int('new-pg')),
    new_ship_piastre:    nonzero(int('new-sp')),
    new_ship_guinea:     nonzero(int('new-sg')),
    dry_run,
  };
}

async function dryRunCoins() {
  const resultDiv = document.getElementById('coin-apply-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Previewing…';
  try {
    const result = await post('/api/coins/set', _coinSetPayload(true));
    if (resultDiv) resultDiv.innerHTML = renderApplyResult(result, 'Coin Dry Run');
  } catch (e) {
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

async function applyCoins() {
  const ok = await showConfirm(
    'Apply Coin Changes',
    '<p>Write new coin values to the save file?</p><p>A backup will be created automatically before writing.</p>'
  );
  if (!ok) return;
  const resultDiv = document.getElementById('coin-apply-result');
  if (resultDiv) resultDiv.innerHTML = spinner() + ' Applying…';
  try {
    const result = await post('/api/coins/set', _coinSetPayload(false));
    toast('Coins updated', 'success');
    if (resultDiv) resultDiv.innerHTML = renderApplyResult(result, 'Coin Values Applied');
  } catch (e) {
    toast(`Failed: ${e.message}`, 'error');
    if (resultDiv) resultDiv.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

// ============================================================
// BACKUPS SCREEN
// ============================================================
async function renderBackups(container) {
  container.innerHTML = `
    <h2>Backups</h2>
    <div class="tab-bar">
      <button class="tab ${S.backupDb === 'players'  ? 'active' : ''}"
              onclick="switchBackupTab('players', this)">Players DB</button>
      <button class="tab ${S.backupDb === 'accounts' ? 'active' : ''}"
              onclick="switchBackupTab('accounts', this)">Accounts DB</button>
    </div>
    <div id="backup-wrap">${spinner()} Loading…</div>
  `;
  await loadBackups(S.backupDb);
}

async function switchBackupTab(db, btn) {
  S.backupDb = db;
  document.querySelectorAll('.tab-bar .tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  await loadBackups(db);
}

async function loadBackups(db) {
  const wrap = document.getElementById('backup-wrap');
  if (!wrap) return;
  wrap.innerHTML = spinner() + ' Loading…';
  try {
    const data = await get(`/api/backups/${db}`);
    if (!data.backups.length) {
      wrap.innerHTML = card(`<p class="muted">No backups found for ${escHtml(db)} database.</p>`);
      return;
    }
    const rows = data.backups.map(b => {
      const info = b.details || {};
      const sizeMb = ((b.size_bytes || 0) / 1048576).toFixed(1);
      const created = (info.created_at || '?').replace('T', ' ');
      return `
        <tr>
          <td class="mono backup-name-cell">${escHtml(b.backup_name)}</td>
          <td>${escHtml(created)}</td>
          <td>${sizeMb} MB</td>
          <td>${info.file_count || '?'}</td>
          <td>
            <button class="btn-warn"
                    onclick="restoreBackup('${escHtml(db)}', '${escHtml(b.backup_name)}')">
              ↩ Restore
            </button>
          </td>
        </tr>
      `;
    }).join('');
    wrap.innerHTML = card(`
      <p class="muted small">DB: <span class="mono">${escHtml(data.resolved_db_path || '?')}</span></p>
      <table class="items-table" style="margin-top:10px">
        <thead><tr><th class="backup-name-col">Backup Name</th><th>Created</th><th>Size</th><th>Files</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `);
  } catch (e) {
    wrap.innerHTML = card(`<p class="err">Failed: ${escHtml(e.message)}</p>`, 'card-err');
  }
}

async function restoreBackup(db, backupName) {
  const ok = await showConfirm(
    'Restore Backup',
    `<p>Restore <strong>${escHtml(backupName)}</strong> to the live ${escHtml(db)} database?</p>
     <p class="warn">⚠ This replaces the active database. Close the game first.</p>
     <p class="warn">⚠ Changes made after this backup was taken will be lost.</p>`
  );
  if (!ok) return;

  const wrap = document.getElementById('backup-wrap');
  if (wrap) wrap.innerHTML = spinner() + ' Restoring…';
  try {
    const result = await post(`/api/backups/${encodeURIComponent(db)}/restore`, { backup_name: backupName });
    toast(`Restored ${backupName}`, 'success');
    if (wrap) {
      const exact = result.matches_backup;
      wrap.innerHTML = card(`
        <h4>Restore Complete</h4>
        <p class="${exact ? 'ok' : 'warn'}">File count: ${result.restored_file_count} / ${result.expected_file_count} ${exact ? '✓' : '⚠'}</p>
        <p>CURRENT: <span class="mono">${escHtml(result.current_marker || '?')}</span></p>
        <div class="btn-row"><button onclick="loadBackups('${escHtml(db)}')">← Back to list</button></div>
      `, exact ? 'card-success' : 'card-warn');
    }
  } catch (e) {
    toast(`Restore failed: ${e.message}`, 'error');
    if (wrap) wrap.innerHTML = card(`<p class="err">${escHtml(e.message)}</p>`, 'card-err');
  }
}

// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('modal-cancel')?.addEventListener('click', () => _modalAction(false));
  document.getElementById('modal-ok')?.addEventListener('click',     () => _modalAction(true));

  // Close item picker when clicking the overlay backdrop
  document.getElementById('item-picker-overlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) closeItemPicker();
  });

  // Pre-fetch status so the sidebar captain name is visible on any initial view
  get('/api/config').then(status => {
    S.status = status;
    updateSidebarCaptain(status);
  }).catch(() => {});

  render();
});

window.addEventListener('hashchange', render);
