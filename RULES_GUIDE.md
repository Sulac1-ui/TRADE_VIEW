# Trading Bot Rules & Safety Verification Guide

This document defines the strict rule set, operating guidelines, and emergency fail-safe procedures for running the Binance 9/15 EMA trading bot with a small capital budget ($20 USDT).

---

## 🔒 The Rule Enforcement Engine (`trading_rules.txt`)

All programmatic constraints are declared in **[`trading_rules.txt`](file:///Users/Admin/Desktop/TRADE_VIEW/trading_rules.txt)**.
Before every single trade loop and order submission, the bot re-verifies these rules.

> [!CAUTION]
> If ANY condition inside `trading_rules.txt` fails, the bot halts trading immediately, logs the violation, and enters **SAFE_STOP** mode.

---

## 📋 Summary of Enforced Guardrails

| Category | Guardrail | Enforcement Value | What happens if violated? |
| :--- | :--- | :--- | :--- |
| **Real Money Switch** | `ALLOW_REAL_MONEY_TRADING` | `False` by default | Bot strictly executes in simulation. Even if you supply real API keys, it will **never** place real orders until you explicitly set this to `True`. |
| **Allowed Pairs** | `ALLOWED_PAIRS` | `BTC/USDT`, `ETH/USDT`, `SOL/USDT` | Bot immediately terminates if configured to trade an unlisted, illiquid meme coin. |
| **Capital Cap** | `MAX_TRADE_AMOUNT_USDT` | `$15.00` | Rejects any order larger than $15.00. |
| **Wallet Reserve** | `MIN_WALLET_RESERVE_USDT` | `$5.00` | Ensures account balance never dips below Binance's minimum threshold. |
| **Hard Stop-Loss** | `MAX_ALLOWED_LOSS_PER_TRADE_PCT` | `1.5%` (`$0.23` on $15) | Exits the position immediately if price drops by 1.5%. |
| **Consecutive Losses**| `MAX_CONSECUTIVE_LOSSES` | `3` trades | Shuts off trading if 3 consecutive trades are stopped out. |
| **Daily Loss Limit** | `MAX_DAILY_LOSS_USDT` | `$1.00` (5% of $20) | Tripping this circuit breaker stops all BUY activity for 24 hours. |
| **Max Trades / Day** | `MAX_TRADES_PER_DAY` | `10` | Prevents overtrading and fee bleeding. |
| **Timeframe Filter** | `MIN_TIMEFRAME` | `15m` | Refuses to execute on high-frequency noise timeframes (like 1m/3m/5m). |
| **Chop Filter** | `MIN_ATR_VOLATILITY_PCT` | `0.20%` | Prevents entries during dead sideways consolidation. |
| **Volume Filter** | `MIN_VOLUME_RATIO` | `0.80` | Requires candle volume to be at least 80% of the 20-period moving average. |

---

## 🛑 How to Change Rules or Force a Stop
1. To change any parameter (e.g., lower max trade size or adjust daily loss limit), simply open and edit [`trading_rules.txt`](file:///Users/Admin/Desktop/TRADE_VIEW/trading_rules.txt). The bot reads this file continuously.
2. To instantly freeze the bot at any time:
   - Set `ALLOW_REAL_MONEY_TRADING=False` in `trading_rules.txt`.
