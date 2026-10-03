/* Chart.js visualisation helpers for dashboard trends.
 * Palette + defaults mirror the CSS tokens in style.css (see docs/DESIGN_SYSTEM.md). */

const CoachPalette = {
    orange: '#ff5c1a',
    peach: '#ffb89a',
    apricot: '#ffd09c',
    butter: '#f5e09a',
    mint: '#9fe3c4',
    sky: '#a6d0f5',
    lavender: '#c6b6f7',
    rose: '#f7a6b7',
    grid: 'rgba(255, 255, 255, 0.05)',
    tick: '#8b8b93',
    text: '#b3b3ba',
    muted: '#5d5d66',
    // Ordered series palette for anything with N datasets
    series: ['#ffb89a', '#a6d0f5', '#9fe3c4', '#c6b6f7', '#f5e09a', '#f7a6b7', '#ffd09c'],
    alpha(hex, a) {
        const n = parseInt(hex.slice(1), 16);
        return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
    }
};
window.CoachPalette = CoachPalette;

/* Global Chart.js defaults - written defensively (test stubs expose only a partial defaults object). */
(function applyChartDefaults() {
    if (typeof Chart === 'undefined' || !Chart.defaults) return;
    const d = Chart.defaults;
    d.color = CoachPalette.text;
    d.font = Object.assign(d.font || {}, {
        family: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        size: 12
    });
    if (d.borderColor !== undefined) d.borderColor = CoachPalette.grid;
    if (d.plugins && d.plugins.legend && d.plugins.legend.labels) {
        Object.assign(d.plugins.legend.labels, { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, boxHeight: 8, padding: 16 });
    }
    if (d.plugins && d.plugins.tooltip) {
        Object.assign(d.plugins.tooltip, {
            backgroundColor: 'rgba(22, 25, 30, 0.96)', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
            titleColor: '#f5f5f7', bodyColor: '#b3b3ba', padding: 12, cornerRadius: 12,
            usePointStyle: true, boxPadding: 4
        });
    }
    if (d.elements) {
        if (d.elements.line) Object.assign(d.elements.line, { borderWidth: 2, tension: 0.35 });
        if (d.elements.point) Object.assign(d.elements.point, { radius: 0, hoverRadius: 4, hitRadius: 10 });
        if (d.elements.bar) Object.assign(d.elements.bar, { borderRadius: 6, borderSkipped: false });
    }
    if (d.animation) Object.assign(d.animation, { duration: 900, easing: 'easeOutQuart' });
})();

/* Shared axis styling: hairline grid, no axis border, quiet ticks. */
function coachAxis(extra) {
    return Object.assign({
        grid: { color: CoachPalette.grid, drawTicks: false },
        border: { display: false },
        ticks: { color: CoachPalette.tick, padding: 8, maxRotation: 0, autoSkipPadding: 12 }
    }, extra || {});
}

function coachAxisTitle(text, color) {
    return { display: true, text: text, color: color || CoachPalette.tick, font: { size: 11, weight: '500' } };
}

const coachLegend = { labels: { color: CoachPalette.text, usePointStyle: true, pointStyle: 'circle', boxWidth: 8, boxHeight: 8, padding: 16 } };

function renderWeeklyVolumeChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Weekly Volume (km)',
                data: data.volume_km,
                backgroundColor: CoachPalette.peach,
                hoverBackgroundColor: CoachPalette.orange,
                borderRadius: 8,
                borderSkipped: false,
                maxBarThickness: 28
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: coachAxis({ grid: { display: false } }),
                y: coachAxis({ beginAtZero: true, title: coachAxisTitle('Kilometers (km)') })
            },
            plugins: { legend: coachLegend }
        }
    });
}

function renderSleepStagesChart(canvasId, data) {
    // COROS gives no sleep score: show duration split into stages (nights without a stage split show total only)
    const ctx = document.getElementById(canvasId).getContext('2d');
    const noSplit = data.labels.map((_, i) =>
        data.deep_hours[i] === null && data.light_hours[i] === null && data.rem_hours[i] === null ? data.sleep_hours[i] : null);
    const ds = (label, arr, color) => ({ label: label, data: arr, backgroundColor: color, stack: 'sleep', borderRadius: 4, borderSkipped: false, maxBarThickness: 18 });
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [
                ds('Deep (hrs)', data.deep_hours, CoachPalette.lavender),
                ds('Light (hrs)', data.light_hours, CoachPalette.sky),
                ds('REM (hrs)', data.rem_hours, CoachPalette.mint),
                ds('Awake (hrs)', data.awake_hours, CoachPalette.butter),
                ds('Total, no stage split (hrs)', noSplit, CoachPalette.muted)
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: coachAxis({ stacked: true, grid: { display: false } }),
                y: coachAxis({ stacked: true, title: coachAxisTitle('Hours') })
            },
            plugins: { legend: coachLegend }
        }
    });
}

function renderSleepTrendChart(canvasId, data) {
    if (data.has_score === false) {
        return renderSleepStagesChart(canvasId, data);
    }
    const ctx = document.getElementById(canvasId).getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'Sleep Duration (hrs)',
                    data: data.sleep_hours,
                    borderColor: CoachPalette.lavender,
                    backgroundColor: CoachPalette.alpha(CoachPalette.lavender, 0.12),
                    fill: true,
                    yAxisID: 'y',
                    tension: 0.35,
                    pointRadius: 0
                },
                {
                    label: 'Sleep Score',
                    data: data.sleep_score,
                    borderColor: CoachPalette.butter,
                    backgroundColor: 'transparent',
                    yAxisID: 'y1',
                    borderDash: [4, 4],
                    tension: 0.35,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: coachAxis({ grid: { display: false } }),
                y: coachAxis({ type: 'linear', position: 'left', title: coachAxisTitle('Hours') }),
                y1: coachAxis({
                    type: 'linear', position: 'right', grid: { drawOnChartArea: false },
                    ticks: { color: CoachPalette.butter, padding: 8 },
                    title: coachAxisTitle('Score (0-100)', CoachPalette.butter)
                })
            },
            plugins: { legend: coachLegend }
        }
    });
}

function renderPhysioTrendChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'HRV Score',
                    data: data.hrv,
                    borderColor: CoachPalette.mint,
                    backgroundColor: CoachPalette.alpha(CoachPalette.mint, 0.12),
                    fill: true,
                    yAxisID: 'y',
                    tension: 0.35,
                    pointRadius: 0
                },
                {
                    label: 'Resting HR (bpm)',
                    data: data.resting_hr,
                    borderColor: CoachPalette.rose,
                    borderDash: [4, 4],
                    yAxisID: 'y1',
                    tension: 0.35,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: coachAxis({ grid: { display: false } }),
                y: coachAxis({ type: 'linear', position: 'left', title: coachAxisTitle('HRV Index') }),
                y1: coachAxis({
                    type: 'linear', position: 'right', grid: { drawOnChartArea: false },
                    title: coachAxisTitle('BPM')
                })
            },
            plugins: { legend: coachLegend }
        }
    });
}
