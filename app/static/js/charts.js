/* Second Brain - Chart.js Helpers */

(function() {
    'use strict';

    function getChartColors(theme) {
        var isDark = theme === 'dark' ||
            document.documentElement.getAttribute('data-bs-theme') === 'dark';

        return {
            text: isDark ? '#dee2e6' : '#212529',
            grid: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
            bg: isDark ? '#1a1d21' : '#ffffff',
            palette: [
                '#0d6efd', '#198754', '#ffc107', '#dc3545',
                '#0dcaf0', '#6f42c1', '#fd7e14', '#20c997',
                '#d63384', '#6c757d'
            ]
        };
    }

    function commonOptions(colors) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: colors.text }
                }
            },
            scales: {
                x: {
                    ticks: { color: colors.text },
                    grid: { color: colors.grid }
                },
                y: {
                    ticks: { color: colors.text },
                    grid: { color: colors.grid }
                }
            }
        };
    }

    window.createBarChart = function(canvasId, labels, datasets, extra) {
        var ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        var colors = getChartColors();
        var opts = commonOptions(colors);
        if (extra) Object.assign(opts, extra);

        datasets.forEach(function(ds, i) {
            if (!ds.backgroundColor) {
                ds.backgroundColor = colors.palette[i % colors.palette.length];
            }
        });

        return new Chart(ctx, {
            type: 'bar',
            data: { labels: labels, datasets: datasets },
            options: opts
        });
    };

    window.createLineChart = function(canvasId, labels, datasets, extra) {
        var ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        var colors = getChartColors();
        var opts = commonOptions(colors);
        opts.elements = { line: { tension: 0.3 } };
        if (extra) Object.assign(opts, extra);

        datasets.forEach(function(ds, i) {
            if (!ds.borderColor) {
                ds.borderColor = colors.palette[i % colors.palette.length];
                ds.backgroundColor = colors.palette[i % colors.palette.length] + '20';
            }
        });

        return new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: opts
        });
    };

    window.createDoughnutChart = function(canvasId, labels, data, extra) {
        var ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        var colors = getChartColors();
        var opts = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: colors.text }
                }
            }
        };
        if (extra) Object.assign(opts, extra);

        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors.palette.slice(0, data.length)
                }]
            },
            options: opts
        });
    };

    // Theme change handler - destroy and recreate charts
    document.addEventListener('themeChanged', function() {
        // Charts should be recreated by the page-specific code
        // This event just notifies them
    });
})();
