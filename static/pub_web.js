'use strict';

const REFRESH_MS = 60_000;
const API_BASE = '/api';
let lastStatus = [];
let lastFetchAt = null;
let openMenuDevice = null;
let modalReturnFocus = null;
let currentUser = null;
let bgThresholds = {};
let bgDefaults = null;
let bgModalDevice = null;
let bgModalReturnFocus = null;
let connectedDevices = new Set();   // stations with a live WebSocket on Render

/* ---------- helpers ---------- */
function el(id) { return document.getElementById(id); }

function fmtSGT(iso) {
    if (!iso) return '--';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Singapore',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    }).formatToParts(d);
    const g = t => parts.find(p => p.type === t)?.value || '';
    return `${g('day')}/${g('month')}/${g('year')}, ${g('hour')}:${g('minute')}:${g('second')} SGT`;
}

function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
}

function toast(msg, type = '') {
    let t = document.querySelector('.toast');
    if (!t) {
        t = document.createElement('div');
        t.className = 'toast';
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.className = 'toast show ' + type;
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.className = 'toast ' + type, 3200);
}

// function bgClass(device, value) {
//     const t = bgThresholds[device];
//     if (!t) return '';
//     const v = Number(value);
//     if (isNaN(v)) return '';
//     if (v < t.good_below) return 'bg-good';
//     if (v <= t.avg_to)    return 'bg-average';
//     return 'bg-bad';
// }

/* ---------- data ---------- */
async function fetchStatus() {
    const resp = await fetch(`${API_BASE}/devices/status`, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    return body.devices || [];
}

async function fetchConnectedDevices() {
    try {
        const resp = await fetch(`${API_BASE}/devices/connected`, { cache: 'no-store' });
        if (!resp.ok) return new Set();
        const body = await resp.json();
        return new Set(body.online || []);
    } catch (_) {
        return new Set();
    }
}

function showLogin(message = '') {
    closeAllMenus();
    closeModal();
    closeBgModal();
    currentUser = null;
    lastStatus = [];
    el('loginError').textContent = message;
    el('loginModal').hidden = false;
    el('loginPassword').value = '';
    setTimeout(() => el('loginUsername').focus(), 0);
}

function setCurrentUser(user) {
    currentUser = user;
    el('downloadAllBtn').innerHTML = user.role === 'admin'
        ? '<i class="fas fa-file-archive"></i> Download All'
        : '<i class="fas fa-file-download"></i> Download Data';
    el('downloadAllBtn').title = user.role === 'admin'
        ? 'Export data from all devices'
        : `Export data from ${user.device}`;
    el('loginModal').hidden = true;
}

async function login(event) {
    event.preventDefault();
    const submit = el('loginForm').querySelector('button[type="submit"]');
    submit.disabled = true;
    el('loginError').textContent = '';
    try {
        const resp = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: el('loginUsername').value, password: el('loginPassword').value }),
        });
        const user = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(user.error || 'Sign in failed');
        setCurrentUser(user);
        await refresh();
    } catch (err) {
        el('loginError').textContent = err.message;
    } finally {
        submit.disabled = false;
    }
}

async function logout() {
    await fetch(`${API_BASE}/auth/logout`, { method: 'POST' }).catch(() => {});
    showLogin('You have been logged out.');
}

async function refresh() {
    try {
        const [status, connected] = await Promise.all([
            fetchStatus(),
            fetchConnectedDevices(),
        ]);
        lastStatus = status;
        connectedDevices = connected;
        lastFetchAt = new Date();

        lastStatus.forEach(entry => {
            if (entry.bg_thresholds) {
                bgThresholds[entry.device] = entry.bg_thresholds;
            }
        });

        const lastCheck = el('lastCheck');
        if (lastCheck) lastCheck.textContent = fmtSGT(lastFetchAt.toISOString());
        const online = lastStatus.filter(d => d.online).length;
        const total = lastStatus.length;

        el('liveText').textContent = `${online} of ${total} online`;
        el('liveDot').className = 'dot ' + (online > 0 ? 'online' : 'offline');

        renderCards();
    } catch (err) {
        console.error(err);
        if (err.message === 'HTTP 401') {
            showLogin('Your session has ended. Please sign in again.');
            return;
        }
        el('liveText').textContent = 'Connection error';
        el('liveDot').className = 'dot offline';
        toast('Failed to reach server', 'error');
    }
}

/* ---------- render cards ---------- */
function statBlock(label, value, unit, dim, cls = '') {
    return `
        <div class="stat${dim ? ' dim' : ''}">
            <span class="stat-label">${label}</span>
            <span class="stat-value ${cls}">${value}<small>${unit}</small></span>
        </div>`;
}

function renderCards() {
    const grid = el('cardsGrid');

    if (!lastStatus.length) {
        grid.innerHTML = `
            <div class="loading">
                <i class="fas fa-satellite-dish"></i>
                <p>No devices configured.</p>
            </div>`;
        return;
    }

    const sorted = [...lastStatus].sort((a, b) => {
        if (a.online !== b.online) return a.online ? -1 : 1;
        if (!!a.last_seen !== !!b.last_seen) return a.last_seen ? -1 : 1;
        return a.device.localeCompare(b.device);
    });

    grid.innerHTML = sorted.map(entry => {
        const { device, label = device, online, last_seen, latest } = entry;

        let statusClass, statusText;
        if (online) { statusClass = 'online'; statusText = 'Online'; }
        else if (last_seen) { statusClass = 'offline'; statusText = 'Offline'; }
        else { statusClass = 'unknown'; statusText = 'Offline'; }

        const hasData = !!latest;
        const batt = hasData ? Number(latest.batt_volt ?? 0).toFixed(2) : '--';
        const bgTemp  = hasData ? Number(latest.bg_temp ?? 0).toFixed(1) : '--';
        const airTemp = hasData ? Number(latest.air_temp ?? 0).toFixed(1) : '--';
        const hum     = hasData ? Number(latest.rel_humidity ?? 0).toFixed(1) : '--';
        const wbgt    = hasData ? Number(latest.wbgt ?? 0).toFixed(2) : '--';
        const tsSGT = last_seen ? fmtSGT(last_seen) : '--';
        const dim = !hasData;
        const wsOnline = connectedDevices.has(device);

        return `
        <div class="card ${statusClass}" data-device="${esc(device)}">
            <div class="card-header">
                <div class="card-title">
                    <h2>${esc(label)}</h2>
                    <span class="batt-inline${dim ? ' dim' : ''}">v: ${batt} V</span>
                </div>
                <div class="card-header-right">
                    <span class="status-badge ${statusClass}">
                        <i class="fas fa-circle"></i> ${statusText}
                    </span>
                    <div class="card-menu-wrap">
                        <button class="card-menu-btn" type="button" data-device="${esc(device)}" aria-label="Actions for ${esc(device)}" aria-expanded="false" title="Device actions">
                            <i class="fas fa-chevron-down"></i>
                        </button>
                        <div class="card-menu" data-menu-device="${esc(device)}" hidden>
                            <button type="button" data-action="download">
                                <i class="fas fa-download"></i> Download range
                            </button>
                            <button type="button" data-action="email">
                                <i class="fas fa-envelope"></i> Send by email
                            </button>
                            <button type="button" data-action="bg-thresholds">
                                <i class="fas fa-sliders-h"></i> Edit BG thresholds
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="stats-grid">
                ${statBlock('Blackglobe Temp (C)',  bgTemp, ' °C', dim)}
                ${statBlock('Rel Humidity', hum,  ' %',  dim)}
                ${statBlock('Air Temp', airTemp, ' °C', dim)}
                ${statBlock('WBGT',     wbgt, ' °C', dim)}
            </div>

            <div class="card-footer-simple">
                <div class="card-footer-left">
                    <span class="footer-label">Last update</span>
                    <span class="footer-value">${tsSGT}</span>
                    <span class="ws-status ${wsOnline ? 'ws-online' : 'ws-offline'}"
                          title="${wsOnline ? 'Live WebSocket connected' : 'No live WebSocket'}">
                        <i class="fas fa-plug"></i> ${wsOnline ? 'live' : 'no live link'}
                    </span>
                </div>
                <button class="btn-edit-bg" type="button" data-device="${esc(device)}" title="Edit BG thresholds">
                    <i class="fas fa-sliders-h"></i> Edit BG
                </button>
            </div>
        </div>`;
    }).join('');

    grid.querySelectorAll('.card-menu-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            toggleMenu(btn.dataset.device);
        });
    });

    grid.querySelectorAll('.card-menu button').forEach(b => {
        b.addEventListener('click', e => {
            e.stopPropagation();
            const device = b.closest('.card-menu').dataset.menuDevice;
            const action = b.dataset.action;
            closeAllMenus();
            if (action === 'download') openModal(device, 'download');
            else if (action === 'email') openModal(device, 'email');
            else if (action === 'bg-thresholds') openBgModal(device);
        });
    });

    grid.querySelectorAll('.btn-edit-bg').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            openBgModal(btn.dataset.device);
        });
    });
}

/* ---------- dropdown menu control ---------- */
function closeAllMenus() {
    document.querySelectorAll('.card-menu').forEach(m => {
        m.hidden = true;
        const trigger = m.parentElement?.querySelector('.card-menu-btn');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
    openMenuDevice = null;
}

function toggleMenu(device) {
    const menu = document.querySelector(`.card-menu[data-menu-device="${CSS.escape(device)}"]`);
    if (!menu) return;
    const wasHidden = menu.hidden;
    closeAllMenus();
    if (wasHidden) {
        menu.hidden = false;
        openMenuDevice = device;
        const trigger = menu.parentElement?.querySelector('.card-menu-btn');
        if (trigger) trigger.setAttribute('aria-expanded', 'true');
    }
}

document.addEventListener('click', () => closeAllMenus());

/* ---------- download helpers ---------- */
function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function localInputValue(date) {
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function selectedDevices() {
    return [...document.querySelectorAll('#deviceOptions input:checked')].map(input => input.value);
}

function renderDeviceOptions(preselect) {
    const devices = lastStatus.length
        ? lastStatus.map(item => ({ id: item.device, label: item.label || item.device }))
        : [
            { id: 'KNF-B452BF260717021', label: 'KNF' },
            { id: 'KWRP-B452BF260731002', label: 'KWRP' },
            { id: 'JWRP-B452BF260731009', label: 'JWRP' },
            { id: 'UPWRP-B452BF260731003', label: 'UPWRP' },
            { id: 'CWRP-B452BF260717023', label: 'CWRP' },
        ];

    const isAllPreselected = !preselect || preselect === 'all';
    el('deviceOptions').innerHTML = devices.map(({ id, label }) => {
        const checked = isAllPreselected || id === preselect;
        return `
        <label class="device-choice">
            <input type="checkbox" value="${esc(id)}" ${checked ? 'checked' : ''}>
            <span>${esc(label)}</span>
        </label>`;
    }).join('');
}

function exportParams() {
    const from = el('fromDate').value;
    const to = el('toDate').value;
    if (!from || !to) throw new Error('Choose both dates');
    if (new Date(from) > new Date(to)) throw new Error('The start date must be before the end date');
    const devices = selectedDevices();
    if (!devices.length) throw new Error('Choose at least one device');
    return { from: new Date(from).toISOString(), to: new Date(to).toISOString(), devices };
}

function emailContent(template, filters) {
    const range = `${el('fromDate').value.replace('T', ' ')} to ${el('toDate').value.replace('T', ' ')}`;
    const devices = filters.devices.join(', ');
    const subjects = { report: `PUB device data report - ${range}`, blank: '' };
    const bodies = {
        report: `Hello,\n\nAttached is the PUB data report for ${range}.\nIncluded devices: ${devices}\n\nRegards`,
        blank: ''
    };
    return { subject: subjects[template], body: bodies[template] };
}

/* ---------- modal ---------- */
function modalSetMethod(method) {
    document.querySelectorAll('.modal-option').forEach(opt => {
        opt.classList.toggle('selected', opt.dataset.method === method);
    });
    el('modalEmailExtra').hidden = method !== 'email';
    const sendBtn = el('modalSend').querySelector('span');
    sendBtn.textContent = method === 'download' ? 'Download' : 'Send email';
}

function modalReset() {
    document.querySelector('input[name="delivery"][value="download"]').checked = true;
    modalSetMethod('download');
    el('emailTo').value = '';
}

function currentMethod() {
    return document.querySelector('input[name="delivery"]:checked').value;
}

function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('pub-theme', theme);
    const button = el('themeToggle');
    const dark = theme === 'dark';
    button.innerHTML = `<i class="fas ${dark ? 'fa-sun' : 'fa-moon'}"></i>`;
    button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
    button.setAttribute('title', dark ? 'Switch to light mode' : 'Switch to dark mode');
}

/* ---------- quick ranges ---------- */
const QUICK_RANGES = [
    { key: '1h',   label: 'Last 1h'  },
    { key: '24h',  label: 'Last 24h' },
    { key: '7d',   label: 'Last 7d'  },
    { key: '30d',  label: 'Last 30d' },
    { key: 'all',  label: 'All available' },
];

function buildQuickRangeBar() {
    let bar = el('quickRangeBar');
    if (bar) return bar;
    const fromDateInput = el('fromDate');
    if (!fromDateInput || !fromDateInput.parentElement) return null;

    bar = document.createElement('div');
    bar.id = 'quickRangeBar';
    bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px 0;';
    bar.innerHTML = QUICK_RANGES.map(r =>
        `<button type="button" data-range="${r.key}" style="
            padding:6px 12px;border:1px solid #cbd5e1;border-radius:999px;
            background:#f8fafc;color:#334155;font-size:12px;font-weight:500;
            cursor:pointer;font-family:inherit;transition:background .15s;
        ">${r.label}</button>`
    ).join('');

    const fieldRow = fromDateInput.closest('.modal-field-row') || fromDateInput.parentElement;
    fieldRow.parentElement.insertBefore(bar, fieldRow);

    bar.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => applyQuickRange(btn.dataset.range));
    });
    return bar;
}

function applyQuickRange(key) {
    const now = new Date();
    let from;
    switch (key) {
        case '1h':  from = new Date(now.getTime() - 1  * 60 * 60 * 1000); break;
        case '24h': from = new Date(now.getTime() - 24 * 60 * 60 * 1000); break;
        case '7d':  from = new Date(now.getTime() - 7  * 24 * 60 * 60 * 1000); break;
        case '30d': from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000); break;
        case 'all': from = new Date('2020-01-01T00:00:00'); break;
        default: return;
    }
    el('fromDate').value = localInputValue(from);
    el('toDate').value   = localInputValue(now);

    const bar = el('quickRangeBar');
    if (bar) {
        bar.querySelectorAll('button').forEach(b => {
            const active = b.dataset.range === key;
            b.style.background  = active ? '#0f766e' : '#f8fafc';
            b.style.borderColor = active ? '#0f766e' : '#cbd5e1';
            b.style.color       = active ? '#fff'    : '#334155';
        });
    }
}

function openModal(preselect, initialMethod) {
    const now = new Date();
    const defaultFrom = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    el('fromDate').value = localInputValue(defaultFrom);
    el('toDate').value   = localInputValue(now);

    renderDeviceOptions(preselect || 'all');
    modalReset();

    buildQuickRangeBar();
    applyQuickRange('30d');

    if (initialMethod && initialMethod !== 'download') {
        document.querySelector(`input[name="delivery"][value="${initialMethod}"]`).checked = true;
        modalSetMethod(initialMethod);
    }

    modalReturnFocus = document.activeElement;
    el('exportModal').hidden = false;
    document.body.style.overflow = 'hidden';
    el('modalClose').focus();
}

function closeModal() {
    el('exportModal').hidden = true;
    document.body.style.overflow = '';
    if (modalReturnFocus && typeof modalReturnFocus.focus === 'function') modalReturnFocus.focus();
    modalReturnFocus = null;
}

/* ---------- export submit ---------- */
async function submitExport() {
    const btn = el('modalSend');
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';

    try {
        const method = currentMethod();
        const filters = exportParams();

        const payload = {
            from:    filters.from,
            to:      filters.to,
            devices: filters.devices,
            method,
        };

        if (method === 'email') {
            const address = el('emailTo').value.trim();
            if (!address) throw new Error('Enter a recipient email address');
            const content = emailContent('report', filters);
            payload.email   = address;
            payload.subject = content.subject;
            payload.body    = content.body;
        }

        toast('Preparing export…', '');
        const resp = await fetch(`${API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);

        if (method === 'email') {
            toast(`Emailed to ${body.to} (${body.readings} readings)`, 'success');
        } else {
            const bytes = Uint8Array.from(atob(body.content_b64), c => c.charCodeAt(0));
            const blob  = new Blob([bytes], { type: body.content_type });
            triggerDownload(blob, body.filename);
            toast(`Downloaded ${body.filename} (${body.readings} readings)`, 'success');
        }
        closeModal();
    } catch (err) {
        console.error(err);
        toast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

/* ---------- BG Thresholds modal ---------- */
async function openBgModal(device) {
    bgModalDevice = device;

    // Get Station ID
    const station_id = bgModalDevice.split("-")[0];

    // Initialize with default fallback values
    let t = bgThresholds[device] || bgDefaults || {
        // avg_from: 31, avg_to: 32.9, bad_above: 33,
        warning: 32, critical: 33
    };

    // Try to retrieve blackglobe thresholds from WT backend if available
    try {
        const response = await fetch(`/api/${station_id}/thresholds`);
        
        if (response.ok) {
            const data = await response.json();
            
            // Map the API response to the modal variables
            // Calculates 'avg_to' as 'wbgt_tier3 - 0.1' to match your default logic
            // t = {
            //     avg_from: data.wbgt_tier2 || t.avg_from,
            //     avg_to: data.wbgt_tier3 ? data.wbgt_tier3 - 0.1 : t.avg_to,
            //     bad_above: data.wbgt_tier3 || t.bad_above
            // };

            t = {
                warning: data.wbgt_tier2 || t.warning,
                critical: data.wbgt_tier3 || t.critical
            }

        } else {
            console.warn(`No threshold data found for ${station_id}, using defaults.`);
        }
    } catch (error) {
        console.error("Failed to fetch thresholds, using defaults:", error);
    }

    // el('bgAvgFrom').value   = t.avg_from;
    // el('bgAvgTo').value     = t.avg_to;
    // el('bgBadAbove').value  = t.bad_above;
    el('bgWarning').value = t.warning;
    el('bgCritical').value = t.critical;
    el('bgError').hidden    = true;
    el('bgError').textContent = '';

    const label = (lastStatus.find(s => s.device === device)?.label) || device;
    el('bgModalSubtitle').textContent = `Define WBGT threshold ranges for ${label}.`;

    validateBgInputs();

    bgModalReturnFocus = document.activeElement;
    el('bgModal').hidden = false;
    document.body.style.overflow = 'hidden';
    el('bgModalClose').focus();
}

function closeBgModal() {
    el('bgModal').hidden = true;
    document.body.style.overflow = '';
    if (bgModalReturnFocus && typeof bgModalReturnFocus.focus === 'function') {
        bgModalReturnFocus.focus();
    }
    bgModalReturnFocus = null;
    bgModalDevice = null;
}

function readBgInputs() {
    return {
        warning: parseFloat(el('bgWarning').value),
        critical: parseFloat(el('bgCritical').value),
    };
}

function validateBgInputs() {
    const v = readBgInputs();
    const errEl = el('bgError');
    const saveBtn = el('bgModalSave');
    let err = '';

    // Check if either value is empty or not a number
    if (isNaN(v.warning) || isNaN(v.critical)) {
        err = 'All values are required.';
    } else if (v.warning >= v.critical) {
        // Ensure Warning is lower than Critical
        err = 'Critical threshold must higher than Warning threshold.';
    }

    if (err) {
        errEl.textContent = err;
        errEl.hidden = false;
        saveBtn.disabled = true;
        return false;
    }
    errEl.hidden = true;
    saveBtn.disabled = false;
    return true;
}

async function saveBgThresholds() {
    if (!validateBgInputs()) return;
    if (!bgModalDevice) return;

    const btn = el('bgModalSave');
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';

    try {
        const resp = await fetch(`${API_BASE}/bg-thresholds/${encodeURIComponent(bgModalDevice)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(readBgInputs()),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);

        bgThresholds[bgModalDevice] = body.thresholds;
        toast(`Saved thresholds for ${bgModalDevice.split('-')[0]}`, 'success');
        closeBgModal();
        renderCards();
    } catch (err) {
        el('bgError').textContent = err.message;
        el('bgError').hidden = false;
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

async function resetBgThresholds() {
    if (!bgModalDevice) return;
    if (!confirm('Reset WBGT thresholds for this device to defaults?')) return;

    const btn = el('bgResetBtn');
    const original = btn.innerHTML;
    btn.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/bg-thresholds/${encodeURIComponent(bgModalDevice)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reset: true }),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);

        bgThresholds[bgModalDevice] = body.thresholds;

        const t = body.thresholds;
        el('bgWarning').value = t.warning;
        el('bgCritical').value = t.critical;

        validateBgInputs();

        toast('Reset to defaults', 'success');
        renderCards();
    } catch (err) {
        el('bgError').textContent = err.message;
        el('bgError').hidden = false;
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

/* ---------- init ---------- */
async function init() {
    applyTheme(document.documentElement.dataset.theme || 'light');
    el('themeToggle').addEventListener('click', () => {
        applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });

    el('downloadAllBtn').addEventListener('click', () => openModal('all', 'download'));
    el('logoutBtn').addEventListener('click', logout);
    el('loginForm').addEventListener('submit', login);

    document.querySelectorAll('.modal-option').forEach(opt => {
        opt.addEventListener('click', () => {
            document.querySelector(`input[name="delivery"][value="${opt.dataset.method}"]`).checked = true;
            modalSetMethod(opt.dataset.method);
        });
    });
    el('selectAllDevices').addEventListener('click', () => {
        document.querySelectorAll('#deviceOptions input').forEach(input => { input.checked = true; });
    });
    el('modalClose').addEventListener('click', closeModal);
    el('modalCancel').addEventListener('click', closeModal);
    el('modalSend').addEventListener('click', submitExport);
    el('exportModal').addEventListener('click', e => {
        if (e.target === el('exportModal')) closeModal();
    });

    el('bgWarning').addEventListener('input', validateBgInputs);
    el('bgCritical').addEventListener('input', validateBgInputs);
    
    el('bgModalClose').addEventListener('click', closeBgModal);
    el('bgModalCancel').addEventListener('click', closeBgModal);
    el('bgModalSave').addEventListener('click', saveBgThresholds);
    el('bgResetBtn').addEventListener('click', resetBgThresholds);
    el('bgModal').addEventListener('click', e => {
        if (e.target === el('bgModal')) closeBgModal();
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            if (!el('bgModal').hidden) { closeBgModal(); return; }
            if (!el('exportModal').hidden) { closeModal(); return; }
        }
    });

    try {
        const r = await fetch(`${API_BASE}/bg-thresholds`, { cache: 'no-store' });
        if (r.ok) {
            const body = await r.json();
            bgDefaults = body.defaults || null;
            if (body.thresholds) bgThresholds = body.thresholds;
        }
    } catch (_) { /* non-fatal */ }

    try {
        const resp = await fetch(`${API_BASE}/auth/me`, { cache: 'no-store' });
        if (!resp.ok) throw new Error('not signed in');
        setCurrentUser(await resp.json());
        refresh();
    } catch (_) {
        showLogin();
    }
    setInterval(refresh, REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);