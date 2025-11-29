// Funding Bot Dashboard JavaScript

// Configuration
const REFRESH_INTERVAL = 30000; // 30 seconds
let refreshTimer = null;
let equityChart = null;
let fundingChart = null;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard initializing...');
    initCharts();
    refreshData();
    startAutoRefresh();
});

// Start auto-refresh
function startAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(refreshData, REFRESH_INTERVAL);
}

// Refresh all data
async function refreshData() {
    console.log('Refreshing data...');
    try {
        await Promise.all([
            fetchOverview(),
            fetchPositions(),
            fetchRiskMetrics(),
            fetchFundingRates(),
            fetchPerformance(),
            fetchEquityHistory(),
            fetchConfig(),
            fetchPaperStatus()
        ]);
        updateLastUpdated();
    } catch (error) {
        console.error('Error refreshing data:', error);
    }
}

// Update last updated timestamp
function updateLastUpdated() {
    const now = new Date();
    document.getElementById('last-updated').textContent = now.toLocaleString();
}

// Fetch paper trading status
async function fetchPaperStatus() {
    try {
        const response = await fetch('/api/paper-status');
        const data = await response.json();
        
        const paperBadge = document.getElementById('paper-badge');
        if (paperBadge) {
            if (data.paper_trading) {
                paperBadge.style.display = 'inline-block';
                paperBadge.textContent = 'PAPER MODE';
                paperBadge.title = `Virtual balance: $${data.initial_balance}`;
            } else {
                paperBadge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Error fetching paper status:', error);
    }
}

// Fetch overview data
async function fetchOverview() {
    try {
        const response = await fetch('/api/overview');
        const data = await response.json();
        
        // Update metrics
        document.getElementById('total-equity').textContent = formatCurrency(data.total_equity);
        
        const totalPnl = document.getElementById('total-pnl');
        totalPnl.textContent = formatCurrency(data.total_pnl);
        totalPnl.className = 'metric-value ' + (data.total_pnl >= 0 ? 'positive' : 'negative');
        
        document.getElementById('total-pnl-pct').textContent = formatPercent(data.total_pnl_pct);
        document.getElementById('daily-apr').textContent = formatPercent(data.daily_apr);
        document.getElementById('monthly-apr').textContent = formatPercent(data.monthly_apr);
        document.getElementById('annualized-apr').textContent = formatPercent(data.annualized_apr);
        document.getElementById('open-positions').textContent = data.open_positions_count;
        document.getElementById('total-funding').textContent = formatCurrency(data.total_funding);
        document.getElementById('total-fees').textContent = formatCurrency(data.total_fees);
    } catch (error) {
        console.error('Error fetching overview:', error);
    }
}

// Fetch positions
async function fetchPositions() {
    try {
        const response = await fetch('/api/positions/open');
        const data = await response.json();
        
        const tbody = document.getElementById('positions-body');
        
        if (data.positions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="no-data">No open positions</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.positions.map(pos => `
            <tr>
                <td><strong>${pos.symbol}</strong></td>
                <td>${formatSide(pos.side)}</td>
                <td>${formatCurrency(pos.position_value)}</td>
                <td>${formatFundingRate(pos.entry_funding_rate)}</td>
                <td>${formatFundingRate(pos.current_funding_rate)}</td>
                <td class="${pos.accumulated_funding >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(pos.accumulated_funding)}
                </td>
                <td class="${pos.net_pnl >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(pos.net_pnl)}
                </td>
                <td>${formatDuration(pos.duration_hours)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error fetching positions:', error);
    }
}

// Fetch risk metrics
async function fetchRiskMetrics() {
    try {
        const response = await fetch('/api/risk-metrics');
        const data = await response.json();
        
        // Update risk level with safe handling
        const riskLevel = document.getElementById('risk-level');
        const riskLevelValue = data.risk_level || 'low';
        riskLevel.textContent = riskLevelValue.charAt(0).toUpperCase() + riskLevelValue.slice(1);
        riskLevel.className = 'metric-value risk-' + riskLevelValue;
        
        // Update metrics with NaN handling
        const marginRatio = data.margin_ratio;
        document.getElementById('margin-ratio').textContent = 
            (marginRatio !== null && marginRatio !== undefined && !isNaN(marginRatio)) 
                ? formatPercent(marginRatio * 100) 
                : '0.00%';
        
        const liqDistance = data.min_liquidation_distance;
        document.getElementById('liq-distance').textContent = 
            (liqDistance !== null && liqDistance !== undefined && !isNaN(liqDistance) && liqDistance < 100) 
                ? formatPercent(liqDistance * 100) 
                : 'N/A';
        
        const drawdown = data.current_drawdown || 0;
        document.getElementById('drawdown').textContent = formatPercent(drawdown * 100);
        
        // Update alerts
        const alertsContainer = document.getElementById('risk-alerts');
        if (data.alerts && data.alerts.length > 0) {
            alertsContainer.innerHTML = data.alerts.map(alert => `
                <div class="alert alert-${alert.level}">
                    <strong>${alert.type.replace(/_/g, ' ').toUpperCase()}:</strong> ${alert.message}
                </div>
            `).join('');
        } else {
            alertsContainer.innerHTML = '';
        }
    } catch (error) {
        console.error('Error fetching risk metrics:', error);
        // Set safe defaults on error
        document.getElementById('risk-level').textContent = 'Low';
        document.getElementById('risk-level').className = 'metric-value risk-low';
        document.getElementById('margin-ratio').textContent = '0.00%';
        document.getElementById('liq-distance').textContent = 'N/A';
        document.getElementById('drawdown').textContent = '0.00%';
    }
}

// Fetch funding rates
async function fetchFundingRates() {
    try {
        const response = await fetch('/api/funding-rates');
        const data = await response.json();
        
        const tbody = document.getElementById('funding-rates-body');
        
        if (data.funding_rates.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="no-data">No funding rates available</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.funding_rates.slice(0, 20).map(rate => `
            <tr>
                <td><strong>${rate.symbol}</strong></td>
                <td class="${rate.funding_rate >= 0 ? 'positive' : 'negative'}">
                    ${formatFundingRate(rate.funding_rate)}
                </td>
                <td class="${rate.apr >= 0 ? 'positive' : 'negative'}">
                    ${formatPercent(rate.apr)}
                </td>
                <td>${formatPrice(rate.mark_price)}</td>
                <td>${formatVolume(rate.volume_24h)}</td>
                <td>${formatTime(rate.next_funding_time)}</td>
            </tr>
        `).join('');
        
        // Update funding chart
        updateFundingChart(data.funding_rates.slice(0, 10));
    } catch (error) {
        console.error('Error fetching funding rates:', error);
    }
}

// Fetch performance by symbol
async function fetchPerformance() {
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        
        const tbody = document.getElementById('performance-body');
        
        if (data.performance.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="no-data">No performance data</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.performance.map(perf => `
            <tr>
                <td><strong>${perf.symbol}</strong></td>
                <td>${perf.total_trades}</td>
                <td>${formatPercent(perf.win_rate)}</td>
                <td class="${perf.total_pnl >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(perf.total_pnl)}
                </td>
                <td class="positive">${formatCurrency(perf.total_funding)}</td>
                <td class="negative">${formatCurrency(perf.total_fees)}</td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error fetching performance:', error);
    }
}

// Fetch equity history for chart
async function fetchEquityHistory() {
    try {
        const response = await fetch('/api/equity-history?days=30');
        const data = await response.json();
        
        if (data.equity_history.length > 0) {
            updateEquityChart(data.equity_history);
        }
    } catch (error) {
        console.error('Error fetching equity history:', error);
    }
}

// Fetch configuration
async function fetchConfig() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();
        
        // Update strategy settings
        document.getElementById('setting-min-funding').textContent = data.strategy.min_funding_rate;
        document.getElementById('setting-max-spread').textContent = data.strategy.max_spread;
        document.getElementById('setting-position-size').textContent = formatPercent(data.strategy.position_size_pct * 100);
        document.getElementById('setting-max-positions').textContent = data.strategy.max_positions;
        
        // Update risk settings
        document.getElementById('setting-max-allocation').textContent = formatPercent(data.risk.max_coin_allocation * 100);
        document.getElementById('setting-margin-warning').textContent = formatPercent(data.risk.margin_ratio_warning * 100);
        document.getElementById('setting-margin-critical').textContent = formatPercent(data.risk.margin_ratio_critical * 100);
        document.getElementById('setting-max-drawdown').textContent = formatPercent(data.risk.max_drawdown * 100);
    } catch (error) {
        console.error('Error fetching config:', error);
    }
}

// Initialize charts
function initCharts() {
    // Equity Chart
    const equityCtx = document.getElementById('equity-chart').getContext('2d');
    equityChart = new Chart(equityCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Total Equity',
                data: [],
                borderColor: '#58a6ff',
                backgroundColor: 'rgba(88, 166, 255, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    grid: {
                        color: '#30363d'
                    },
                    ticks: {
                        color: '#8b949e'
                    }
                },
                y: {
                    grid: {
                        color: '#30363d'
                    },
                    ticks: {
                        color: '#8b949e',
                        callback: value => '$' + value.toLocaleString()
                    }
                }
            }
        }
    });
    
    // Funding Chart
    const fundingCtx = document.getElementById('funding-chart').getContext('2d');
    fundingChart = new Chart(fundingCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'APR %',
                data: [],
                backgroundColor: [],
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#8b949e'
                    }
                },
                y: {
                    grid: {
                        color: '#30363d'
                    },
                    ticks: {
                        color: '#8b949e',
                        callback: value => value + '%'
                    }
                }
            }
        }
    });
}

// Update equity chart
function updateEquityChart(history) {
    if (!equityChart || history.length === 0) return;
    
    equityChart.data.labels = history.map(h => {
        const date = new Date(h.timestamp);
        return date.toLocaleDateString();
    });
    equityChart.data.datasets[0].data = history.map(h => h.total_equity);
    equityChart.update();
}

// Update funding chart
function updateFundingChart(fundingRates) {
    if (!fundingChart || fundingRates.length === 0) return;
    
    fundingChart.data.labels = fundingRates.map(f => f.symbol.replace('USDT', ''));
    fundingChart.data.datasets[0].data = fundingRates.map(f => f.apr);
    fundingChart.data.datasets[0].backgroundColor = fundingRates.map(f => 
        f.apr >= 0 ? 'rgba(35, 134, 54, 0.8)' : 'rgba(218, 54, 51, 0.8)'
    );
    fundingChart.update();
}

// Formatting helpers
function formatCurrency(value) {
    if (value === null || value === undefined || isNaN(value)) return '$0.00';
    return '$' + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPercent(value) {
    if (value === null || value === undefined || isNaN(value)) return '0.00%';
    return value.toFixed(2) + '%';
}

function formatFundingRate(value) {
    if (value === null || value === undefined || isNaN(value)) return '0.0000%';
    return (value * 100).toFixed(4) + '%';
}

function formatPrice(value) {
    if (value === null || value === undefined || isNaN(value)) return '$0.00';
    if (value >= 1) {
        return '$' + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return '$' + value.toFixed(6);
}

function formatVolume(value) {
    if (value === null || value === undefined || isNaN(value)) return '$0';
    if (value >= 1e9) return '$' + (value / 1e9).toFixed(2) + 'B';
    if (value >= 1e6) return '$' + (value / 1e6).toFixed(2) + 'M';
    if (value >= 1e3) return '$' + (value / 1e3).toFixed(2) + 'K';
    return '$' + value.toFixed(2);
}

function formatSide(side) {
    if (side === 'long_spot_short_perp') {
        return '📈 Long Spot / Short Perp';
    }
    return '📉 Short Spot / Long Perp';
}

function formatDuration(hours) {
    if (hours === null || hours === undefined || isNaN(hours)) return '0 min';
    if (hours < 1) return Math.round(hours * 60) + ' min';
    if (hours < 24) return hours.toFixed(1) + ' hrs';
    return (hours / 24).toFixed(1) + ' days';
}

function formatTime(isoString) {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);
    return date.toLocaleTimeString();
}
