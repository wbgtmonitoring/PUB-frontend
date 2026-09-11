'use strict';

const REFRESH_MS = 60_000;
const API_BASE = '/api';
let lastStatus = [];
let lastFetchAt = null;
let openMenuDevice = null;

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

function ageText(iso) {
    if (!iso) return 'never';
    const diff = Date.now() - new Date(iso).getTime();
    if (isNaN(diff)) return '--';
    const s = Math.floor(diff / 1000);
    if (s < 0) return 'just now';
    if (s < 60) return s + 's ago';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm ago';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ago';
    const d = Math.floor(h / 24);
    return d + 'd ago';
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

/* ---------- data ---------- */
async function fetchStatus() {
    const resp = await fetch(`${API_BASE}/devices/status`, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    return body.devices || [];
}

async function refresh() {
    try {
        lastStatus = await fetchStatus();
        lastFetchAt = new Date();

        el('lastCheck').textContent = fmtSGT(lastFetchAt.toISOString());
        const online = lastStatus.filter(d => d.online).length;
        const total = lastStatus.length;
        el('liveText').textContent = `${online} of ${total} online`;
        el('liveDot').className = 'dot ' + (online > 0 ? 'online' : 'offline');

        renderCards();
    } catch (err) {
        console.error(err);
        el('liveText').textContent = 'Connection error';
        el('liveDot').className = 'dot offline';
        toast('Failed to reach server', 'error');
    }
}

/* ---------- render cards ---------- */
function statBlock(label, value, unit, dim) {
    return `
        <div class="stat${dim ? ' dim' : ''}">
            <span class="stat-label">${label}</span>
            <span class="stat-value">${value}<small>${unit}</small></span>
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
        const { device, online, last_seen, latest } = entry;

        let statusClass, statusText;
        if (online) { statusClass = 'online'; statusText = 'Online'; }
        else if (last_seen) { statusClass = 'offline'; statusText = 'Offline'; }
        else { statusClass = 'unknown'; statusText = 'Never seen'; }

        const hasData = !!latest;
        const batt = hasData ? Number(latest.battery_voltage ?? 0).toFixed(2) : '--';
        const felt = hasData ? Number(latest.felt_temp ?? 0).toFixed(1)       : '--';
        const surr = hasData ? Number(latest.surround_temp ?? 0).toFixed(1)   : '--';
        const hum  = hasData ? Number(latest.humidity ?? 0).toFixed(1)        : '--';
        const wbgt = hasData ? Number(latest.wbgt ?? 0).toFixed(2)            : '--';
        const tsSGT = last_seen ? fmtSGT(last_seen) : '--';
        const dim = !hasData;

        return `
        <div class="card ${statusClass}" data-device="${esc(device)}">
            <div class="card-header">
                <div class="card-title">
                    <h2>${esc(device)}</h2>
                    <span class="batt-inline${dim ? ' dim' : ''}">v: ${batt} V</span>
                </div>
                <div class="card-header-right">
                    <span class="status-badge ${statusClass}">
                        <i class="fas fa-circle"></i> ${statusText}
                    </span>
                    <div class="card-menu-wrap">
                        <button class="card-menu-btn" type="button" data-device="${esc(device)}" aria-label="Actions">
                            <i class="fas fa-chevron-down"></i>
                        </button>
                        <div class="card-menu" data-menu-device="${esc(device)}" hidden>
                            <button type="button" data-action="download">
                                <i class="fas fa-download"></i> Download
                            </button>
                            <button type="button" data-action="email">
                                <i class="fas fa-envelope"></i> Send by email
                            </button>
                            <button type="button" data-action="telegram">
                                <i class="fab fa-telegram"></i> Send via Telegram
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="stats-grid">
                ${statBlock('BG Temp',  felt, ' °C', dim)}
                ${statBlock('Humidity', hum,  ' %',  dim)}
                ${statBlock('Air Temp', surr, ' °C', dim)}
                ${statBlock('WBGT',     wbgt, ' °C', dim)}
            </div>

            <div class="card-footer-simple">
                <span class="footer-label">Last update</span>
                <span class="footer-value">${tsSGT}</span>
            </div>
        </div>`;
    }).join('');

    // Bind dropdown menu buttons
    grid.querySelectorAll('.card-menu-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            toggleMenu(btn.dataset.device);
        });
    });

    // Bind dropdown actions
    grid.querySelectorAll('.card-menu button').forEach(b => {
        b.addEventListener('click', e => {
            e.stopPropagation();
            const device = b.closest('.card-menu').dataset.menuDevice;
            const action = b.dataset.action;
            closeAllMenus();
            if (action === 'download') openModal(device, 'download');
            else if (action === 'email') openModal(device, 'email');
            else if (action === 'telegram') openModal(device, 'telegram');
        });
    });
}

/* ---------- dropdown menu control ---------- */
function closeAllMenus() {
    document.querySelectorAll('.card-menu').forEach(m => { m.hidden = true; });
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
    }
}

document.addEventListener('click', () => closeAllMenus());

/* ---------- CSV / download ---------- */
function csvEscape(v) {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCSV(rows) {
    const headers = [
        'Timestamp (SGT)', 'Timestamp (UTC)', 'Device',
        'Battery (V)', 'BG Temp (C)', 'Air Temp (C)', 'Humidity (%)', 'WBGT (C)'
    ];
    const lines = [headers.join(',')];
    for (const r of rows) {
        lines.push([
            csvEscape(fmtSGT(r.ts)),
            csvEscape(r.ts),
            csvEscape(r.device),
            csvEscape(Number(r.battery_voltage ?? 0).toFixed(2)),
            csvEscape(Number(r.felt_temp ?? 0).toFixed(2)),
            csvEscape(Number(r.surround_temp ?? 0).toFixed(2)),
            csvEscape(Number(r.humidity ?? 0).toFixed(2)),
            csvEscape(Number(r.wbgt ?? 0).toFixed(2)),
        ].join(','));
    }
    return lines.join('\n');
}

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

function stamp() {
    return new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
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
        ? lastStatus.map(item => item.device)
        : ['TG452-01', 'TG452-02', 'TG452-03', 'TG452-04', 'TG452-05'];

    const isAllPreselected = !preselect || preselect === 'all';
    el('deviceOptions').innerHTML = devices.map(device => {
        const checked = isAllPreselected || device === preselect;
        return `
        <label class="device-choice">
            <input type="checkbox" value="${esc(device)}" ${checked ? 'checked' : ''}>
            <span>${esc(device)}</span>
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

async function fetchExportRows(filters) {
    const params = new URLSearchParams({ from: filters.from, to: filters.to });
    const resp = await fetch(`${API_BASE}/readings?${params}`, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    const allowed = new Set(filters.devices);
    return (body.readings || [])
        .filter(row => allowed.has(row.device))
        .sort((a, b) => a.ts.localeCompare(b.ts));
}

async function buildExportBlob(rows) {
    const byDevice = {};
    rows.forEach(row => (byDevice[row.device] = byDevice[row.device] || []).push(row));
    const devices = Object.keys(byDevice);
    if (devices.length === 1) {
        return { blob: new Blob([buildCSV(rows)], { type: 'text/csv;charset=utf-8' }), extension: 'csv', devices };
    }
    const zip = new JSZip();
    devices.forEach(device => zip.file(`pub_${device}_${stamp()}.csv`, buildCSV(byDevice[device])));
    zip.file(`pub_ALL_${stamp()}.csv`, buildCSV(rows));
    return { blob: await zip.generateAsync({ type: 'blob' }), extension: 'zip', devices };
}

function emailContent(template, filters, rows) {
    const range = `${el('fromDate').value.replace('T', ' ')} to ${el('toDate').value.replace('T', ' ')}`;
    const devices = filters.devices.join(', ');
    const subjects = { report: `PUB device data report - ${range}`, blank: '' };
    const bodies = {
        report: `Hello,\n\nAttached is the PUB data report for ${range}.\nIncluded devices: ${devices}\nTotal readings: ${rows.length}\n\nRegards`,
        blank: ''
    };
    return { subject: subjects[template], body: bodies[template] };
}

function telegramMessage(template, filters, rows) {
    const range = `${el('fromDate').value.replace('T', ' ')} to ${el('toDate').value.replace('T', ' ')}`;
    const devices = filters.devices.join(', ');
    if (template === 'blank') return '';
    if (template === 'short') {
        return `PUB export ready\nRange: ${range}\nDevices: ${devices}\nReadings: ${rows.length}`;
    }
    return `PUB data report\nRange: ${range}\nDevices: ${devices}\nTotal readings: ${rows.length}\n\nCSV/ZIP attached.`;
}

/* ---------- modal ---------- */
function modalSetMethod(method) {
    document.querySelectorAll('.modal-option').forEach(opt => {
        opt.classList.toggle('selected', opt.dataset.method === method);
    });
    el('modalEmailExtra').hidden    = method !== 'email';
    el('modalTelegramExtra').hidden = method !== 'telegram';
    const sendBtn = el('modalSend').querySelector('span');
    sendBtn.textContent = method === 'download' ? 'Download'
                        : method === 'email'    ? 'Send email'
                        :                          'Send Telegram';
}

function modalReset() {
    document.querySelector('input[name="delivery"][value="download"]').checked = true;
    modalSetMethod('download');
    el('emailTo').value = '';
    el('telegramChatId').value = '';
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

function openModal(preselect, initialMethod) {
    const now = new Date();
    el('fromDate').value = localInputValue(new Date(now.getTime() - 2 * 60 * 60 * 1000));
    el('toDate').value = localInputValue(now);

    renderDeviceOptions(preselect || 'all');
    modalReset();

    if (initialMethod && initialMethod !== 'download') {
        document.querySelector(`input[name="delivery"][value="${initialMethod}"]`).checked = true;
        modalSetMethod(initialMethod);
    }

    el('exportModal').hidden = false;
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    el('exportModal').hidden = true;
    document.body.style.overflow = '';
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
        const rows = await fetchExportRows(filters);
        if (!rows.length) throw new Error('No readings match these filters');

        if (method === 'download') {
            const result = await buildExportBlob(rows);
            const filename = `pub_export_${stamp()}.${result.extension}`;
            triggerDownload(result.blob, filename);
            toast(`Downloaded ${filename}`, 'success');
            closeModal();
            return;
        }

        const payload = {
            from:    filters.from,
            to:      filters.to,
            devices: filters.devices,
            method,
        };

        if (method === 'email') {
            const address = el('emailTo').value.trim();
            if (!address) throw new Error('Enter a recipient email address');
            const content = emailContent('report', filters, rows);
            payload.email   = address;
            payload.subject = content.subject;
            payload.body    = content.body;
        } else if (method === 'telegram') {
            const chatId = el('telegramChatId').value.trim();
            if (!chatId) throw new Error('Enter the Telegram chat ID');
            payload.telegram_chat_id = chatId;
            payload.telegram_message = telegramMessage(el('telegramTemplate').value, filters, rows);
        }

        const resp = await fetch(`${API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);

        const target = method === 'email' ? body.to : `chat ${body.chat_id}`;
        toast(`Sent to ${target} (${body.readings} readings)`, 'success');
        closeModal();
    } catch (err) {
        console.error(err);
        toast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

/* ---------- init ---------- */
function init() {
    el('refreshBtn').addEventListener('click', () => {
        el('refreshBtn').disabled = true;
        refresh().finally(() => { el('refreshBtn').disabled = false; });
    });

    applyTheme(document.documentElement.dataset.theme || 'light');
    el('themeToggle').addEventListener('click', () => {
        applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });

    el('downloadAllBtn').addEventListener('click', () => openModal('all', 'download'));

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
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && !el('exportModal').hidden) closeModal();
    });

    refresh();
    setInterval(refresh, REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);