# Binance 9/15 EMA Crossover Trading Bot with Automated Risk Management

This bot connects to Binance via `ccxt` and executes a classic **9 EMA & 15 EMA crossover strategy** enhanced with an institutional-grade **Automated Risk Management Engine** (`risk_manager.py`).

---

## 🛡️ Risk Vulnerability Analysis for a \$20 Balance

Operating an algorithmic bot with a **\$20 USDT account balance** presents specific structural challenges:

1. **Binance Minimum Notional Trap (\$5 – \$10 USDT)**:
   - Binance enforces a minimum order notional of \$5 to \$10 USDT per spot trade.
   - On a \$20 balance, a \$15 trade commits **75% of your total capital**.
   - If consecutive unmanaged drawdowns drop the total balance below \$5 or \$10, the exchange rejects subsequent orders (`MIN_NOTIONAL` error), locking you out of recovery.
2. **Lagging Indicator Flash-Crash Vulnerability**:
   - Without a hard Stop-Loss, the bot relies on 5m candle closes for EMA crossovers. In a sudden dump, a bearish crossover may lag by 2–4 candles (10–20 minutes), during which the asset could plunge 5%–15%, destroying \$1.00 – \$3.00+ in a single trade.
3. **Sideways Market Whipsaws & Fee Bleed**:
   - During flat, low-volatility periods, EMAs intertwine repeatedly.
   - Spot taker fees (~0.075% – 0.1% per leg = 0.15% – 0.2% round-trip) combined with bid-ask spread quickly bleed 5%–10% of a \$20 account over multiple false crossovers.
4. **Profit Giveback**:
   - Strong momentum moves often retrace before an EMA bearish crossover occurs. Without a Take-Profit or dynamic Trailing Stop, winning trades turn into losing trades.

---

## 🛡️ Implemented Risk Protections

| Risk Control | Default Value | Protection Mechanism |
|---|---|---|
| **Fixed Stop-Loss** | `1.5%` (`STOP_LOSS_PCT=0.015`) | Hard risk ceiling. Max loss capped at ~\$0.23 on a \$15 trade (~1.1% of portfolio). |
| **Fixed Take-Profit** | `3.5%` (`TAKE_PROFIT_PCT=0.035`) | Locks in ~\$0.53 target profit (Risk-to-Reward ratio > 1:2.3). |
| **Dynamic Trailing Stop** | `Arms @ +1.5%, Trails 1.0%` | Dynamically protects unrealized gains once trade enters green; follows high-water mark. |
| **Daily Circuit Breaker** | `MAX_DAILY_LOSS_USDT=1.00` | Halts all new entries if daily realized loss hits \$1.00 (5% of account), preserving \$19.00 capital. Auto-resets daily. |
| **Volatility Filter (ATR)** | `MIN_ATR_PCT=0.0020` (0.2%) | Rejects entries in flat/dead chop markets where ATR is insufficient to beat fees. |
| **Volume SMA Filter** | `MIN_VOLUME_RATIO=0.80` | Rejects entries on low liquidity / ghost volume (<80% of 20-period Volume SMA). |
| **EMA Spread Filter** | `MIN_EMA_SPREAD_PCT=0.0005` | Blocks micro-crosses of flat, nearly parallel EMA lines. |
| **Minimum Notional Filter** | `MIN_NOTIONAL_USDT=5.00` | Pre-validates trade size against Binance order minimums. |

---

## 🚀 Setup & Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Adjust parameters in `.env`:
```env
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
SYMBOL=BTC/USDT
TIMEFRAME=5m
TRADE_AMOUNT_USDT=15.0

# Safety & Modes
TESTNET=True
DRY_RUN=True

# Risk Protections
STOP_LOSS_PCT=0.015
TAKE_PROFIT_PCT=0.035
TRAILING_STOP_ENABLED=True
TRAILING_STOP_ACTIVATION_PCT=0.015
TRAILING_STOP_CALLBACK_PCT=0.010
MAX_DAILY_LOSS_USDT=1.00
MIN_VOLUME_RATIO=0.80
MIN_ATR_PCT=0.0020
MIN_EMA_SPREAD_PCT=0.0005
```

### 3. Run the Bot
```bash
python bot.py
```

### 4. Run the Multi-Pair Market Scanner & Signal Screener
Scan top Binance liquid pairs across multiple timeframes (5m, 15m, 1h) to detect active crossovers, impending pinches, volume confirmation, and multi-timeframe confluence:
```bash
python scanner.py
```

#### Scanner CLI Options:
```bash
# Scan custom pairs & timeframes
python scanner.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframes 5m,15m,1h

# Set tighter convergence threshold (e.g. 0.05%)
python scanner.py --convergence 0.05

# Continuous real-time monitor mode (refreshes every 30s)
python scanner.py --watch --interval 30

# Custom JSON export destination
python scanner.py --output signals.json
```
Signals are exported cleanly to `signals.json` with detailed metrics (EMA 9, EMA 15, separation %, volume ratio vs 20 SMA, active crossovers, impending setups, and MTF confluence ratings).

### 5. Launch the Web Dashboard & Real-Time Performance Monitor
```bash
python dashboard.py --port 5001
```
Open your browser and navigate to:
```
http://127.0.0.1:5001
```
- **Real-Time KPIs**: Current account balance ($20 initial budget), total net PnL ($ and %), position status, 9 vs 15 EMA values with spread, and win rate.
- **Interactive Candlestick & EMA Chart**: TradingView Lightweight Charts with candlestick series, Fast EMA 9 (cyan), Slow EMA 15 (orange), and BUY/SELL crossover markers. Includes an automatic high-performance Canvas fallback for offline environments.
- **Execution & Signal Feed**: Instant tabular breakdown of all closed & open orders, execution prices, and PnL.
- **Live Terminal Log Stream**: Streams live messages from `bot.log` with auto-scroll.
- **Interactive Simulation**: Click `⚡ Sim Tick` in the navigation header to simulate live market ticks and trigger crossover logic on demand.

### 6. Run Unit & Integration Tests
```bash
python -m unittest test_risk.py test_scanner.py -v
```
All 22 unit tests verify risk manager limits, stop-loss, trailing stops, circuit breakers, scanner calculations, crossover detection, convergence logic, volume confirmations, and atomic JSON persistence.
