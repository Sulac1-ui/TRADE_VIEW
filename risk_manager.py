"""
Risk Management Module for Crypto Trading Bots.

Specifically engineered to protect small balance accounts (e.g. $20 USDT on Binance),
where minimum order notionals, exchange fee erosion, and sudden dumps pose severe risk.

Key Protections:
1. Fixed Stop-Loss: Immediate exit if loss reaches threshold (e.g. 1.5% - 2.0%).
2. Take-Profit & Trailing Stop: Lock in gains (e.g. 3.0% - 5.0%) and dynamically trail high-water mark.
3. Daily Loss Circuit Breaker: Halts new entries once maximum daily loss is reached (e.g. $1.00).
4. Market Regime Filters:
   - Minimum Volume Filter: Rejects entries when volume < ratio * 20-period Volume SMA.
   - Minimum Volatility (ATR) Filter: Rejects entries in flat/dead sideways markets where fees eat capital.
   - EMA Spread Filter: Avoids micro-crossovers of flat parallel moving averages.
5. Binance Minimum Notional Protection: Ensures orders satisfy the ~$5.00 exchange minimum.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any
import pandas as pd

logger = logging.getLogger("RiskManager")


@dataclass
class RiskConfig:
    """Configurable risk parameters with safety defaults for a $20 balance."""
    stop_loss_pct: float = 0.015               # 1.5% fixed stop loss
    take_profit_pct: float = 0.035             # 3.5% take profit target
    trailing_stop_enabled: bool = True        # Enable trailing stop
    trailing_stop_activation_pct: float = 0.015 # Minimum profit before trailing stop activates (+1.5%)
    trailing_stop_callback_pct: float = 0.010  # Trail 1.0% below the peak high-water mark
    max_daily_loss_usdt: float = 1.00          # Circuit breaker: $1.00 max daily loss (5% of $20 account)
    min_volume_ratio: float = 0.80              # Candle volume must be >= 80% of 20-period Volume SMA
    min_atr_pct: float = 0.0020                # Minimum ATR(14) as % of price (0.20% minimum volatility)
    min_ema_spread_pct: float = 0.0005         # Minimum spread between EMA9 and EMA15 (0.05%)
    min_notional_usdt: float = 5.00            # Binance minimum order size threshold

    @classmethod
    def from_env(cls) -> "RiskConfig":
        """Load configuration from environment variables with safe defaults."""
        def get_float(name: str, default: float) -> float:
            val = os.getenv(name)
            if val is None or val.strip() == "":
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(f"Invalid float for {name}: {val!r}. Using default: {default}")
                return default

        def get_bool(name: str, default: bool) -> bool:
            val = os.getenv(name)
            if val is None or val.strip() == "":
                return default
            return val.lower() in ("true", "1", "yes")

        return cls(
            stop_loss_pct=get_float("STOP_LOSS_PCT", 0.015),
            take_profit_pct=get_float("TAKE_PROFIT_PCT", 0.035),
            trailing_stop_enabled=get_bool("TRAILING_STOP_ENABLED", True),
            trailing_stop_activation_pct=get_float("TRAILING_STOP_ACTIVATION_PCT", 0.015),
            trailing_stop_callback_pct=get_float("TRAILING_STOP_CALLBACK_PCT", 0.010),
            max_daily_loss_usdt=get_float("MAX_DAILY_LOSS_USDT", 1.00),
            min_volume_ratio=get_float("MIN_VOLUME_RATIO", 0.80),
            min_atr_pct=get_float("MIN_ATR_PCT", 0.0020),
            min_ema_spread_pct=get_float("MIN_EMA_SPREAD_PCT", 0.0005),
            min_notional_usdt=get_float("MIN_NOTIONAL_USDT", 5.00),
        )


class PositionRiskState:
    """Tracks position pricing, high-water mark, and trailing stop state."""

    def __init__(self, entry_price: float, quantity: float, entry_time: Optional[datetime] = None):
        self.entry_price: float = float(entry_price)
        self.quantity: float = float(quantity)
        self.entry_time: datetime = entry_time or datetime.now()
        self.peak_price: float = float(entry_price)
        self.lowest_price: float = float(entry_price)
        self.trailing_armed: bool = False

    def update_price(self, current_price: float, trailing_activation_pct: float) -> None:
        """Updates the high-water mark and checks trailing stop activation."""
        if current_price > self.peak_price:
            self.peak_price = current_price
        if current_price < self.lowest_price:
            self.lowest_price = current_price

        # Arm trailing stop if price has reached or exceeded activation gain
        if not self.trailing_armed and self.entry_price > 0:
            gain_pct = (self.peak_price - self.entry_price) / self.entry_price
            if gain_pct >= trailing_activation_pct:
                self.trailing_armed = True
                logger.info(
                    f"🎯 Trailing Stop ARMED at peak ${self.peak_price:.2f} "
                    f"(+{gain_pct * 100:.2f}% gain from entry ${self.entry_price:.2f})"
                )

    def unrealized_pnl(self, current_price: float) -> float:
        """Returns unrealized dollar PnL."""
        return (current_price - self.entry_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Returns unrealized percentage PnL."""
        if self.entry_price <= 0:
            return 0.0
        return ((current_price / self.entry_price) - 1.0) * 100.0


class DailyPnLTracker:
    """Tracks daily realized losses and enforces circuit breaker protection."""

    def __init__(self, current_date: Optional[date] = None):
        self.current_date: date = current_date or datetime.now().date()
        self.realized_pnl: float = 0.0
        self.realized_losses: float = 0.0  # Cumulative negative PnL (as positive dollar amount)
        self.trades_count: int = 0
        self.win_count: int = 0
        self.loss_count: int = 0
        self.circuit_breaker_triggered: bool = False

    def check_day_rollover(self, current_time: Optional[datetime] = None) -> None:
        """Resets daily accumulators when date rolls over."""
        now_date = (current_time or datetime.now()).date()
        if now_date > self.current_date:
            logger.info(f"🔄 Day rollover detected: {self.current_date} -> {now_date}. Resetting daily PnL tracker.")
            self.current_date = now_date
            self.realized_pnl = 0.0
            self.realized_losses = 0.0
            self.trades_count = 0
            self.win_count = 0
            self.loss_count = 0
            self.circuit_breaker_triggered = False

    def record_trade(self, pnl: float, timestamp: Optional[datetime] = None, max_daily_loss: float = 1.00) -> bool:
        """
        Records a closed trade's PnL.
        Returns True if circuit breaker has just been triggered.
        """
        self.check_day_rollover(timestamp)
        self.trades_count += 1
        self.realized_pnl += pnl

        if pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
            self.realized_losses += abs(pnl)

        if self.realized_losses >= max_daily_loss:
            if not self.circuit_breaker_triggered:
                self.circuit_breaker_triggered = True
                logger.error(
                    f"⛔ CIRCUIT BREAKER TRIGGERED! Cumulative daily loss of ${self.realized_losses:.2f} "
                    f"exceeds max limit of ${max_daily_loss:.2f}. New entries halted for {self.current_date}."
                )
            return True

        return False

    def is_circuit_breaker_active(self, max_daily_loss: float, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """Checks if trading is blocked by the circuit breaker."""
        self.check_day_rollover(current_time)
        if self.circuit_breaker_triggered or self.realized_losses >= max_daily_loss:
            return True, (
                f"Circuit breaker active: Daily loss ${self.realized_losses:.2f} "
                f"exceeded maximum limit of ${max_daily_loss:.2f}"
            )
        return False, ""

    def reset(self, reset_date: Optional[date] = None) -> None:
        """Resets the circuit breaker manually."""
        self.current_date = reset_date or datetime.now().date()
        self.realized_pnl = 0.0
        self.realized_losses = 0.0
        self.trades_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.circuit_breaker_triggered = False


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range (ATR) using standard exponential smoothing."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def calculate_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculates rolling simple moving average of volume."""
    return df["volume"].rolling(window=period, min_periods=1).mean()


def compute_all_risk_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Computes EMA 9, EMA 15, ATR 14, Volume SMA 20, and spreads on DataFrame."""
    df = df.copy()
    if "ema_9" not in df.columns:
        df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    if "ema_15" not in df.columns:
        df["ema_15"] = df["close"].ewm(span=15, adjust=False).mean()

    df["atr_14"] = calculate_atr(df, period=14)
    # ATR as a percentage of close price
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["vol_sma_20"] = calculate_volume_sma(df, period=20)
    df["ema_spread_pct"] = (df["ema_9"] - df["ema_15"]).abs() / df["ema_15"]
    return df


class RiskManager:
    """
    Central Risk Management engine.
    Controls entry approvals, exit thresholds (SL/TP/Trailing), and daily loss bounds.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config: RiskConfig = config or RiskConfig.from_env()
        self.position: Optional[PositionRiskState] = None
        self.daily_tracker: DailyPnLTracker = DailyPnLTracker()

    @property
    def is_in_position(self) -> bool:
        return self.position is not None

    def open_position(self, entry_price: float, quantity: float, timestamp: Optional[datetime] = None) -> None:
        """Opens a tracked position."""
        self.position = PositionRiskState(entry_price=entry_price, quantity=quantity, entry_time=timestamp)
        logger.info(
            f"🛡️ RiskManager: Position opened. Entry: ${entry_price:.2f} | Qty: {quantity} | "
            f"Stop-Loss: ${entry_price * (1 - self.config.stop_loss_pct):.2f} (-{self.config.stop_loss_pct*100:.1f}%) | "
            f"Take-Profit: ${entry_price * (1 + self.config.take_profit_pct):.2f} (+{self.config.take_profit_pct*100:.1f}%)"
        )

    def close_position(self, exit_price: float, timestamp: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Closes current position, logs PnL, and updates daily loss tracker.
        Returns a dictionary summarizing the trade.
        """
        if not self.position:
            logger.warning("Attempted to close position in RiskManager, but no position was active.")
            return {}

        pnl = self.position.unrealized_pnl(exit_price)
        pnl_pct = self.position.unrealized_pnl_pct(exit_price)
        entry_price = self.position.entry_price
        quantity = self.position.quantity
        peak_price = self.position.peak_price
        trailing_armed = self.position.trailing_armed

        # Update daily tracker
        circuit_tripped = self.daily_tracker.record_trade(
            pnl=pnl,
            timestamp=timestamp,
            max_daily_loss=self.config.max_daily_loss_usdt
        )

        summary = {
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl_usdt": pnl,
            "pnl_pct": pnl_pct,
            "peak_price": peak_price,
            "trailing_armed": trailing_armed,
            "daily_realized_loss": self.daily_tracker.realized_losses,
            "circuit_breaker_tripped": circuit_tripped,
        }

        self.position = None
        logger.info(
            f"🛡️ RiskManager: Position closed. Exit: ${exit_price:.2f} | "
            f"PnL: ${pnl:.2f} ({pnl_pct:+.2f}%) | Daily Realized Loss: ${self.daily_tracker.realized_losses:.2f}"
        )
        return summary

    def check_exit_conditions(self, current_price: float) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Evaluates active position against Fixed Stop-Loss, Trailing Stop, and Take-Profit.
        Returns: (should_exit, reason, details)
        """
        if not self.position:
            return False, None, {}

        # 1. Update high-water mark and arming status
        self.position.update_price(current_price, self.config.trailing_stop_activation_pct)

        entry = self.position.entry_price
        peak = self.position.peak_price

        # Calculate current return from entry
        return_pct = (current_price - entry) / entry

        # --- 2. Check Fixed Stop-Loss ---
        if return_pct <= -self.config.stop_loss_pct:
            details = {
                "exit_type": "STOP_LOSS",
                "entry_price": entry,
                "current_price": current_price,
                "loss_pct": return_pct * 100.0,
                "threshold_pct": self.config.stop_loss_pct * 100.0,
                "stop_price": entry * (1.0 - self.config.stop_loss_pct),
            }
            return True, "STOP_LOSS", details

        # --- 3. Check Trailing Stop ---
        if self.config.trailing_stop_enabled and self.position.trailing_armed:
            trailing_stop_price = peak * (1.0 - self.config.trailing_stop_callback_pct)
            if current_price <= trailing_stop_price:
                drawdown_from_peak = (peak - current_price) / peak
                details = {
                    "exit_type": "TRAILING_STOP",
                    "entry_price": entry,
                    "peak_price": peak,
                    "current_price": current_price,
                    "trailing_stop_price": trailing_stop_price,
                    "drawdown_pct": drawdown_from_peak * 100.0,
                    "locked_in_profit_pct": return_pct * 100.0,
                }
                return True, "TRAILING_STOP", details

        # --- 4. Check Fixed Take-Profit ---
        if return_pct >= self.config.take_profit_pct:
            details = {
                "exit_type": "TAKE_PROFIT",
                "entry_price": entry,
                "current_price": current_price,
                "gain_pct": return_pct * 100.0,
                "threshold_pct": self.config.take_profit_pct * 100.0,
                "target_price": entry * (1.0 + self.config.take_profit_pct),
            }
            return True, "TAKE_PROFIT", details

        return False, None, {}

    def evaluate_entry_filters(
        self,
        df: pd.DataFrame,
        trade_amount_usdt: float,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Validates all pre-trade safety filters before allowing a BUY order.
        Returns: (can_enter, reason)
        """
        # 1. Circuit Breaker Check
        cb_active, cb_reason = self.daily_tracker.is_circuit_breaker_active(
            self.config.max_daily_loss_usdt,
            current_time=current_time
        )
        if cb_active:
            return False, cb_reason

        # 2. Binance Minimum Notional Check ($5.00 min)
        if trade_amount_usdt < self.config.min_notional_usdt:
            return False, (
                f"Trade amount ${trade_amount_usdt:.2f} is below Binance "
                f"minimum notional requirement of ${self.config.min_notional_usdt:.2f}"
            )

        # 3. Candle history sufficiency
        if len(df) < 20:
            return False, f"Insufficient candle data: {len(df)} candles found, 20 required for risk indicators"

        # Ensure indicators are computed
        if "atr_pct" not in df.columns or "vol_sma_20" not in df.columns or "ema_spread_pct" not in df.columns:
            df = compute_all_risk_indicators(df)

        # Inspect the last completed candle (index -2) or latest candle if len == 20
        candle_idx = -2 if len(df) > 2 else -1

        # 4. ATR Volatility Filter (Blocks sideways chop)
        atr_pct = float(df["atr_pct"].iloc[candle_idx])
        if pd.isna(atr_pct) or atr_pct < self.config.min_atr_pct:
            return False, (
                f"Volatility too low: ATR is {atr_pct * 100:.3f}%, "
                f"below minimum threshold of {self.config.min_atr_pct * 100:.3f}%. (Flat choppy market)"
            )

        # 5. Volume Filter (Blocks entries on illiquid / ghost volume)
        candle_vol = float(df["volume"].iloc[candle_idx])
        vol_sma = float(df["vol_sma_20"].iloc[candle_idx])
        if vol_sma > 0:
            vol_ratio = candle_vol / vol_sma
            if vol_ratio < self.config.min_volume_ratio:
                return False, (
                    f"Volume too low: Candle volume {candle_vol:.2f} is {vol_ratio * 100:.1f}% "
                    f"of 20-period SMA ({vol_sma:.2f}), below required {self.config.min_volume_ratio * 100:.0f}%"
                )

        # 6. EMA Spread Filter (Avoids micro-crossovers of flat lines)
        ema_spread = float(df["ema_spread_pct"].iloc[candle_idx])
        if pd.isna(ema_spread) or ema_spread < self.config.min_ema_spread_pct:
            return False, (
                f"EMA spread too narrow: {ema_spread * 100:.4f}% separation, "
                f"below minimum {self.config.min_ema_spread_pct * 100:.4f}% filter (indecisive trend)"
            )

        return True, "All risk filters passed"

    def get_status_summary(self, current_price: Optional[float] = None) -> Dict[str, Any]:
        """Provides full snapshot of active risk metrics for logging and UI/status."""
        summary: Dict[str, Any] = {
            "in_position": self.is_in_position,
            "daily_realized_loss": self.daily_tracker.realized_losses,
            "daily_realized_pnl": self.daily_tracker.realized_pnl,
            "max_daily_loss_limit": self.config.max_daily_loss_usdt,
            "circuit_breaker_active": self.daily_tracker.circuit_breaker_triggered,
            "trades_count_today": self.daily_tracker.trades_count,
            "win_count": self.daily_tracker.win_count,
            "loss_count": self.daily_tracker.loss_count,
        }

        if self.position and current_price is not None:
            self.position.update_price(current_price, self.config.trailing_stop_activation_pct)
            summary["entry_price"] = self.position.entry_price
            summary["peak_price"] = self.position.peak_price
            summary["unrealized_pnl_usdt"] = self.position.unrealized_pnl(current_price)
            summary["unrealized_pnl_pct"] = self.position.unrealized_pnl_pct(current_price)
            summary["trailing_armed"] = self.position.trailing_armed
            summary["stop_loss_price"] = self.position.entry_price * (1.0 - self.config.stop_loss_pct)
            summary["take_profit_price"] = self.position.entry_price * (1.0 + self.config.take_profit_pct)
            if self.position.trailing_armed:
                summary["trailing_stop_price"] = self.position.peak_price * (1.0 - self.config.trailing_stop_callback_pct)

        return summary
