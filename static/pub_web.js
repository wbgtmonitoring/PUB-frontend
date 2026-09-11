'use strict';

const REFRESH_MS = 60_000;
const API_BASE = '/api';
let lastStatus = [];          // array of {device, online, last_seen, latest}
let lastFetchAt = null;

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

/* ---------- render ---------- */
function readingBlock(iconClass, iconFa, label, value, unit, dim) {
    return `
        <div class="reading${dim ? ' dim' : ''}">
            <div class="reading-icon ${iconClass}"><i class="fas ${iconFa}"></i></div>
            <div class="reading-body">
                <span class="reading-label">${label}</span>
                <span class="reading-value">${value}<small>${unit}</small></span>
            </div>
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

    // Sort: online first, then offline, then never-seen
    const sorted = [...lastStatus].sort((a, b) => {
        if (a.online !== b.online) return a.online ? -1 : 1;
        if (!!a.last_seen !== !!b.last_seen) return a.last_seen ? -1 : 1;
        return a.device.localeCompare(b.device);
    });

    grid.innerHTML = sorted.map(entry => {
        const { device, online, last_seen, latest } = entry;

        let statusClass, statusText;
        if (online) {
            statusClass = 'online';  statusText = 'Online';
        } else if (last_seen) {
            statusClass = 'offline'; statusText = 'Offline';
        } else {
            statusClass = 'unknown'; statusText = 'Never seen';
        }

        const hasData = !!latest;
        const batt = hasData ? Number(latest.battery_voltage ?? 0).toFixed(2) : '--';
        const felt = hasData ? Number(latest.felt_temp ?? 0).toFixed(1)       : '--';
        const surr = hasData ? Number(latest.surround_temp ?? 0).toFixed(1)   : '--';
        const hum  = hasData ? Number(latest.humidity ?? 0).toFixed(1)        : '--';
        const wbgt = hasData ? Number(latest.wbgt ?? 0).toFixed(2)            : '--';
        const tsSGT = last_seen ? fmtSGT(last_seen) : '--';
        const lastSeen = ageText(last_seen);
        const dim = !hasData;

        return `
        <div class="card ${statusClass}">
            <div class="card-header">
                <div class="card-title">
                    <h2>${esc(device)}</h2>
                    <span class="last-seen">${
                        hasData ? `Updated ${lastSeen}` : 'No data received yet'
                    }</span>
                </div>
                <span class="status-badge ${statusClass}">
                    <i class="fas fa-circle"></i> ${statusText}
                </span>
            </div>

            <div class="readings">
                ${readingBlock('icon-battery',  'fa-bolt',             'Battery',  batt, ' V', dim)}
                ${readingBlock('icon-felt',     'fa-thermometer-half', 'BG Temp',     felt, ' °C', dim)}
                ${readingBlock('icon-surround', 'fa-thermometer-full', 'Air Temp', surr, ' °C', dim)}
                ${readingBlock('icon-humidity', 'fa-tint',             'Humidity', hum,  ' %', dim)}
                ${readingBlock('icon-wbgt',     'fa-temperature-high', 'WBGT',     wbgt, ' °C', dim)}
            </div>

            <div class="card-footer">
                <div class="card-stats">
                    <span>Last update</span>
                    <span><strong>${tsSGT}</strong></span>
                </div>
                <button class="btn-download" data-device="${esc(device)}" ${
                    hasData ? '' : 'disabled'
                }>
                    <i class="fas fa-download"></i> CSV
                </button>
            </div>
        </div>`;
    }).join('');

    grid.querySelectorAll('.btn-download').forEach(btn => {
        if (btn.disabled) return;
        btn.addEventListener('click', () => downloadDeviceCSV(btn.dataset.device, btn));
    });
}

/* ---------- downloads ---------- */
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

async function downloadDeviceCSV(device, btn) {
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';

    try {
        const resp = await fetch(
            `${API_BASE}/readings?minutes=120&device=${encodeURIComponent(device)}`,
            { cache: 'no-store' }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const body = await resp.json();
        const rows = (body.readings || []).sort((a, b) => a.ts.localeCompare(b.ts));

        if (!rows.length) {
            toast('No data available for this device', 'error');
            return;
        }

        const csv = buildCSV(rows);
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
        triggerDownload(blob, `pub_${device}_${stamp()}.csv`);
        toast(`Downloaded ${rows.length} readings for ${device}`, 'success');
    } catch (err) {
        console.error(err);
        toast('Download failed: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

async function downloadAllZip() {
    const btn = el('downloadAllBtn');
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Building...';

    try {
        const resp = await fetch(`${API_BASE}/readings?minutes=120`, { cache: 'no-store' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const body = await resp.json();
        const rows = body.readings || [];

        if (!rows.length) {
            toast('No data available', 'error');
            return;
        }

        const byDevice = {};
        for (const r of rows) {
            (byDevice[r.device] = byDevice[r.device] || []).push(r);
        }

        const zip = new JSZip();
        for (const [device, list] of Object.entries(byDevice)) {
            list.sort((a, b) => a.ts.localeCompare(b.ts));
            zip.file(`pub_${device}_${stamp()}.csv`, buildCSV(list));
        }

        const allSorted = [...rows].sort((a, b) => a.ts.localeCompare(b.ts));
        zip.file(`pub_ALL_${stamp()}.csv`, buildCSV(allSorted));

        const blob = await zip.generateAsync({ type: 'blob' });
        triggerDownload(blob, `pub_all_devices_${stamp()}.zip`);
        toast(`Downloaded ${Object.keys(byDevice).length} device file(s)`, 'success');
    } catch (err) {
        console.error(err);
        toast('Download failed: ' + err.message, 'error');
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
    el('downloadAllBtn').addEventListener('click', downloadAllZip);

    refresh();
    setInterval(refresh, REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', init);