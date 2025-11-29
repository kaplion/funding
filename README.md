# Binance Funding Rate Arbitrage Bot

A comprehensive funding rate arbitrage bot for Binance that creates delta-neutral positions to earn funding rate income.

## Overview

This bot implements a funding rate arbitrage strategy that:

- **Positive funding rate**: Opens long spot + short perpetual positions (earns funding)
- **Negative funding rate**: Opens short spot (margin) + long perpetual positions (earns funding)
- Maintains **delta-neutral positions** to eliminate price risk
- Provides a **real-time web dashboard** for monitoring

## Features

### Core Trading
- Automated funding rate scanning for all USDT perpetual pairs
- Entry/exit logic based on funding rate thresholds
- Delta-neutral position management
- Synchronized spot and futures order execution
- Limit order preference with automatic market order fallback

### Risk Management
- Maximum position count limits
- Per-coin allocation limits
- Margin ratio monitoring
- Liquidation distance tracking
- Auto-deleverage risk monitoring
- Maximum drawdown protection

### Monitoring & Notifications
- Real-time web dashboard with FastAPI
- Equity curve and P&L charts
- Position performance tracking
- Telegram notifications (optional)
- Risk alerts

## Project Structure

```
funding/
├── src/
│   ├── __init__.py           # Package initialization
│   ├── bot.py                # Main bot orchestration
│   ├── data_collector.py     # Funding rate data collection
│   ├── strategy.py           # Entry/exit logic
│   ├── executor.py           # Order execution
│   ├── risk_manager.py       # Risk management
│   ├── accounting.py         # P&L tracking
│   ├── notifications.py      # Telegram notifications
│   ├── dashboard.py          # Web dashboard
│   └── models.py             # SQLAlchemy models
├── config/
│   ├── config.py             # Configuration management
│   └── config.example.yaml   # Example configuration
├── templates/
│   └── dashboard.html        # Dashboard UI template
├── static/
│   ├── css/style.css         # Dashboard styles
│   └── js/main.js            # Dashboard JavaScript
├── tests/
│   ├── test_data_collector.py
│   ├── test_strategy.py
│   ├── test_risk_manager.py
│   └── test_accounting.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Installation

### Prerequisites

- Python 3.10+
- Binance account with API access
- Spot and Futures trading enabled

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/kaplion/funding.git
   cd funding
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API credentials
   ```

5. **Configure strategy (optional)**
   ```bash
   cp config/config.example.yaml config/config.yaml
   # Edit config/config.yaml as needed
   ```

## Configuration

### Environment Variables (.env)

```bash
# Binance API credentials
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
BINANCE_TESTNET=false  # Use testnet for testing

# Telegram notifications (optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Database
DATABASE_URL=sqlite:///./funding_bot.db
```

### Strategy Configuration (config.yaml)

```yaml
strategy:
  min_funding_rate: 0.0003    # ~32% APR threshold
  max_spread: 0.001           # 0.1% max spread
  position_size_pct: 0.1      # 10% of equity per position
  max_positions: 5            # Max concurrent positions
  recheck_interval: 300       # 5 minutes

risk:
  max_coin_allocation: 0.2    # 20% max per coin
  margin_ratio_warning: 0.7   # 70% warning
  margin_ratio_critical: 0.85 # 85% critical
  min_liquidation_distance: 0.15
  max_drawdown: 0.1           # 10% max drawdown
```

## Usage

### Running the Bot

```bash
# Direct execution
python -m src.bot

# With custom config
python -m src.bot --config config/config.yaml
```

### Running with Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f funding-bot

# Stop
docker-compose down
```

### Dashboard

The web dashboard is available at `http://localhost:8000` when the bot is running.

Features:
- Real-time equity and P&L tracking
- Open positions with current funding rates
- Risk metrics (margin ratio, liquidation distance)
- Funding rate leaderboard
- Performance by symbol
- Bot start/stop controls

## API Endpoints

The dashboard exposes the following REST API:

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | Bot running status |
| `GET /api/overview` | Account overview and P&L |
| `GET /api/positions` | All positions |
| `GET /api/positions/open` | Open positions only |
| `GET /api/risk-metrics` | Current risk metrics |
| `GET /api/funding-rates` | Top funding rates |
| `GET /api/funding-history` | Funding payment history |
| `GET /api/equity-history` | Equity history for charts |
| `GET /api/performance` | Performance by symbol |
| `GET /api/config` | Current configuration |
| `POST /api/bot/start` | Start the bot |
| `POST /api/bot/stop` | Stop the bot |

## Strategy Details

### Entry Criteria

1. Funding rate above threshold (default: 0.03% per 8h = ~32% APR)
2. Spot/futures spread below maximum (default: 0.1%)
3. Below maximum position count
4. No existing position in the symbol
5. Within allocation limits

### Exit Criteria

1. Funding rate drops below 50% of threshold
2. Spread widens to 2x maximum
3. Margin ratio reaches critical level
4. Risk management triggers

### Position Sizing

- Default: 10% of total equity per position
- Maximum per coin: 20% of equity
- Maximum total positions: 5

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_strategy.py -v
```

## Risk Disclaimer

⚠️ **WARNING**: Trading cryptocurrencies involves significant risk. This bot is provided for educational purposes only. Always:

- Start with small amounts
- Test on testnet first
- Monitor positions regularly
- Understand the risks of leverage trading
- Never invest more than you can afford to lose

The authors are not responsible for any financial losses.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request