"""
Historical Backtesting Engine for 9/15 EMA Crossover Strategy
Simulates trading on Binance pairs (BTC/USDT, ETH/USDT, SOL/USDT) across multiple timeframes (5m, 15m, 1h).
"""

import os
import sys
import time
import argparse
import datetime
import pandas as pd
import numpy as np
import ccxt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


class DataLoader:
    """Handles fetching and caching historical OHLCV candle data via ccxt."""

    def __init__(self, exchange=None):
        self.exchange = exchange or ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"}
        })

    def get_cache_path(self, symbol: str, timeframe: str, days: int) -> str:
        clean_symbol = symbol.replace("/", "_").replace(":", "_")
        return os.path.join(DATA_DIR, f"{clean_symbol}_{timeframe}_{days}d.csv")

    def fetch_historical_ohlcv(self, symbol: str, timeframe: str, days: int = 60, refresh: bool = False) -> pd.DataFrame:
        cache_file = self.get_cache_path(symbol, timeframe, days)

        # Check cache validity (use cache if exists and not older than 6 hours unless refresh=True)
        if not refresh and os.path.exists(cache_file):
            file_age = time.time() - os.path.getmtime(cache_file)
            if file_age < 6 * 3600:
                print(f"  [Cache hit] Loading {symbol} {timeframe} ({days}d) from {os.path.basename(cache_file)}")
                df = pd.read_csv(cache_file)
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                return df

        print(f"  [Fetching] Downloading {symbol} {timeframe} ({days} days) from Binance...")
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - (days * 24 * 3600 * 1000)
        since = start_ts

        all_candles = []
        consecutive_empty = 0

        while since < end_ts:
            try:
                candles = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
                if not candles:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                    time.sleep(0.5)
                    continue

                consecutive_empty = 0
                all_candles.extend(candles)
                last_ts = candles[-1][0]

                # Advance timestamp past the last fetched candle
                if last_ts == since:
                    break
                since = last_ts + 1

                if len(candles) < 1000:
                    break

            except Exception as e:
                print(f"  [Warning] Error fetching {symbol} {timeframe} at {since}: {e}. Retrying in 2s...")
                time.sleep(2)

        if not all_candles:
            raise RuntimeError(f"Failed to fetch any candles for {symbol} {timeframe}")

        df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values(by="timestamp")
        df = df.reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Save to CSV cache
        df.to_csv(cache_file, index=False)
        print(f"  [Saved] Cached {len(df)} candles to {os.path.basename(cache_file)}")
        return df


class Strategy:
    """9/15 EMA Crossover Strategy implementation."""

    @staticmethod
    def calculate_indicators(df: pd.DataFrame, fast_span: int = 9, slow_span: int = 15) -> pd.DataFrame:
        df = df.copy()
        df["ema_9"] = df["close"].ewm(span=fast_span, adjust=False).mean()
        df["ema_15"] = df["close"].ewm(span=slow_span, adjust=False).mean()
        return df

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
        """
        Generates crossover signals:
        - Bullish crossover (EMA 9 crosses above EMA 15) -> BUY (1)
        - Bearish crossover (EMA 9 crosses below EMA 15) -> SELL (-1)
        - Otherwise -> 0
        """
        df = df.copy()
        df["prev_ema_9"] = df["ema_9"].shift(1)
        df["prev_ema_15"] = df["ema_15"].shift(1)

        # Bullish: prev fast <= prev slow and curr fast > curr slow
        bullish = (df["prev_ema_9"] <= df["prev_ema_15"]) & (df["ema_9"] > df["ema_15"])
        # Bearish: prev fast >= prev slow and curr fast < curr slow
        bearish = (df["prev_ema_9"] >= df["prev_ema_15"]) & (df["ema_9"] < df["ema_15"])

        df["signal"] = 0
        df.loc[bullish, "signal"] = 1
        df.loc[bearish, "signal"] = -1
        return df


class BacktestEngine:
    """
    Simulates spot trading with:
    - Initial starting capital (e.g., $20)
    - Binance trading fee (e.g., 0.1% = 0.001)
    - Non-lookahead execution (signal evaluated at candle close, filled at next candle open)
    - Bar-by-bar mark-to-market equity curve tracking
    """

    def __init__(self, initial_capital: float = 20.0, fee_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate

    def run(self, df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
        capital = float(self.initial_capital)
        position_qty = 0.0
        in_position = False

        trades = []
        equity_curve = []
        entry_bar_idx = None
        entry_price = 0.0
        entry_time = None
        entry_fee = 0.0
        cost_basis = 0.0

        n = len(df)
        signals = df["signal"].values
        opens = df["open"].values
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        timestamps = df["timestamp"].values

        # Ensure we have enough bars
        warmup_bars = 20

        for i in range(n):
            curr_ts = timestamps[i]
            curr_open = opens[i]
            curr_close = closes[i]

            # Execute pending signal from previous bar at CURRENT bar OPEN
            if i >= warmup_bars:
                prev_signal = signals[i - 1]

                # BUY execution
                if prev_signal == 1 and not in_position:
                    entry_price = curr_open
                    entry_time = curr_ts
                    entry_bar_idx = i

                    # Available cash pays fee
                    entry_fee = capital * self.fee_rate
                    effective_capital = capital - entry_fee
                    position_qty = effective_capital / entry_price
                    cost_basis = capital
                    capital = 0.0
                    in_position = True

                # SELL execution
                elif prev_signal == -1 and in_position:
                    exit_price = curr_open
                    exit_time = curr_ts
                    gross_proceeds = position_qty * exit_price
                    exit_fee = gross_proceeds * self.fee_rate
                    net_proceeds = gross_proceeds - exit_fee
                    total_fees = entry_fee + exit_fee

                    net_pnl = net_proceeds - cost_basis
                    ret_pct = ((net_proceeds / cost_basis) - 1.0) * 100.0
                    duration_bars = i - entry_bar_idx

                    trades.append({
                        "trade_num": len(trades) + 1,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": exit_time,
                        "exit_price": exit_price,
                        "qty": position_qty,
                        "entry_fee": entry_fee,
                        "exit_fee": exit_fee,
                        "total_fees": total_fees,
                        "cost_basis": cost_basis,
                        "net_proceeds": net_proceeds,
                        "net_pnl": net_pnl,
                        "return_pct": ret_pct,
                        "duration_bars": duration_bars,
                        "exit_reason": "BEARISH_CROSS",
                        "status": "CLOSED"
                    })

                    capital = net_proceeds
                    position_qty = 0.0
                    in_position = False

            # Mark to market equity at the close of current candle
            if in_position:
                # Value of position if sold now at close price minus selling fee
                cur_gross = position_qty * curr_close
                cur_equity = cur_gross * (1.0 - self.fee_rate)
            else:
                cur_equity = capital

            equity_curve.append({
                "timestamp": curr_ts,
                "equity": cur_equity,
                "in_position": in_position,
                "close": curr_close
            })

        # If still in position at end of backtest, close out at final candle close
        if in_position:
            final_exit_price = closes[-1]
            final_ts = timestamps[-1]
            gross_proceeds = position_qty * final_exit_price
            exit_fee = gross_proceeds * self.fee_rate
            net_proceeds = gross_proceeds - exit_fee
            total_fees = entry_fee + exit_fee
            net_pnl = net_proceeds - cost_basis
            ret_pct = ((net_proceeds / cost_basis) - 1.0) * 100.0

            trades.append({
                "trade_num": len(trades) + 1,
                "symbol": symbol,
                "timeframe": timeframe,
                "entry_time": entry_time,
                "entry_price": entry_price,
                "exit_time": final_ts,
                "exit_price": final_exit_price,
                "qty": position_qty,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "total_fees": total_fees,
                "cost_basis": cost_basis,
                "net_proceeds": net_proceeds,
                "net_pnl": net_pnl,
                "return_pct": ret_pct,
                "duration_bars": n - 1 - entry_bar_idx,
                "exit_reason": "END_OF_TEST",
                "status": "CLOSED"
            })
            capital = net_proceeds
            equity_curve[-1]["equity"] = capital

        equity_df = pd.DataFrame(equity_curve)
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=[
            "trade_num", "symbol", "timeframe", "entry_time", "entry_price",
            "exit_time", "exit_price", "qty", "entry_fee", "exit_fee",
            "total_fees", "cost_basis", "net_proceeds", "net_pnl", "return_pct",
            "duration_bars", "exit_reason", "status"
        ])

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "initial_capital": self.initial_capital,
            "final_capital": capital,
            "trades_df": trades_df,
            "equity_df": equity_df,
            "candles_df": df
        }


class MetricsCalculator:
    """Calculates comprehensive performance metrics."""

    @staticmethod
    def calculate(result: dict) -> dict:
        initial_cap = result["initial_capital"]
        final_cap = result["final_capital"]
        trades_df = result["trades_df"]
        equity_df = result["equity_df"]
        candles_df = result["candles_df"]

        total_return_pct = ((final_cap - initial_cap) / initial_cap) * 100.0
        net_profit_usd = final_cap - initial_cap
        total_trades = len(trades_df)

        # Buy & Hold Return for benchmark
        first_close = candles_df["close"].iloc[0]
        last_close = candles_df["close"].iloc[-1]
        buy_and_hold_return_pct = ((last_close - first_close) / first_close) * 100.0

        if total_trades > 0:
            winning_trades = trades_df[trades_df["net_pnl"] > 0]
            losing_trades = trades_df[trades_df["net_pnl"] < 0]
            win_count = len(winning_trades)
            loss_count = len(losing_trades)
            win_rate_pct = (win_count / total_trades) * 100.0

            gross_profit = winning_trades["net_pnl"].sum()
            gross_loss = abs(losing_trades["net_pnl"].sum())

            if gross_loss > 0:
                profit_factor = gross_profit / gross_loss
            else:
                profit_factor = float("inf") if gross_profit > 0 else 0.0

            total_fees = trades_df["total_fees"].sum()
            avg_trade_pnl = trades_df["net_pnl"].mean()
            avg_trade_ret_pct = trades_df["return_pct"].mean()

            avg_win_pct = winning_trades["return_pct"].mean() if win_count > 0 else 0.0
            avg_loss_pct = losing_trades["return_pct"].mean() if loss_count > 0 else 0.0

            best_trade_pct = trades_df["return_pct"].max()
            worst_trade_pct = trades_df["return_pct"].min()
        else:
            win_count = 0
            loss_count = 0
            win_rate_pct = 0.0
            profit_factor = 0.0
            total_fees = 0.0
            avg_trade_pnl = 0.0
            avg_trade_ret_pct = 0.0
            avg_win_pct = 0.0
            avg_loss_pct = 0.0
            best_trade_pct = 0.0
            worst_trade_pct = 0.0

        # Bar-by-bar Max Drawdown calculation
        equity_series = equity_df["equity"]
        running_max = equity_series.cummax()
        drawdown_series = (running_max - equity_series) / running_max * 100.0
        max_drawdown_pct = float(drawdown_series.max()) if len(drawdown_series) > 0 else 0.0

        # Time in market %
        time_in_market_pct = (equity_df["in_position"].sum() / len(equity_df)) * 100.0 if len(equity_df) > 0 else 0.0

        # Date range
        start_date = candles_df["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M")
        end_date = candles_df["timestamp"].iloc[-1].strftime("%Y-%m-%d %H:%M")
        num_candles = len(candles_df)

        return {
            "symbol": result["symbol"],
            "timeframe": result["timeframe"],
            "start_date": start_date,
            "end_date": end_date,
            "num_candles": num_candles,
            "initial_capital": initial_cap,
            "final_capital": final_cap,
            "net_profit_usd": net_profit_usd,
            "total_return_pct": total_return_pct,
            "buy_and_hold_return_pct": buy_and_hold_return_pct,
            "outperformance_pct": total_return_pct - buy_and_hold_return_pct,
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": win_rate_pct,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "total_fees_usd": total_fees,
            "avg_trade_pnl_usd": avg_trade_pnl,
            "avg_trade_ret_pct": avg_trade_ret_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "best_trade_pct": best_trade_pct,
            "worst_trade_pct": worst_trade_pct,
            "time_in_market_pct": time_in_market_pct
        }


def run_full_backtest(pairs, timeframes, days, initial_capital, fee_rate, refresh=False, export_trades=False):
    loader = DataLoader()
    engine = BacktestEngine(initial_capital=initial_capital, fee_rate=fee_rate)

    results_summary = []
    detailed_results = {}

    print("=" * 80)
    print(" 🚀 STARTING 9/15 EMA MULTI-PAIR HISTORICAL BACKTEST")
    print(f" Pairs: {', '.join(pairs)}")
    print(f" Timeframes: {', '.join(timeframes)}")
    print(f" Lookback: {days} days | Initial Capital: ${initial_capital:.2f} | Fee Rate: {fee_rate*100:.2f}%")
    print("=" * 80)

    for symbol in pairs:
        for tf in timeframes:
            print(f"\n--- Processing {symbol} [{tf}] ---")
            try:
                raw_df = loader.fetch_historical_ohlcv(symbol, timeframe=tf, days=days, refresh=refresh)
                strat_df = Strategy.calculate_indicators(raw_df)
                strat_df = Strategy.generate_signals(strat_df)

                res = engine.run(strat_df, symbol=symbol, timeframe=tf)
                metrics = MetricsCalculator.calculate(res)
                results_summary.append(metrics)
                detailed_results[f"{symbol}_{tf}"] = (res, metrics)

                # Export trades if requested
                if export_trades and len(res["trades_df"]) > 0:
                    clean_sym = symbol.replace("/", "_")
                    export_path = os.path.join(RESULTS_DIR, f"trades_{clean_sym}_{tf}.csv")
                    res["trades_df"].to_csv(export_path, index=False)
                    print(f"  [Exported] Trade log saved to {export_path}")

                print(f"  Result: Return = {metrics['total_return_pct']:+.2f}% | "
                      f"Win Rate = {metrics['win_rate_pct']:.1f}% ({metrics['win_count']}/{metrics['total_trades']}) | "
                      f"Max DD = {metrics['max_drawdown_pct']:.2f}% | "
                      f"PF = {metrics['profit_factor']:.2f} | "
                      f"Final = ${metrics['final_capital']:.2f}")

            except Exception as e:
                print(f"  [Error] Failed backtest for {symbol} {tf}: {e}")
                import traceback
                traceback.print_exc()

    return results_summary, detailed_results


def print_summary_table(summary_list):
    df_summary = pd.DataFrame(summary_list)
    if df_summary.empty:
        print("No results to display.")
        return

    # Sort by total return descending
    df_summary = df_summary.sort_values(by="total_return_pct", ascending=False).reset_index(drop=True)

    print("\n" + "=" * 115)
    print(" 📊 9/15 EMA STRATEGY COMPREHENSIVE PERFORMANCE SUMMARY (SORTED BY RETURN)")
    print("=" * 115)

    header = (
        f"{'Rank':<5} | {'Pair':<10} | {'TF':<5} | {'Return %':<10} | {'Net PnL':<9} | "
        f"{'Final $':<9} | {'Win Rate':<10} | {'Trades':<7} | {'Max DD %':<9} | {'PF':<6} | "
        f"{'Fees $':<8} | {'B&H %':<9}"
    )
    print(header)
    print("-" * 115)

    for idx, row in df_summary.iterrows():
        pf_str = f"{row['profit_factor']:.2f}" if row['profit_factor'] != float("inf") else "inf"
        print(
            f"#{idx+1:<4} | "
            f"{row['symbol']:<10} | "
            f"{row['timeframe']:<5} | "
            f"{row['total_return_pct']:>+9.2f}% | "
            f"${row['net_profit_usd']:>+7.2f} | "
            f"${row['final_capital']:>7.2f} | "
            f"{row['win_rate_pct']:>8.1f}% | "
            f"{row['total_trades']:>6} | "
            f"{row['max_drawdown_pct']:>8.2f}% | "
            f"{pf_str:>6} | "
            f"${row['total_fees_usd']:>6.2f} | "
            f"{row['buy_and_hold_return_pct']:>+8.2f}%"
        )
    print("=" * 115)

    # Breakdown by timeframe
    print("\n 📈 AVERAGE METRICS BY TIMEFRAME:")
    tf_group = df_summary.groupby("timeframe").agg({
        "total_return_pct": "mean",
        "win_rate_pct": "mean",
        "max_drawdown_pct": "mean",
        "total_trades": "mean",
        "total_fees_usd": "mean"
    }).loc[["5m", "15m", "1h"]]
    for tf, row in tf_group.iterrows():
        print(f"  • {tf:<4}: Avg Return = {row['total_return_pct']:>+6.2f}% | Avg Win Rate = {row['win_rate_pct']:>5.1f}% | Avg DD = {row['max_drawdown_pct']:>5.2f}% | Avg Trades = {row['total_trades']:>4.0f} | Avg Fees = ${row['total_fees_usd']:.2f}")

    # Breakdown by pair
    print("\n 🪙 AVERAGE METRICS BY PAIR:")
    pair_group = df_summary.groupby("symbol").agg({
        "total_return_pct": "mean",
        "win_rate_pct": "mean",
        "max_drawdown_pct": "mean",
        "total_trades": "mean",
        "total_fees_usd": "mean"
    })
    for pair, row in pair_group.iterrows():
        print(f"  • {pair:<10}: Avg Return = {row['total_return_pct']:>+6.2f}% | Avg Win Rate = {row['win_rate_pct']:>5.1f}% | Avg DD = {row['max_drawdown_pct']:>5.2f}% | Avg Trades = {row['total_trades']:>4.0f} | Avg Fees = ${row['total_fees_usd']:.2f}")

    best = df_summary.iloc[0]
    worst = df_summary.iloc[-1]
    print("\n 🏆 TOP PERFORMER:")
    print(f"  {best['symbol']} on {best['timeframe']}: Return {best['total_return_pct']:+.2f}% | Win Rate {best['win_rate_pct']:.1f}% | Max DD {best['max_drawdown_pct']:.2f}% | Profit Factor {best['profit_factor']:.2f}")

    print("\n ⚠️ WORST PERFORMER:")
    print(f"  {worst['symbol']} on {worst['timeframe']}: Return {worst['total_return_pct']:+.2f}% | Win Rate {worst['win_rate_pct']:.1f}% | Max DD {worst['max_drawdown_pct']:.2f}% | Profit Factor {worst['profit_factor']:.2f}")
    print("=" * 115)


def parse_args():
    parser = argparse.ArgumentParser(description="9/15 EMA Crossover Strategy Historical Backtesting Engine")
    parser.add_argument("--pairs", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT", help="Comma-separated list of symbols")
    parser.add_argument("--timeframes", type=str, default="5m,15m,1h", help="Comma-separated list of timeframes")
    parser.add_argument("--days", type=int, default=60, help="Number of lookback days (default: 60)")
    parser.add_argument("--capital", type=float, default=20.0, help="Starting capital in USD (default: 20.0)")
    parser.add_argument("--fee", type=float, default=0.001, help="Trading fee rate (default: 0.001 for 0.1%%)")
    parser.add_argument("--refresh", action="store_true", help="Force refresh data cache from Binance API")
    parser.add_argument("--export-trades", action="store_true", default=True, help="Export trade logs to CSV")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    pairs_list = [p.strip() for p in args.pairs.split(",") if p.strip()]
    timeframes_list = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    summary, detailed = run_full_backtest(
        pairs=pairs_list,
        timeframes=timeframes_list,
        days=args.days,
        initial_capital=args.capital,
        fee_rate=args.fee,
        refresh=args.refresh,
        export_trades=args.export_trades
    )

    print_summary_table(summary)

    # Save summary table to CSV
    summary_csv_path = os.path.join(RESULTS_DIR, f"summary_{args.days}d.csv")
    pd.DataFrame(summary).to_csv(summary_csv_path, index=False)
    print(f"\n[Done] Summary results saved to {summary_csv_path}\n")
