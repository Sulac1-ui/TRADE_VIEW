"""
State Manager for Binance 9/15 EMA Bot & Dashboard
Handles shared state persistence (state.json) and bot.log parsing.
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "state.json"))
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "bot.log"))
DEFAULT_INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "20.0"))
def get_utc_now_iso() -> str:
    """Returns current UTC time in ISO format ending with Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_to_utc_iso(ts: float) -> str:
    """Converts a Unix timestamp to UTC ISO string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_default_state() -> Dict[str, Any]:
    """Generates default state structure."""
    return {
        "status": "STANDBY",
        "bot_name": "Binance 9/15 EMA Trading Bot",
        "symbol": "BTC/USDT",
        "timeframe": "5m",
        "trade_amount_usdt": 15.0,
        "dry_run": True,
        "testnet": True,
        "balance": {
            "initial": DEFAULT_INITIAL_BALANCE,
            "current": DEFAULT_INITIAL_BALANCE,
            "currency": "USDT",
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
        },
        "position": {
            "in_position": False,
            "symbol": "BTC/USDT",
            "side": "NONE",
            "entry_price": 0.0,
            "current_price": 0.0,
            "qty": 0.0,
            "cost_basis": 0.0,
            "entry_time": None,
            "unrealized_pnl": 0.0,
            "unrealized_pnl_pct": 0.0,
        },
        "indicators": {
            "latest_close": 0.0,
            "ema_9": 0.0,
            "ema_15": 0.0,
            "spread": 0.0,
            "trend": "NEUTRAL",
            "last_signal": "NONE",
            "signal_time": None,
        },
        "stats": {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_volume_usdt": 0.0,
        },
        "candles": [],
        "trades": [],
        "signals": [],
        "last_updated": get_utc_now_iso(),
    }


def save_state(state: Dict[str, Any]) -> None:
    """Atomically writes state to state.json to avoid concurrent read corruption."""
    state["last_updated"] = get_utc_now_iso()
    tmp_file = f"{STATE_FILE}.tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        raise e


def seed_initial_candles_if_empty(state: Dict[str, Any]) -> Dict[str, Any]:
    """Populates realistic initial candle data and indicator calculations if state is fresh."""
    if state.get("candles") and len(state["candles"]) > 0:
        return state

    import random
    import math

    now = int(time.time())
    candle_interval = 300  # 5 minutes
    num_candles = 36
    start_time = now - (num_candles * candle_interval)

    # Base price around $91,500
    base_price = 91400.0
    candles = []
    current_close = base_price

    # Generate realistic price movement with subtle trend
    prices = []
    for i in range(num_candles):
        angle = (i / num_candles) * 2 * math.pi
        noise = (random.random() - 0.48) * 120.0
        wave = math.sin(angle) * 250.0 + (i * 12.0)
        c_open = current_close
        c_close = round(base_price + wave + noise, 2)
        c_high = round(max(c_open, c_close) + random.random() * 80.0, 2)
        c_low = round(min(c_open, c_close) - random.random() * 80.0, 2)
        c_volume = round(random.random() * 4.5 + 0.5, 4)
        c_time = start_time + (i * candle_interval)

        prices.append(c_close)
        current_close = c_close

        candles.append({
            "time": c_time,
            "time_iso": timestamp_to_utc_iso(c_time),
            "open": c_open,
            "high": c_high,
            "low": c_low,
            "close": c_close,
            "volume": c_volume,
            "ema_9": c_close,
            "ema_15": c_close,
        })

    # Compute exponential moving averages accurately
    alpha_9 = 2.0 / (9.0 + 1.0)
    alpha_15 = 2.0 / (15.0 + 1.0)

    ema_9 = prices[0]
    ema_15 = prices[0]

    for i in range(len(candles)):
        p = candles[i]["close"]
        ema_9 = (p * alpha_9) + (ema_9 * (1.0 - alpha_9))
        ema_15 = (p * alpha_15) + (ema_15 * (1.0 - alpha_15))
        candles[i]["ema_9"] = round(ema_9, 2)
        candles[i]["ema_15"] = round(ema_15, 2)

    state["candles"] = candles
    latest = candles[-1]
    spread = round(latest["ema_9"] - latest["ema_15"], 2)

    state["indicators"].update({
        "latest_close": latest["close"],
        "ema_9": latest["ema_9"],
        "ema_15": latest["ema_15"],
        "spread": spread,
        "trend": "BULLISH" if spread > 0 else "BEARISH",
        "last_signal": "BUY" if spread > 0 else "SELL",
        "signal_time": latest["time_iso"],
    })

    # Add initial seed trades if none exist
    if not state.get("trades"):
        t1_time = timestamp_to_utc_iso(start_time + 10 * candle_interval)
        t2_time = timestamp_to_utc_iso(start_time + 22 * candle_interval)
        p1 = round(base_price - 80.0, 2)
        p2 = round(base_price + 110.0, 2)
        qty1 = round(15.0 / p1, 6)
        pnl1 = round((p2 - p1) * qty1, 4)
        pct1 = round(((p2 / p1) - 1.0) * 100.0, 2)

        state["trades"] = [
            {
                "id": "TRD-SIM-101",
                "timestamp": t2_time,
                "symbol": "BTC/USDT",
                "action": "SELL",
                "price": p2,
                "qty": qty1,
                "cost": round(p2 * qty1, 4),
                "pnl": pnl1,
                "pnl_pct": pct1,
                "dry_run": True,
                "status": "CLOSED",
            },
            {
                "id": "TRD-SIM-100",
                "timestamp": t1_time,
                "symbol": "BTC/USDT",
                "action": "BUY",
                "price": p1,
                "qty": qty1,
                "cost": round(p1 * qty1, 4),
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "dry_run": True,
                "status": "CLOSED",
            }
        ]
        state["balance"]["realized_pnl"] = pnl1
        state["balance"]["total_pnl"] = pnl1
        state["balance"]["current"] = round(DEFAULT_INITIAL_BALANCE + pnl1, 4)
        state["balance"]["total_pnl_pct"] = round((pnl1 / DEFAULT_INITIAL_BALANCE) * 100.0, 2)
        state["stats"]["total_trades"] = 1
        state["stats"]["winning_trades"] = 1
        state["stats"]["losing_trades"] = 0
        state["stats"]["win_rate"] = 100.0
        state["stats"]["total_volume_usdt"] = round(15.0 * 2, 2)

    return state


def load_state() -> Dict[str, Any]:
    """Reads state.json or initializes a new state if missing or invalid."""
    data = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None

    if data is None:
        data = get_default_state()

    # Ensure all default keys exist
    default = get_default_state()
    for key, val in default.items():
        if key not in data:
            data[key] = val
        elif isinstance(val, dict) and isinstance(data[key], dict):
            for sub_k, sub_v in val.items():
                if sub_k not in data[key]:
                    data[key][sub_k] = sub_v

    # Seed initial candles if fresh
    data = seed_initial_candles_if_empty(data)
    try:
        save_state(data)
    except Exception:
        pass

    return data


def update_market_candles(state: Dict[str, Any], df_candles) -> Dict[str, Any]:
    """
    Updates the candle list and latest indicator readings from a pandas DataFrame
    that contains: timestamp, open, high, low, close, volume, ema_9, ema_15
    """
    if df_candles is None or len(df_candles) == 0:
        return state

    candles_list = []
    # Take up to the last 50 candles
    subset = df_candles.tail(50)
    for _, row in subset.iterrows():
        t = row["timestamp"]
        # Format timestamp
        if hasattr(t, "isoformat"):
            time_iso = t.isoformat()
            time_unix = int(t.timestamp())
        else:
            time_iso = str(t)
            time_unix = int(time.time())

        close_val = float(row.get("close", 0.0))
        ema9_val = float(row.get("ema_9", 0.0)) if "ema_9" in row and not row.isna().get("ema_9", False) else close_val
        ema15_val = float(row.get("ema_15", 0.0)) if "ema_15" in row and not row.isna().get("ema_15", False) else close_val

        candles_list.append({
            "time": time_unix,
            "time_iso": time_iso,
            "open": float(row.get("open", close_val)),
            "high": float(row.get("high", close_val)),
            "low": float(row.get("low", close_val)),
            "close": close_val,
            "volume": float(row.get("volume", 0.0)),
            "ema_9": round(ema9_val, 2),
            "ema_15": round(ema15_val, 2),
        })

    state["candles"] = candles_list

    # Update latest indicators
    latest = candles_list[-1]
    latest_close = latest["close"]
    ema_9 = latest["ema_9"]
    ema_15 = latest["ema_15"]
    spread = round(ema_9 - ema_15, 2)
    trend = "BULLISH" if spread > 0 else ("BEARISH" if spread < 0 else "NEUTRAL")

    state["indicators"].update({
        "latest_close": latest_close,
        "ema_9": ema_9,
        "ema_15": ema_15,
        "spread": spread,
        "trend": trend,
    })

    # Update position mark price and unrealized PnL if currently in position
    pos = state["position"]
    pos["current_price"] = latest_close
    if pos["in_position"] and pos["entry_price"] > 0:
        qty = pos["qty"]
        unrealized = (latest_close - pos["entry_price"]) * qty
        unrealized_pct = ((latest_close / pos["entry_price"]) - 1.0) * 100.0
        pos["unrealized_pnl"] = round(unrealized, 4)
        pos["unrealized_pnl_pct"] = round(unrealized_pct, 2)
    else:
        pos["unrealized_pnl"] = 0.0
        pos["unrealized_pnl_pct"] = 0.0

    # Update balance overview
    bal = state["balance"]
    bal["unrealized_pnl"] = pos["unrealized_pnl"]
    bal["total_pnl"] = round(bal["realized_pnl"] + bal["unrealized_pnl"], 4)
    bal["current"] = round(bal["initial"] + bal["total_pnl"], 4)
    if bal["initial"] > 0:
        bal["total_pnl_pct"] = round((bal["total_pnl"] / bal["initial"]) * 100.0, 2)

    return state


def record_signal(state: Dict[str, Any], signal_type: str, price: float, ema9: float, ema15: float) -> Dict[str, Any]:
    """Records a BUY or SELL crossover signal."""
    now_iso = get_utc_now_iso()
    state["indicators"]["last_signal"] = signal_type
    state["indicators"]["signal_time"] = now_iso

    signal_entry = {
        "timestamp": now_iso,
        "type": signal_type,
        "price": round(price, 2),
        "ema_9": round(ema9, 2),
        "ema_15": round(ema15, 2),
        "spread": round(ema9 - ema15, 2),
    }

    # Prepend signal
    if "signals" not in state:
        state["signals"] = []
    state["signals"].insert(0, signal_entry)
    # Keep last 50 signals
    state["signals"] = state["signals"][:50]
    return state


def record_trade_execution(
    state: Dict[str, Any],
    action: str,
    price: float,
    qty: float,
    symbol: str,
    is_dry_run: bool = True,
    pnl: float = 0.0,
    pnl_pct: float = 0.0,
) -> Dict[str, Any]:
    """Records BUY or SELL trade execution and updates position/balance."""
    now_iso = get_utc_now_iso()
    pos = state["position"]
    bal = state["balance"]
    stats = state["stats"]

    cost = round(price * qty, 4)
    trade_id = f"TRD-{int(time.time() * 1000)}"

    if action == "BUY":
        pos["in_position"] = True
        pos["symbol"] = symbol
        pos["side"] = "LONG"
        pos["entry_price"] = round(price, 2)
        pos["current_price"] = round(price, 2)
        pos["qty"] = qty
        pos["cost_basis"] = cost
        pos["entry_time"] = now_iso
        pos["unrealized_pnl"] = 0.0
        pos["unrealized_pnl_pct"] = 0.0

        trade_entry = {
            "id": trade_id,
            "timestamp": now_iso,
            "symbol": symbol,
            "action": "BUY",
            "price": round(price, 2),
            "qty": qty,
            "cost": cost,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "dry_run": is_dry_run,
            "status": "OPEN",
        }
    else:  # SELL
        entry_price = pos["entry_price"]
        actual_pnl = round(pnl if pnl != 0 else (price - entry_price) * qty, 4)
        actual_pct = round(pnl_pct if pnl_pct != 0 else (((price / entry_price) - 1.0) * 100.0 if entry_price > 0 else 0.0), 2)

        # Update realized balance
        bal["realized_pnl"] = round(bal["realized_pnl"] + actual_pnl, 4)
        bal["total_pnl"] = round(bal["realized_pnl"], 4)
        bal["current"] = round(bal["initial"] + bal["total_pnl"], 4)
        if bal["initial"] > 0:
            bal["total_pnl_pct"] = round((bal["total_pnl"] / bal["initial"]) * 100.0, 2)

        # Update stats
        stats["total_trades"] += 1
        stats["total_volume_usdt"] = round(stats["total_volume_usdt"] + cost, 2)
        if actual_pnl > 0:
            stats["winning_trades"] += 1
        else:
            stats["losing_trades"] += 1

        if stats["total_trades"] > 0:
            stats["win_rate"] = round((stats["winning_trades"] / stats["total_trades"]) * 100.0, 1)

        # Reset position
        pos["in_position"] = False
        pos["side"] = "NONE"
        pos["entry_price"] = 0.0
        pos["current_price"] = round(price, 2)
        pos["qty"] = 0.0
        pos["cost_basis"] = 0.0
        pos["entry_time"] = None
        pos["unrealized_pnl"] = 0.0
        pos["unrealized_pnl_pct"] = 0.0

        trade_entry = {
            "id": trade_id,
            "timestamp": now_iso,
            "symbol": symbol,
            "action": "SELL",
            "price": round(price, 2),
            "qty": qty,
            "cost": cost,
            "pnl": actual_pnl,
            "pnl_pct": actual_pct,
            "dry_run": is_dry_run,
            "status": "CLOSED",
        }

    if "trades" not in state:
        state["trades"] = []
    state["trades"].insert(0, trade_entry)
    state["trades"] = state["trades"][:100]

    return state


def parse_bot_logs(max_lines: int = 100) -> List[Dict[str, str]]:
    """Reads and parses recent lines from bot.log."""
    if not os.path.exists(LOG_FILE):
        return []

    parsed = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        recent = lines[-max_lines:]
        for line in reversed(recent):
            line_str = line.strip()
            if not line_str:
                continue

            # Standard format: 2026-11-05 18:52:41,465 [INFO] Message
            level = "INFO"
            timestamp = ""
            msg = line_str

            if " [" in line_str and "] " in line_str:
                parts = line_str.split(" [", 1)
                timestamp = parts[0]
                rest = parts[1].split("] ", 1)
                if len(rest) == 2:
                    level = rest[0].strip()
                    msg = rest[1].strip()

            parsed.append({
                "raw": line_str,
                "timestamp": timestamp,
                "level": level,
                "message": msg,
            })
    except Exception as e:
        parsed.append({
            "raw": f"Error reading log file: {e}",
            "timestamp": "",
            "level": "ERROR",
            "message": str(e),
        })

    return parsed


def simulate_tick(state: Dict[str, Any], force_action: Optional[str] = None) -> Dict[str, Any]:
    """Generates a new candle tick and optionally triggers a BUY or SELL simulation."""
    import random
    if not state.get("candles"):
        seed_initial_candles_if_empty(state)

    last_candle = state["candles"][-1]
    last_time = last_candle["time"]
    new_time = last_time + 300

    prev_close = last_candle["close"]
    delta = (random.random() - 0.48) * 150.0
    if force_action == "BUY":
        delta = abs(delta) + 140.0
    elif force_action == "SELL":
        delta = - (abs(delta) + 140.0)

    new_close = round(prev_close + delta, 2)
    new_open = prev_close
    new_high = round(max(new_open, new_close) + random.random() * 50.0, 2)
    new_low = round(min(new_open, new_close) - random.random() * 50.0, 2)
    new_vol = round(random.random() * 3.5 + 0.5, 4)

    # EMA calculation
    alpha_9 = 2.0 / (9.0 + 1.0)
    alpha_15 = 2.0 / (15.0 + 1.0)
    ema_9 = round((new_close * alpha_9) + (last_candle["ema_9"] * (1.0 - alpha_9)), 2)
    ema_15 = round((new_close * alpha_15) + (last_candle["ema_15"] * (1.0 - alpha_15)), 2)

    new_candle = {
        "time": new_time,
        "time_iso": timestamp_to_utc_iso(new_time),
        "open": new_open,
        "high": new_high,
        "low": new_low,
        "close": new_close,
        "volume": new_vol,
        "ema_9": ema_9,
        "ema_15": ema_15,
    }

    state["candles"].append(new_candle)
    if len(state["candles"]) > 60:
        state["candles"] = state["candles"][-60:]

    spread = round(ema_9 - ema_15, 2)
    prev_spread = round(last_candle["ema_9"] - last_candle["ema_15"], 2)

    detected_signal = None
    if force_action in ["BUY", "SELL"]:
        detected_signal = force_action
    elif prev_spread <= 0 and spread > 0:
        detected_signal = "BUY"
    elif prev_spread >= 0 and spread < 0:
        detected_signal = "SELL"

    state["indicators"].update({
        "latest_close": new_close,
        "ema_9": ema_9,
        "ema_15": ema_15,
        "spread": spread,
        "trend": "BULLISH" if spread > 0 else "BEARISH",
    })

    if detected_signal:
        record_signal(state, detected_signal, new_close, ema_9, ema_15)
        trade_amount = state.get("trade_amount_usdt", 15.0)
        pos = state["position"]
        if detected_signal == "BUY" and not pos["in_position"]:
            qty = round(trade_amount / new_close, 6)
            record_trade_execution(state, "BUY", new_close, qty, state.get("symbol", "BTC/USDT"), True)
        elif detected_signal == "SELL" and pos["in_position"]:
            qty = pos["qty"]
            pnl = (new_close - pos["entry_price"]) * qty
            pct = ((new_close / pos["entry_price"]) - 1.0) * 100.0 if pos["entry_price"] > 0 else 0.0
            record_trade_execution(state, "SELL", new_close, qty, state.get("symbol", "BTC/USDT"), True, pnl=pnl, pnl_pct=pct)

    # Update position unrealized pnl
    pos = state["position"]
    pos["current_price"] = new_close
    if pos["in_position"] and pos["entry_price"] > 0:
        qty = pos["qty"]
        pos["unrealized_pnl"] = round((new_close - pos["entry_price"]) * qty, 4)
        pos["unrealized_pnl_pct"] = round(((new_close / pos["entry_price"]) - 1.0) * 100.0, 2)
    else:
        pos["unrealized_pnl"] = 0.0
        pos["unrealized_pnl_pct"] = 0.0

    bal = state["balance"]
    bal["unrealized_pnl"] = pos["unrealized_pnl"]
    bal["total_pnl"] = round(bal["realized_pnl"] + bal["unrealized_pnl"], 4)
    bal["current"] = round(bal["initial"] + bal["total_pnl"], 4)
    if bal["initial"] > 0:
        bal["total_pnl_pct"] = round((bal["total_pnl"] / bal["initial"]) * 100.0, 2)

    save_state(state)
    return state

