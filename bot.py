import os
import time
import logging
from datetime import datetime
import pandas as pd
import ccxt
from dotenv import load_dotenv

import state_manager
from rule_verifier import TradingRules
from risk_manager import (
    RiskConfig,
    RiskManager,
    compute_all_risk_indicators,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", mode="a")
    ]
)
logger = logging.getLogger("EMA_Bot")

# Load configuration
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "15.0"))
TESTNET = os.getenv("TESTNET", "True").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

def init_exchange():
    """Initializes Binance connection using ccxt."""
    exchange_params = {
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
    }
    exchange = ccxt.binance(exchange_params)
    if TESTNET:
        exchange.set_sandbox_mode(True)
        logger.info("Operating in Binance TESTNET sandbox mode.")
    return exchange

def fetch_candles(exchange, symbol, timeframe, limit=50):
    """Fetches recent OHLCV candle data."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        logger.error(f"Error fetching candles: {e}")
        return None

def fetch_current_price(exchange, symbol, fallback_df=None):
    """Fetches real-time price from ticker with fallback to latest candle close."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        if ticker and "last" in ticker and ticker["last"] is not None:
            return float(ticker["last"])
    except Exception as e:
        logger.debug(f"Ticker fetch failed ({e}); falling back to candle close price.")

    if fallback_df is not None and not fallback_df.empty:
        return float(fallback_df["close"].iloc[-1])
    return None

def compute_indicators(df):
    """Calculates EMA 9, EMA 15, and risk indicators (ATR, Vol SMA, EMA Spread)."""
    return compute_all_risk_indicators(df)

def check_crossover_signal(df):
    """
    Checks for EMA 9 and EMA 15 crossover on closed candles.
    Returns: 'BUY', 'SELL', or None
    """
    if len(df) < 16:
        return None

    # Using the last completed candle (index -2) and candle prior to it (index -3)
    prev_fast = df["ema_9"].iloc[-3]
    prev_slow = df["ema_15"].iloc[-3]
    curr_fast = df["ema_9"].iloc[-2]
    curr_slow = df["ema_15"].iloc[-2]

    # Bullish cross: EMA 9 crosses above EMA 15
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "BUY"
    # Bearish cross: EMA 9 crosses below EMA 15
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return "SELL"

    return None

class BotState:
    def __init__(self, risk_manager: RiskManager = None):
        self.risk_manager = risk_manager or RiskManager()
        self.in_position = False
        self.entry_price = 0.0
        self.bought_qty = 0.0

def execute_trade(exchange, action, symbol, trade_amount_usdt, state, reason="SIGNAL", exit_price=None):
    """Executes order on Binance or simulates if DRY_RUN is enabled."""
    last_price = exit_price or fetch_current_price(exchange, symbol)
    if not last_price:
        logger.error(f"Cannot execute {action}: unable to determine market price.")
        return

    if action == "BUY" and not state.in_position:
        qty = round(trade_amount_usdt / last_price, 6)
        logger.info(f"Signal BUY [{reason}] at price: ${last_price:.2f} | Target qty: {qty}")
        if DRY_RUN:
            logger.info(f"[DRY_RUN] Simulated BUY order for {qty} {symbol} at ${last_price:.2f}")
            state.in_position = True
            state.entry_price = last_price
            state.bought_qty = qty
            state.risk_manager.open_position(last_price, qty)
        else:
            try:
                order = exchange.create_market_buy_order(symbol, qty)
                logger.info(f"BUY order executed: {order}")
                state.in_position = True
                state.entry_price = last_price
                state.bought_qty = qty
                state.risk_manager.open_position(last_price, qty)
            except Exception as e:
                logger.error(f"Failed to execute BUY order: {e}")
                return

        try:
            st_dict = state_manager.load_state()
            state_manager.record_trade_execution(st_dict, "BUY", last_price, qty, symbol, DRY_RUN)
            state_manager.save_state(st_dict)
        except Exception as e:
            logger.debug(f"State save failed on BUY: {e}")

    elif action == "SELL" and state.in_position:
        qty = state.bought_qty
        pnl = (last_price - state.entry_price) * qty
        pct = ((last_price / state.entry_price) - 1.0) * 100.0
        logger.info(f"Signal SELL [{reason}] at price: ${last_price:.2f} | Selling qty: {qty}")
        if DRY_RUN:
            logger.info(
                f"[DRY_RUN] Simulated SELL order at ${last_price:.2f}. "
                f"Realized PnL: ${pnl:+.2f} ({pct:+.2f}%) | Exit Reason: {reason}"
            )
            state.risk_manager.close_position(last_price)
            state.in_position = False
            state.entry_price = 0.0
            state.bought_qty = 0.0
        else:
            try:
                order = exchange.create_market_sell_order(symbol, qty)
                logger.info(f"SELL order executed: {order} | Realized PnL: ${pnl:+.2f} ({pct:+.2f}%)")
                state.risk_manager.close_position(last_price)
                state.in_position = False
                state.entry_price = 0.0
                state.bought_qty = 0.0
            except Exception as e:
                logger.error(f"Failed to execute SELL order: {e}")
                return

        try:
            st_dict = state_manager.load_state()
            state_manager.record_trade_execution(st_dict, "SELL", last_price, qty, symbol, DRY_RUN, pnl=pnl, pnl_pct=pct)
            state_manager.save_state(st_dict)
        except Exception as e:
            logger.debug(f"State save failed on SELL: {e}")

def run_loop():
    logger.info("Initializing 9/15 EMA Binance Bot with Automated Risk Management...")
    logger.info(f"Symbol: {SYMBOL} | Timeframe: {TIMEFRAME} | Trade Amount: ${TRADE_AMOUNT_USDT}")
    logger.info(f"Dry Run Mode: {DRY_RUN} | Testnet: {TESTNET}")

    risk_config = RiskConfig.from_env()
    risk_manager = RiskManager(risk_config)
    state = BotState(risk_manager=risk_manager)

    logger.info("🛡️ Automated Risk Protections Active:")
    logger.info(f"   • Fixed Stop-Loss: -{risk_config.stop_loss_pct * 100:.1f}%")
    logger.info(f"   • Take-Profit Target: +{risk_config.take_profit_pct * 100:.1f}%")
    logger.info(
        f"   • Dynamic Trailing Stop: {'Enabled' if risk_config.trailing_stop_enabled else 'Disabled'} "
        f"(Arms at +{risk_config.trailing_stop_activation_pct * 100:.1f}%, Trails {risk_config.trailing_stop_callback_pct * 100:.1f}% from peak)"
    )
    logger.info(f"   • Max Daily Loss Circuit Breaker: ${risk_config.max_daily_loss_usdt:.2f}")
    logger.info(f"   • Market Volatility Filter: Min ATR {risk_config.min_atr_pct * 100:.2f}%")
    logger.info(f"   • Volume Filter: Min {risk_config.min_volume_ratio * 100:.0f}% of 20-period Volume SMA")
    logger.info(f"   • Minimum Notional: ${risk_config.min_notional_usdt:.2f}")

    exchange = init_exchange()
    sleep_seconds = 15  # check every 15s
    rules_engine = TradingRules()

    logger.info("Bot started successfully. Waiting for candle signals and monitoring positions...")
    while True:
        try:
            # 0. STRICT RULES VERIFICATION ON EVERY CYCLE
            is_allowed, rule_msg = rules_engine.validate_pre_flight(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                trade_amount=TRADE_AMOUNT_USDT,
                dry_run=DRY_RUN
            )
            if not is_allowed:
                logger.critical(f"🛑 [SAFETY HALT] {rule_msg}. Trading is paused until rules in trading_rules.txt are met.")
                time.sleep(sleep_seconds)
                continue
            df = fetch_candles(exchange, SYMBOL, TIMEFRAME, limit=50)
            if df is not None and len(df) >= 20:
                df = compute_indicators(df)
                current_price = fetch_current_price(exchange, SYMBOL, fallback_df=df)

                # Sync market data to shared state for live dashboard
                try:
                    st_dict = state_manager.load_state()
                    st_dict["status"] = "ACTIVE"
                    st_dict["symbol"] = SYMBOL
                    st_dict["timeframe"] = TIMEFRAME
                    st_dict = state_manager.update_market_candles(st_dict, df)
                    state_manager.save_state(st_dict)
                except Exception as e:
                    logger.debug(f"State candle update failed: {e}")

                # 1. Real-time Risk Exit Monitoring (Fixed SL / Trailing Stop / TP)
                if state.in_position and current_price is not None:
                    should_exit, exit_reason, exit_details = state.risk_manager.check_exit_conditions(current_price)
                    if should_exit:
                        logger.warning(
                            f"🚨 [RISK EXIT TRIGGERED: {exit_reason}] Price: ${current_price:.2f} | "
                            f"Details: {exit_details}"
                        )
                        execute_trade(
                            exchange=exchange,
                            action="SELL",
                            symbol=SYMBOL,
                            trade_amount_usdt=TRADE_AMOUNT_USDT,
                            state=state,
                            reason=exit_reason,
                            exit_price=current_price
                        )
                        time.sleep(sleep_seconds)
                        continue

                # 2. Check strategy crossover signal on closed candles
                signal = check_crossover_signal(df)

                latest_close = df["close"].iloc[-1]
                latest_ema9 = df["ema_9"].iloc[-1]
                latest_ema15 = df["ema_15"].iloc[-1]
                latest_atr_pct = df["atr_pct"].iloc[-1] * 100.0

                logger.debug(
                    f"Price: {latest_close:.2f} | EMA9: {latest_ema9:.2f} | EMA15: {latest_ema15:.2f} | "
                    f"ATR%: {latest_atr_pct:.2f}% | Signal: {signal}"
                )

                # 3. Handle Signals
                if signal == "BUY" and not state.in_position:
                    can_enter, filter_reason = state.risk_manager.evaluate_entry_filters(df, TRADE_AMOUNT_USDT)
                    if can_enter:
                        execute_trade(
                            exchange=exchange,
                            action="BUY",
                            symbol=SYMBOL,
                            trade_amount_usdt=TRADE_AMOUNT_USDT,
                            state=state,
                            reason="EMA_BULLISH_CROSS",
                            exit_price=current_price
                        )
                    else:
                        logger.info(f"✋ [ENTRY BLOCKED] BUY crossover signal rejected by risk filter: {filter_reason}")

                elif signal == "SELL" and state.in_position:
                    logger.info("📉 EMA Bearish Cross detected. Executing technical exit.")
                    execute_trade(
                        exchange=exchange,
                        action="SELL",
                        symbol=SYMBOL,
                        trade_amount_usdt=TRADE_AMOUNT_USDT,
                        state=state,
                        reason="EMA_BEARISH_CROSS",
                        exit_price=current_price
                    )

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        time.sleep(sleep_seconds)

if __name__ == "__main__":
    run_loop()
