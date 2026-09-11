let allData = [];
let filteredData = [];
let currentPage = 1;
let pageSize = 25;
let currentSort = { column: 0, ascending: false };
let chart = null;
let currentPeriod = 'hourly';
let currentParam = 'all';
let availableDevices = [];
let selectedDevice = 'all';
const columns = ['timestamp', 'device', 'batteryVoltage', 'feltTemp', 'surroundTemp', 'humidity'];

const BUCKET_MS = {
    hourly:   60 * 1000,
    daily:    15 * 60 * 1000,
    weekly:   30 * 60 * 1000,
    monthly:  60 * 60 * 1000,
    sixmonth: 60 * 60 * 1000,
    yearly:   60 * 60 * 1000,
};

// Format an ISO-UTC timestamp as Singapore local time.
// e.g. "2026-09-11T04:20:52.128035Z" -> "11/09/2026, 12:20:52 SGT"
function formatSGT(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Singapore',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    }).formatToParts(d);
    const get = t => parts.find(p => p.type === t)?.value || '';
    return `${get('day')}/${get('month')}/${get('year')}, ${get('hour')}:${get('minute')}:${get('second')} SGT`;
}

// Shorter version for chart labels: "11/09 12:20"
function formatSGTShort(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Singapore',
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
        hour12: false,
    }).formatToParts(d);
    const get = t => parts.find(p => p.type === t)?.value || '';
    return `${get('day')}/${get('month')} ${get('hour')}:${get('minute')}`;
}

function mapApiRecord(r) {
    return {
        timestamp: r.ts,
        device: r.device,
        batteryVoltage: Number(r.battery_voltage) || 0,
        feltTemp: Number(r.felt_temp) || 0,
        surroundTemp: Number(r.surround_temp) || 0,
        humidity: Number(r.humidity) || 0,
    };
}

function setConnectionStatus(online, message) {
    const status = document.getElementById('connectionStatus');
    status.classList.toggle('online', online);
    status.innerHTML = `<i class="fas fa-circle"></i> ${message}`;
}

async function loadData() {
    try {
        const resp = await fetch('/api/readings?minutes=120', { cache: 'no-store' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const body = await resp.json();
        allData = (body.readings || []).map(mapApiRecord);
        availableDevices = [...new Set(allData.map(r => r.device).filter(Boolean))].sort();
        renderDeviceOptions();
        applySearch(false);
        updateLastUpdate();
        setConnectionStatus(true, allData.length ? 'Online' : 'Connected, no data');
    } catch (err) {
        console.error('loadData failed:', err);
        setConnectionStatus(false, 'Offline');
    }
}

function initializeDashboard() {
    bindControls();
    initializeChart();
    loadData();
    window.setInterval(loadData, 60000);
}

function bindControls() {
    document.getElementById('searchInput').addEventListener('input', () => applySearch());
    document.getElementById('deviceSelect').addEventListener('change', e => {
        selectedDevice = e.target.value; applySearch();
    });
    document.getElementById('pageSizeSelect').addEventListener('change', e => {
        pageSize = Number(e.target.value); currentPage = 1;
        renderTable(); updatePagination();
    });
}

function applySearch(resetPage = true) {
    const term = document.getElementById('searchInput').value.toLowerCase().trim();
    filteredData = allData.filter(row => {
        const matchesDevice = selectedDevice === 'all' || row.device === selectedDevice;
        const matchesSearch = !term || Object.values(row).some(v => String(v).toLowerCase().includes(term));
        return matchesDevice && matchesSearch;
    });
    if (resetPage) currentPage = 1;
    updateStats(); renderTable(); updatePagination(); updateChart();
}

function updateStats() {
    const fields = [
        ['batteryVoltage', 'battery', 'V', 2],
        ['feltTemp', 'felt', '°C', 1],
        ['surroundTemp', 'surround', '°C', 1],
        ['humidity', 'humidity', '%', 1],
    ];
    document.getElementById('totalRecords').textContent = filteredData.length;
    if (!filteredData.length) {
        fields.forEach(([, name]) => ['Latest', 'Max', 'Min'].forEach(t =>
            document.getElementById(`${name}${t}`).textContent = '--'));
        ['avgBattery', 'avgFelt', 'avgSurround', 'avgHumidity'].forEach(id =>
            document.getElementById(id).textContent = '--');
        return;
    }
    const latest = [...filteredData].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
    fields.forEach(([field, name, unit, decimals]) => {
        const values = filteredData.map(r => Number(r[field]));
        const fmt = v => `${v.toFixed(decimals)}${unit}`;
        document.getElementById(`${name}Latest`).textContent = fmt(latest[field]);
        document.getElementById(`${name}Max`).textContent = fmt(Math.max(...values));
        document.getElementById(`${name}Min`).textContent = fmt(Math.min(...values));
        document.getElementById(`avg${name[0].toUpperCase()}${name.slice(1)}`).textContent =
            fmt(values.reduce((s, v) => s + v, 0) / values.length);
    });
}

function renderDeviceOptions() {
    const select = document.getElementById('deviceSelect');
    select.replaceChildren(new Option('All devices', 'all'));
    availableDevices.forEach(d => select.appendChild(new Option(d, d)));
    select.value = selectedDevice;
}

function updateLastUpdate() {
    document.getElementById('lastUpdate').textContent = formatSGT(new Date().toISOString());
}

function renderTable() {
    const tbody = document.getElementById('tableBody');
    const start = (currentPage - 1) * pageSize;
    const pageData = filteredData.slice(start, start + pageSize);
    tbody.replaceChildren();
    if (!pageData.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No data matches your search.</td></tr>';
        return;
    }
    pageData.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${formatSGT(row.timestamp)}</td>
            <td><span class="status-badge active">${row.device}</span></td>
            <td>${Number(row.batteryVoltage).toFixed(2)} V</td>
            <td>${Number(row.feltTemp).toFixed(1)} °C</td>
            <td>${Number(row.surroundTemp).toFixed(1)} °C</td>
            <td>${Number(row.humidity).toFixed(1)} %</td>`;
        tbody.appendChild(tr);
    });
}

function updatePagination() {
    const pagination = document.getElementById('pagination');
    const totalPages = Math.ceil(filteredData.length / pageSize);
    pagination.replaceChildren();
    if (totalPages <= 1) return;
    const addButton = (label, page, disabled = false, active = false) => {
        const button = document.createElement('button');
        button.innerHTML = label;
        button.disabled = disabled;
        if (active) button.className = 'active';
        if (!disabled && !active) button.addEventListener('click', () => changePage(page));
        pagination.appendChild(button);
    };
    addButton('<i class="fas fa-chevron-left"></i><span>Previous</span>', currentPage - 1, currentPage === 1);
    for (let p = 1; p <= totalPages; p++)
        if (p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1)
            addButton(String(p), p, false, p === currentPage);
    addButton('<span>Next</span><i class="fas fa-chevron-right"></i>', currentPage + 1, currentPage === totalPages);
    const info = document.createElement('span');
    info.className = 'page-info';
    info.textContent = `Page ${currentPage} of ${totalPages} (${filteredData.length} records)`;
    pagination.appendChild(info);
}

function changePage(page) {
    const totalPages = Math.ceil(filteredData.length / pageSize);
    if (page < 1 || page > totalPages) return;
    currentPage = page; renderTable(); updatePagination();
}

function sortTable(columnIndex) {
    currentSort = currentSort.column === columnIndex
        ? { column: columnIndex, ascending: !currentSort.ascending }
        : { column: columnIndex, ascending: true };
    const key = columns[columnIndex];
    filteredData.sort((a, b) => {
        // Sort timestamp by actual epoch, others normally
        let x, y;
        if (key === 'timestamp') {
            x = new Date(a.timestamp).getTime();
            y = new Date(b.timestamp).getTime();
        } else {
            x = typeof a[key] === 'string' ? a[key].toLowerCase() : a[key];
            y = typeof b[key] === 'string' ? b[key].toLowerCase() : b[key];
        }
        return (x < y ? -1 : x > y ? 1 : 0) * (currentSort.ascending ? 1 : -1);
    });
    currentPage = 1;
    renderTable(); updatePagination();
    document.querySelectorAll('thead th i').forEach((icon, i) =>
        icon.className = i === columnIndex ? `fas fa-sort-${currentSort.ascending ? 'up' : 'down'}` : 'fas fa-sort');
}

function refreshData() { loadData(); }

function initializeChart() {
    chart = new Chart(document.getElementById('mainChart'), {
        type: 'line',
        data: { labels: [], datasets: [] },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: false } },
        },
    });
}

function getChartRows() {
    const bucket = BUCKET_MS[currentPeriod] || 60 * 1000;
    const groups = new Map();
    [...filteredData].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)).forEach(row => {
        const ts = new Date(row.timestamp).getTime();
        const key = Math.floor(ts / bucket) * bucket;
        const g = groups.get(key) || { count: 0, batteryVoltage: 0, feltTemp: 0, surroundTemp: 0, humidity: 0 };
        g.count += 1;
        ['batteryVoltage', 'feltTemp', 'surroundTemp', 'humidity'].forEach(f => g[f] += Number(row[f]));
        groups.set(key, g);
    });
    return [...groups.entries()].map(([key, v]) => ({
        label: formatSGTShort(new Date(key).toISOString()),
        batteryVoltage: v.batteryVoltage / v.count,
        feltTemp: v.feltTemp / v.count,
        surroundTemp: v.surroundTemp / v.count,
        humidity: v.humidity / v.count,
    }));
}

function updateChart() {
    if (!chart) return;
    const rows = getChartRows();
    const defs = {
        batteryVoltage: ['Voltage (V)', '#1976d2'],
        feltTemp: ['Felt temperature (°C)', '#f57c00'],
        surroundTemp: ['Surround temperature (°C)', '#388e3c'],
        humidity: ['Humidity (%)', '#00838f'],
    };
    const fields = currentParam === 'all' ? Object.keys(defs)
        : currentParam === 'temperature' ? ['feltTemp', 'surroundTemp']
        : [currentParam === 'voltage' ? 'batteryVoltage' : 'humidity'];

    chart.data.labels = rows.map(r => r.label);
    chart.data.datasets = fields.map(f => ({
        label: defs[f][0], data: rows.map(r => r[f]),
        borderColor: defs[f][1], backgroundColor: `${defs[f][1]}22`,
        tension: 0.3, pointRadius: rows.length > 40 ? 0 : 3, fill: false,
    }));
    chart.options.scales.y.title = {
        display: true,
        text: currentParam === 'humidity' ? 'Percent'
            : currentParam === 'voltage' ? 'Volts' : 'Value',
    };
    chart.options.scales.x = {
        ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: 12 },
        title: { display: true, text: 'Time (SGT)' },
    };
    chart.update('none');
    document.getElementById('chartTitle').textContent =
        `${currentPeriod[0].toUpperCase()}${currentPeriod.slice(1)} data overview (last 2h, SGT)`;
    document.getElementById('chartLegend').innerHTML = fields
        .map(f => `<span class="chart-legend-item"><span class="chart-legend-color" style="background:${defs[f][1]}"></span>${defs[f][0]}</span>`)
        .join('');
}

function changeChartPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll('.chart-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
    updateChart();
}
function changeChartParameter(parameter) {
    currentParam = parameter;
    document.querySelectorAll('.param-btn').forEach(b => b.classList.toggle('active', b.dataset.param === parameter));
    updateChart();
}

function downloadCSV() {
    // CSV keeps UTC (ISO) for maximum compatibility; use formatSGT(r.timestamp) if you want SGT in the file
    const headers = ['Timestamp (UTC)', 'Device', 'Battery Voltage (V)', 'Felt Temp (°C)', 'Surround Temp (°C)', 'Relative Humidity (%)'];
    const rows = filteredData.map(r => [r.timestamp, r.device, r.batteryVoltage, r.feltTemp, r.surroundTemp, r.humidity]);
    const csv = [headers, ...rows]
        .map(row => row.map(v => `"${String(v).replaceAll('"', '""')}"`).join(','))
        .join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = `pub-device-data-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
}

document.addEventListener('DOMContentLoaded', initializeDashboard);