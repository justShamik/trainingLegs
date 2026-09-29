/* Chart.js Visualization Helpers for Dashboard Trends */

function renderWeeklyVolumeChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Weekly Volume (km)',
                data: data.volume_km,
                backgroundColor: '#ff5500',
                borderColor: '#e04b00',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    grid: { color: '#2a2f38' },
                    ticks: { color: '#9aa0ac' }
                },
                y: {
                    grid: { color: '#2a2f38' },
                    ticks: { color: '#9aa0ac' },
                    title: { display: true, text: 'Kilometers (km)', color: '#9aa0ac' }
                }
            },
            plugins: {
                legend: { labels: { color: '#f0f2f5' } }
            }
        }
    });
}

function renderSleepTrendChart(canvasId, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'Sleep Duration (hrs)',
                    data: data.sleep_hours,
                    borderColor: '#00e676',
                    backgroundColor: 'rgba(0, 230, 118, 0.1)',
                    yAxisID: 'y',
                    tension: 0.3
                },
                {
                    label: 'Sleep Score',
                    data: data.sleep_score,
                    borderColor: '#ffab00',
                    backgroundColor: 'transparent',
                    yAxisID: 'y1',
                    borderDash: [5, 5],
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: '#2a2f38' }, ticks: { color: '#9aa0ac' } },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: '#2a2f38' },
                    ticks: { color: '#9aa0ac' },
                    title: { display: true, text: 'Hours', color: '#9aa0ac' }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#ffab00' },
                    title: { display: true, text: 'Score (0-100)', color: '#ffab00' }
                }
            },
            plugins: { legend: { labels: { color: '#f0f2f5' } } }
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
                    borderColor: '#ff5500',
                    backgroundColor: 'rgba(255, 85, 0, 0.1)',
                    yAxisID: 'y',
                    tension: 0.3
                },
                {
                    label: 'Resting HR (bpm)',
                    data: data.resting_hr,
                    borderColor: '#626875',
                    borderDash: [4, 4],
                    yAxisID: 'y1',
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: '#2a2f38' }, ticks: { color: '#9aa0ac' } },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: '#2a2f38' },
                    ticks: { color: '#9aa0ac' },
                    title: { display: true, text: 'HRV Index', color: '#9aa0ac' }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#9aa0ac' },
                    title: { display: true, text: 'BPM', color: '#9aa0ac' }
                }
            },
            plugins: { legend: { labels: { color: '#f0f2f5' } } }
        }
    });
}
