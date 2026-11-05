#!/usr/bin/env python3
"""
Binance Multi-Pair Market Scanner & Signal Screener
Strategy: 9 EMA & 15 EMA Crossover Strategy
Author: Antigravity Team
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

import pandas as pd
import ccxt
from dotenv import load_dotenv

# Load environment configuration if available
load_dotenv()

# Default Configurations
DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
]

DEFAULT_TIMEFRAMES = ["5m", "15m", "1h"]
DEFAULT_CONVERGENCE_PCT = 0.10  # 0.10% threshold for impending crossover
DEFAULT_OUTPUT_FILE = "signals.json"
CANDLE_LIMIT = 100  # Warmup periods for precise EMA calculation

# ANSI Color Codes for Terminal Output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    
    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    
    # Background colors
    BG_GREEN = "\033[42m\033[30m"
    BG_RED = "\033[41m\033[37m"
    BG_YELLOW = "\033[43m\033[30m"
    BG_CYAN = "\033[46m\033[30m"


def supports_color() -> bool:
    """Checks whether the environment supports ANSI terminal colors."""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def colorize(text: str, color_code: str, use_color: bool = True) -> str:
    """Wraps text in ANSI color if supported."""
    if not use_color:
        return text
    return f"{color_code}{text}{Colors.RESET}"


def init_exchange(sandbox: bool = False) -> ccxt.binance:
    """Initializes the ccxt Binance client for public market data."""
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    
    exchange_config = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
        },
        "timeout": 15000,
    }
    exchange = ccxt.binance(exchange_config)
    if sandbox or os.getenv("TESTNET", "False").lower() == "true":
        exchange.set_sandbox_mode(True)
    return exchange


def fetch_and_analyze(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    convergence_pct: float = DEFAULT_CONVERGENCE_PCT,
    limit: int = CANDLE_LIMIT
) -> Dict[str, Any]:
    """
    Fetches OHLCV candle data for a given symbol and timeframe,
    computes EMA 9, EMA 15, volume moving average, and detects:
      - Confirmed crossover (on last closed candle)
      - Live crossover (on current forming candle)
      - Impending crossover (distance <= convergence_pct and converging)
      - Trend strength and volume confirmation
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 30:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "error": f"Insufficient candles returned ({len(ohlcv) if ohlcv else 0})",
            }

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        # Exponential Moving Averages
        df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema_15"] = df["close"].ewm(span=15, adjust=False).mean()

        # Volume 20-period Moving Average
        df["vol_sma_20"] = df["volume"].rolling(window=20).mean()

        # Candle references
        c_prev2 = df.iloc[-3]  # Closed candle prior
        c_prev1 = df.iloc[-2]  # Last fully closed candle
        c_curr = df.iloc[-1]   # Current forming candle

        curr_price = float(c_curr["close"])
        curr_ema9 = float(c_curr["ema_9"])
        curr_ema15 = float(c_curr["ema_15"])
        prev_ema9 = float(c_prev1["ema_9"])
        prev_ema15 = float(c_prev1["ema_15"])
        prev2_ema9 = float(c_prev2["ema_9"])
        prev2_ema15 = float(c_prev2["ema_15"])

        # 1. Crossover detection on closed candle (confirmed signal)
        crossover_closed = None
        if prev2_ema9 <= prev2_ema15 and prev_ema9 > prev_ema15:
            crossover_closed = "BULLISH_CROSSOVER"
        elif prev2_ema9 >= prev2_ema15 and prev_ema9 < prev_ema15:
            crossover_closed = "BEARISH_CROSSOVER"

        # 2. Crossover detection on live/forming candle (early warning signal)
        crossover_live = None
        if prev_ema9 <= prev_ema15 and curr_ema9 > curr_ema15:
            crossover_live = "LIVE_BULLISH_CROSS"
        elif prev_ema9 >= prev_ema15 and curr_ema9 < curr_ema15:
            crossover_live = "LIVE_BEARISH_CROSS"

        # 3. EMA separation and convergence calculations
        diff_val = curr_ema9 - curr_ema15
        diff_pct = (diff_val / curr_ema15) * 100 if curr_ema15 > 0 else 0.0
        abs_diff_pct = abs(diff_pct)

        prev_diff_val = prev_ema9 - prev_ema15
        prev_diff_pct = (prev_diff_val / prev_ema15) * 100 if prev_ema15 > 0 else 0.0
        prev_abs_diff_pct = abs(prev_diff_pct)

        # Is EMA 9 actively moving closer to EMA 15?
        is_converging = abs_diff_pct < prev_abs_diff_pct

        # Impending crossover detection
        impending = False
        impending_type = None
        if abs_diff_pct <= convergence_pct and not crossover_closed and not crossover_live:
            impending = True
            if curr_ema9 < curr_ema15:
                impending_type = "IMPENDING_BULLISH"  # Approaching from below
            else:
                impending_type = "IMPENDING_BEARISH"  # Approaching from above

        # 4. Volume Confirmation (using closed candle and current forming candle)
        closed_vol = float(c_prev1["volume"])
        closed_vol_sma = float(c_prev1["vol_sma_20"]) if not pd.isna(c_prev1["vol_sma_20"]) else 0.0
        closed_vol_ratio = (closed_vol / closed_vol_sma) if closed_vol_sma > 0 else 1.0

        curr_vol = float(c_curr["volume"])
        curr_vol_sma = float(c_curr["vol_sma_20"]) if not pd.isna(c_curr["vol_sma_20"]) else 0.0

        # Estimate elapsed fraction of current forming candle to calculate projected volume
        candle_ms_map = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        candle_duration_ms = candle_ms_map.get(timeframe, 300_000)
        curr_candle_open_ms = int(c_curr["timestamp"].timestamp() * 1000)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        elapsed_ms = max(2000, min(candle_duration_ms, now_ms - curr_candle_open_ms))
        elapsed_fraction = elapsed_ms / candle_duration_ms

        projected_curr_vol = (curr_vol / elapsed_fraction) if elapsed_fraction > 0 else curr_vol
        projected_vol_ratio = (projected_curr_vol / curr_vol_sma) if curr_vol_sma > 0 else 1.0

        # Primary volume ratio to use for confirmation:
        # If live crossover, evaluate projected volume on forming bar; otherwise use completed bar volume.
        active_vol_ratio = projected_vol_ratio if crossover_live else closed_vol_ratio

        if active_vol_ratio >= 1.5:
            vol_rating = "SURGE"
            vol_confirmed = True
        elif active_vol_ratio >= 1.0:
            vol_rating = "ABOVE_AVG"
            vol_confirmed = True
        else:
            vol_rating = "LOW"
            vol_confirmed = False

        # 5. Trend Strength Classification
        if abs_diff_pct >= 0.40:
            trend_strength = "STRONG"
        elif abs_diff_pct >= 0.15:
            trend_strength = "MODERATE"
        else:
            trend_strength = "WEAK"

        trend_direction = "BULLISH" if curr_ema9 > curr_ema15 else ("BEARISH" if curr_ema9 < curr_ema15 else "FLAT")

        # 6. Overall Signal Summary
        primary_signal = "NEUTRAL"
        action = "HOLD"
        urgency = "LOW"

        if crossover_closed == "BULLISH_CROSSOVER":
            primary_signal = "CONFIRMED_BULL_CROSS"
            action = "STRONG_BUY" if vol_confirmed else "BUY"
            urgency = "HIGH"
        elif crossover_closed == "BEARISH_CROSSOVER":
            primary_signal = "CONFIRMED_BEAR_CROSS"
            action = "STRONG_SELL" if vol_confirmed else "SELL"
            urgency = "HIGH"
        elif crossover_live == "LIVE_BULLISH_CROSS":
            primary_signal = "LIVE_BULL_CROSS"
            action = "BUY_ALERT"
            urgency = "HIGH"
        elif crossover_live == "LIVE_BEARISH_CROSS":
            primary_signal = "LIVE_BEAR_CROSS"
            action = "SELL_ALERT"
            urgency = "HIGH"
        elif impending_type == "IMPENDING_BULLISH":
            primary_signal = "IMPENDING_BULL_CROSS"
            action = "WATCH_BUY"
            urgency = "MEDIUM"
        elif impending_type == "IMPENDING_BEARISH":
            primary_signal = "IMPENDING_BEAR_CROSS"
            action = "WATCH_SELL"
            urgency = "MEDIUM"
        else:
            if trend_direction == "BULLISH":
                primary_signal = f"{trend_strength}_BULL_TREND"
                action = "HOLD_LONG" if trend_strength == "STRONG" else "WATCH"
            else:
                primary_signal = f"{trend_strength}_BEAR_TREND"
                action = "HOLD_SHORT" if trend_strength == "STRONG" else "WATCH"

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": curr_price,
            "ema_9": curr_ema9,
            "ema_15": curr_ema15,
            "diff_pct": diff_pct,
            "abs_diff_pct": abs_diff_pct,
            "trend_direction": trend_direction,
            "trend_strength": trend_strength,
            "is_converging": is_converging,
            "crossover_closed": crossover_closed,
            "crossover_live": crossover_live,
            "impending": impending,
            "impending_type": impending_type,
            "volume_ratio": active_vol_ratio,
            "closed_vol_ratio": closed_vol_ratio,
            "projected_vol_ratio": projected_vol_ratio,
            "volume_rating": vol_rating,
            "volume_confirmed": vol_confirmed,
            "primary_signal": primary_signal,
            "action": action,
            "urgency": urgency,
            "last_closed_time": str(c_prev1["timestamp"]),
            "current_time": str(c_curr["timestamp"]),
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "error": str(e),
        }


def scan_market(
    symbols: List[str] = DEFAULT_SYMBOLS,
    timeframes: List[str] = DEFAULT_TIMEFRAMES,
    convergence_pct: float = DEFAULT_CONVERGENCE_PCT,
    max_workers: int = 6,
    exchange: Optional[ccxt.binance] = None
) -> Dict[str, Any]:
    """
    Executes concurrent scans across all symbol and timeframe pairs.
    Returns structured results including summary lists for crossovers,
    impending setups, and multi-timeframe confluence.
    """
    if exchange is None:
        exchange = init_exchange()

    start_time = time.time()
    scan_timestamp = datetime.now(timezone.utc).isoformat()

    tasks = [(sym, tf) for sym in symbols for tf in timeframes]
    results_list: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(fetch_and_analyze, exchange, sym, tf, convergence_pct): (sym, tf)
            for sym, tf in tasks
        }
        for future in as_completed(future_to_task):
            res = future.result()
            results_list.append(res)

    duration = round(time.time() - start_time, 2)

    # Sort results by symbol then timeframe order
    tf_order = {tf: i for i, tf in enumerate(timeframes)}
    results_list.sort(key=lambda r: (r.get("symbol", ""), tf_order.get(r.get("timeframe", ""), 99)))

    # Categorize signals
    active_crossovers = []
    impending_signals = []
    strong_trends = []
    symbols_map: Dict[str, Dict[str, Any]] = {}

    for r in results_list:
        if "error" in r:
            continue
        sym = r["symbol"]
        tf = r["timeframe"]

        if sym not in symbols_map:
            symbols_map[sym] = {}
        symbols_map[sym][tf] = r

        # Check for active crossovers
        if r.get("crossover_closed") or r.get("crossover_live"):
            active_crossovers.append(r)
        elif r.get("impending"):
            impending_signals.append(r)
        elif r.get("trend_strength") == "STRONG":
            strong_trends.append(r)

    # Multi-Timeframe (MTF) Confluence Analysis
    mtf_confluence = []
    for sym, tfs_data in symbols_map.items():
        bull_votes = 0
        bear_votes = 0
        total_valid = 0
        details = []

        for tf in timeframes:
            if tf in tfs_data:
                d = tfs_data[tf]
                total_valid += 1
                sig = d.get("primary_signal", "")
                direction = d.get("trend_direction", "")
                cross_mark = ""
                if d.get("crossover_closed") or d.get("crossover_live"):
                    cross_mark = "⚡"
                elif d.get("impending"):
                    cross_mark = "⏳"

                if direction == "BULLISH":
                    bull_votes += 1
                    details.append(f"{tf}: BULL{cross_mark}")
                elif direction == "BEARISH":
                    bear_votes += 1
                    details.append(f"{tf}: BEAR{cross_mark}")
                else:
                    details.append(f"{tf}: FLAT")

        confluence_status = "MIXED"
        if total_valid > 0:
            if bull_votes == total_valid:
                confluence_status = "ALL_BULLISH_CONFLUENCE"
            elif bear_votes == total_valid:
                confluence_status = "ALL_BEARISH_CONFLUENCE"
            elif bull_votes >= 2 and total_valid >= 3:
                confluence_status = "LEANING_BULLISH"
            elif bear_votes >= 2 and total_valid >= 3:
                confluence_status = "LEANING_BEARISH"

        latest_price = next((tfs_data[tf]["price"] for tf in timeframes if tf in tfs_data), 0.0)

        mtf_confluence.append({
            "symbol": sym,
            "price": latest_price,
            "confluence": confluence_status,
            "bull_votes": bull_votes,
            "bear_votes": bear_votes,
            "total_timeframes": total_valid,
            "breakdown": " | ".join(details)
        })

    return {
        "timestamp": scan_timestamp,
        "duration_seconds": duration,
        "config": {
            "symbols": symbols,
            "timeframes": timeframes,
            "convergence_pct": convergence_pct,
        },
        "summary": {
            "total_scanned": len(results_list),
            "active_crossovers_count": len(active_crossovers),
            "impending_count": len(impending_signals),
            "strong_trends_count": len(strong_trends),
        },
        "active_crossovers": active_crossovers,
        "impending_crossovers": impending_signals,
        "strong_trends": strong_trends,
        "mtf_confluence": mtf_confluence,
        "all_results": results_list,
    }


def format_price(price: float) -> str:
    """Formats price with appropriate precision based on magnitude."""
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    else:
        return f"{price:.6f}"


def print_cli_report(data: Dict[str, Any], use_color: bool = True):
    """Renders a structured, clean terminal view of market scanner results."""
    cfg = data["config"]
    summary = data["summary"]
    timestamp = data["timestamp"]
    duration = data["duration_seconds"]

    print("")
    header_title = " ⚡ BINANCE 9/15 EMA CROSSOVER MARKET SCANNER ⚡ "
    print(colorize("=" * 88, Colors.CYAN, use_color))
    print(colorize(header_title.center(88), Colors.BOLD + Colors.CYAN, use_color))
    print(colorize("=" * 88, Colors.CYAN, use_color))
    conv_val = cfg['convergence_pct']
    print(
        f"  Scan Time: {colorize(timestamp, Colors.BOLD, use_color)} | "
        f"Duration: {colorize(f'{duration}s', Colors.GREEN, use_color)} | "
        f"Convergence Threshold: {colorize(f'{conv_val}%', Colors.YELLOW, use_color)}"
    )
    print(
        f"  Scanned: {len(cfg['symbols'])} pairs across {len(cfg['timeframes'])} timeframes ({summary['total_scanned']} checks) | "
        f"Crossovers: {colorize(str(summary['active_crossovers_count']), Colors.RED if summary['active_crossovers_count'] > 0 else Colors.GRAY, use_color)} | "
        f"Impending: {colorize(str(summary['impending_count']), Colors.YELLOW if summary['impending_count'] > 0 else Colors.GRAY, use_color)}"
    )
    print(colorize("-" * 88, Colors.GRAY, use_color))

    # SECTION 1: Active Crossovers
    active = data["active_crossovers"]
    print(f"\n{colorize('🚨 1. ACTIVE & LIVE CROSSOVERS (IMMEDIATE ACTION SIGNALS)', Colors.BOLD + Colors.WHITE, use_color)}")
    if not active:
        print(colorize("   No active crossovers at this exact moment.", Colors.GRAY, use_color))
    else:
        for item in active:
            sym = item["symbol"]
            tf = item["timeframe"]
            price_str = format_price(item["price"])
            vol_ratio = item["volume_ratio"]
            action = item["action"]
            sig = item["primary_signal"]
            diff_pct = item["diff_pct"]

            if "BULL" in sig:
                badge = colorize(f" [BUY SIGNAL] {sig} ", Colors.BG_GREEN, use_color)
                act_str = colorize(action, Colors.GREEN + Colors.BOLD, use_color)
            else:
                badge = colorize(f" [SELL SIGNAL] {sig} ", Colors.BG_RED, use_color)
                act_str = colorize(action, Colors.RED + Colors.BOLD, use_color)

            vol_badge = colorize(f"{vol_ratio:.2f}x Vol", Colors.GREEN if vol_ratio >= 1.0 else Colors.YELLOW, use_color)
            diff_str = colorize(f"EMA Diff: {diff_pct:+.3f}%", Colors.CYAN, use_color)

            print(f"   • {colorize(f'{sym:<10}', Colors.BOLD, use_color)} [{tf:>3}] {badge} at ${price_str} | {diff_str} | {vol_badge} -> {act_str}")

    # SECTION 2: Impending Crossovers
    impending = data["impending_crossovers"]
    print(f"\n{colorize('⏳ 2. IMPENDING CROSSOVERS (WATCHLIST - CONVERGING WITHIN 0.1%)', Colors.BOLD + Colors.WHITE, use_color)}")
    if not impending:
        print(colorize("   No impending crossovers converging within threshold.", Colors.GRAY, use_color))
    else:
        for item in impending:
            sym = item["symbol"]
            tf = item["timeframe"]
            price_str = format_price(item["price"])
            diff_pct = item["diff_pct"]
            abs_diff = item["abs_diff_pct"]
            converging = item["is_converging"]
            imp_type = item["impending_type"]
            vol_ratio = item["volume_ratio"]

            if imp_type == "IMPENDING_BULLISH":
                target_str = colorize("POTENTIAL GOLDEN CROSS (EMA9 -> EMA15)", Colors.GREEN, use_color)
                arrow = colorize("▲ Approaching from below", Colors.GREEN, use_color)
            else:
                target_str = colorize("POTENTIAL DEATH CROSS (EMA9 -> EMA15)", Colors.RED, use_color)
                arrow = colorize("▼ Approaching from above", Colors.RED, use_color)

            conv_status = colorize("PINCHING", Colors.BOLD + Colors.YELLOW, use_color) if converging else "Hovering"
            vol_info = f"Vol: {vol_ratio:.2f}x"

            print(
                f"   • {colorize(f'{sym:<10}', Colors.BOLD, use_color)} [{tf:>3}] ${price_str} | "
                f"Gap: {colorize(f'{abs_diff:.3f}%', Colors.YELLOW, use_color)} ({diff_pct:+.3f}%) | "
                f"{arrow} | {conv_status} | {target_str} ({vol_info})"
            )

    # SECTION 3: Multi-Timeframe (MTF) Confluence
    mtf = data["mtf_confluence"]
    print(f"\n{colorize('🌐 3. MULTI-TIMEFRAME CONFLUENCE SUMMARY (5m / 15m / 1h)', Colors.BOLD + Colors.WHITE, use_color)}")
    for m in mtf:
        sym = m["symbol"]
        price_str = format_price(m["price"])
        conf = m["confluence"]
        breakdown = m["breakdown"]

        if conf == "ALL_BULLISH_CONFLUENCE":
            conf_str = colorize("STRONG BULL CONFLUENCE (3/3) 🟢", Colors.GREEN + Colors.BOLD, use_color)
        elif conf == "ALL_BEARISH_CONFLUENCE":
            conf_str = colorize("STRONG BEAR CONFLUENCE (3/3) 🔴", Colors.RED + Colors.BOLD, use_color)
        elif conf == "LEANING_BULLISH":
            conf_str = colorize("LEANING BULL (2/3) ↗", Colors.GREEN, use_color)
        elif conf == "LEANING_BEARISH":
            conf_str = colorize("LEANING BEAR (2/3) ↘", Colors.RED, use_color)
        else:
            conf_str = colorize("MIXED / CHOPPY ⬌", Colors.GRAY, use_color)

        print(f"   • {colorize(f'{sym:<10}', Colors.BOLD, use_color)} ${price_str:<10} | {conf_str:<32} | [{breakdown}]")

    # SECTION 4: Complete Screener Table
    print(f"\n{colorize('📋 4. FULL SCREENER MATRIX', Colors.BOLD + Colors.WHITE, use_color)}")
    col_sym = f"{'Symbol':<10}"
    col_tf = f"{'TF':<4}"
    col_price = f"{'Price':<12}"
    col_ema9 = f"{'EMA 9':<12}"
    col_ema15 = f"{'EMA 15':<12}"
    col_diff = f"{'EMA Diff %':<11}"
    col_trend = f"{'Trend (9 vs 15)':<16}"
    col_vol = f"{'Vol Ratio':<10}"
    col_status = f"{'Status / Action':<20}"

    table_header = f"   {col_sym} {col_tf} {col_price} {col_ema9} {col_ema15} {col_diff} {col_trend} {col_vol} {col_status}"
    print(colorize(table_header, Colors.UNDERLINE + Colors.BOLD, use_color))

    for item in data["all_results"]:
        if "error" in item:
            print(f"   {item['symbol']:<10} {item['timeframe']:<4} ERROR: {item['error']}")
            continue

        sym = item["symbol"]
        tf = item["timeframe"]
        price_s = format_price(item["price"])
        ema9_s = format_price(item["ema_9"])
        ema15_s = format_price(item["ema_15"])
        diff_pct = item["diff_pct"]
        vol_r = f"{item['volume_ratio']:.2f}x"
        strength = item["trend_strength"]
        direction = item["trend_direction"]
        primary = item["primary_signal"]

        # Color formatting for rows
        diff_str = f"{diff_pct:+.3f}%"
        if diff_pct > 0:
            diff_colored = colorize(f"{diff_str:<11}", Colors.GREEN, use_color)
            trend_str = colorize(f"{direction:<7} ({strength:<6})", Colors.GREEN, use_color)
        else:
            diff_colored = colorize(f"{diff_str:<11}", Colors.RED, use_color)
            trend_str = colorize(f"{direction:<7} ({strength:<6})", Colors.RED, use_color)

        if "BULL_CROSS" in primary:
            status_colored = colorize(f"{primary:<20}", Colors.GREEN + Colors.BOLD, use_color)
        elif "BEAR_CROSS" in primary:
            status_colored = colorize(f"{primary:<20}", Colors.RED + Colors.BOLD, use_color)
        elif "IMPENDING" in primary:
            status_colored = colorize(f"{primary:<20}", Colors.YELLOW, use_color)
        else:
            status_colored = colorize(f"{primary:<20}", Colors.GRAY, use_color)

        vol_colored = colorize(f"{vol_r:<10}", Colors.GREEN if item["volume_confirmed"] else Colors.GRAY, use_color)

        print(f"   {sym:<10} {tf:<4} {price_s:<12} {ema9_s:<12} {ema15_s:<12} {diff_colored} {trend_str:<16} {vol_colored} {status_colored}")

    print(colorize("=" * 88, Colors.CYAN, use_color))
    print("")


def save_signals_to_file(data: Dict[str, Any], filepath: str = DEFAULT_OUTPUT_FILE) -> bool:
    """Saves scanner results to JSON file cleanly."""
    try:
        # Atomic write pattern
        temp_file = f"{filepath}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        print(f"Error saving signals to {filepath}: {e}", file=sys.stderr)
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Binance 9/15 EMA Crossover Multi-Pair Market Scanner & Signal Screener"
    )
    parser.add_argument(
        "-s", "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols to scan (e.g. BTC/USDT,ETH/USDT,SOL/USDT)"
    )
    parser.add_argument(
        "-t", "--timeframes",
        type=str,
        default=",".join(DEFAULT_TIMEFRAMES),
        help="Comma-separated timeframes to scan (e.g. 5m,15m,1h)"
    )
    parser.add_argument(
        "-c", "--convergence",
        type=float,
        default=DEFAULT_CONVERGENCE_PCT,
        help=f"Convergence percentage threshold for impending crossovers (default: {DEFAULT_CONVERGENCE_PCT} percent)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f"JSON file path to save signals (default: {DEFAULT_OUTPUT_FILE})"
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Do not save output to JSON file"
    )
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Continuously monitor and scan in a loop"
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        default=30,
        help="Seconds to wait between scans in watch mode (default: 30)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Number of concurrent worker threads (default: 6)"
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Binance Testnet sandbox"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip().lower() for t in args.timeframes.split(",") if t.strip()]

    use_color = supports_color()
    exchange = init_exchange(sandbox=args.testnet)

    if args.watch:
        print(colorize(f"Starting continuous market scanner (every {args.interval}s)... Press Ctrl+C to stop.", Colors.BOLD + Colors.CYAN, use_color))
        try:
            while True:
                data = scan_market(
                    symbols=symbols,
                    timeframes=timeframes,
                    convergence_pct=args.convergence,
                    max_workers=args.workers,
                    exchange=exchange
                )
                print_cli_report(data, use_color=use_color)
                if not args.no_json:
                    save_signals_to_file(data, args.output)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(colorize("\nScanner stopped by user.", Colors.YELLOW, use_color))
    else:
        data = scan_market(
            symbols=symbols,
            timeframes=timeframes,
            convergence_pct=args.convergence,
            max_workers=args.workers,
            exchange=exchange
        )
        print_cli_report(data, use_color=use_color)
        if not args.no_json:
            saved = save_signals_to_file(data, args.output)
            if saved:
                print(colorize(f"💾 Saved latest signals to {args.output}", Colors.DIM, use_color))


if __name__ == "__main__":
    main()
