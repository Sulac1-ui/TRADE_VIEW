"""
Comprehensive Unit Tests for Risk Management & Trailing Stop / Take Profit system.
"""

import unittest
from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np

from risk_manager import (
    RiskConfig,
    PositionRiskState,
    DailyPnLTracker,
    RiskManager,
    calculate_atr,
    calculate_volume_sma,
    compute_all_risk_indicators,
)


class TestRiskProtections(unittest.TestCase):
    def setUp(self):
        """Set up standard configuration for a $20 account test suite."""
        self.config = RiskConfig(
            stop_loss_pct=0.015,                # 1.5% fixed stop loss
            take_profit_pct=0.035,              # 3.5% take profit
            trailing_stop_enabled=True,         # Enable trailing stop
            trailing_stop_activation_pct=0.015, # Arms at +1.5%
            trailing_stop_callback_pct=0.010,   # Trails 1.0% below peak
            max_daily_loss_usdt=1.00,           # $1.00 max daily loss (5% of $20 account)
            min_volume_ratio=0.80,              # 80% of 20-SMA volume
            min_atr_pct=0.0020,                 # 0.20% minimum ATR volatility
            min_ema_spread_pct=0.0005,          # 0.05% minimum EMA spread
            min_notional_usdt=5.00,             # $5.00 minimum notional
        )
        self.rm = RiskManager(self.config)

    # --------------------------------------------------------------------------
    # 1. FIXED STOP-LOSS TESTS
    # --------------------------------------------------------------------------
    def test_fixed_stop_loss_triggers_at_threshold(self):
        """Verify Fixed Stop-Loss triggers when price drops by stop_loss_pct (1.5%)."""
        entry_price = 100.0
        qty = 0.15  # $15 trade
        self.rm.open_position(entry_price=entry_price, quantity=qty)

        # Drop 1.0% to 99.0 -> Stop loss should NOT trigger
        should_exit, reason, _ = self.rm.check_exit_conditions(99.0)
        self.assertFalse(should_exit)

        # Drop exactly 1.5% to 98.5 -> Stop loss triggers
        should_exit, reason, details = self.rm.check_exit_conditions(98.5)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "STOP_LOSS")
        self.assertAlmostEqual(details["loss_pct"], -1.5, places=2)
        self.assertAlmostEqual(details["stop_price"], 98.5, places=2)

    def test_fixed_stop_loss_triggers_on_gap_dump(self):
        """Verify Stop-Loss triggers even on large sudden market dumps (e.g. flash crash)."""
        entry_price = 60000.0
        self.rm.open_position(entry_price=entry_price, quantity=0.00025)

        # Sudden dump by 5.0% to 57000.0
        should_exit, reason, details = self.rm.check_exit_conditions(57000.0)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "STOP_LOSS")
        self.assertAlmostEqual(details["loss_pct"], -5.0, places=2)

    # --------------------------------------------------------------------------
    # 2. FIXED TAKE-PROFIT TESTS
    # --------------------------------------------------------------------------
    def test_fixed_take_profit_triggers_at_target(self):
        """Verify Take-Profit triggers when target percentage is met."""
        # Disable trailing stop to isolate fixed Take-Profit
        self.config.trailing_stop_enabled = False
        rm = RiskManager(self.config)

        entry_price = 100.0
        rm.open_position(entry_price=entry_price, quantity=0.15)

        # Rise 2.0% to 102.0 -> TP should NOT trigger
        should_exit, _, _ = rm.check_exit_conditions(102.0)
        self.assertFalse(should_exit)

        # Rise to 103.5 (+3.5%) -> TP triggers
        should_exit, reason, details = rm.check_exit_conditions(103.5)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "TAKE_PROFIT")
        self.assertAlmostEqual(details["gain_pct"], 3.5, places=2)
        self.assertAlmostEqual(details["target_price"], 103.5, places=2)

    # --------------------------------------------------------------------------
    # 3. DYNAMIC TRAILING STOP TESTS
    # --------------------------------------------------------------------------
    def test_trailing_stop_not_armed_below_activation(self):
        """Verify trailing stop does not arm until price reaches trailing_stop_activation_pct."""
        entry_price = 100.0
        self.rm.open_position(entry_price=entry_price, quantity=0.15)

        # Price rises to 101.0 (+1.0%, below 1.5% activation)
        should_exit, _, _ = self.rm.check_exit_conditions(101.0)
        self.assertFalse(should_exit)
        self.assertFalse(self.rm.position.trailing_armed)

        # Price pulls back to 99.5 (-0.5%)
        # Because trailing stop was NOT armed, this should NOT trigger trailing stop exit
        should_exit, _, _ = self.rm.check_exit_conditions(99.5)
        self.assertFalse(should_exit)

    def test_trailing_stop_arms_and_locks_profit(self):
        """
        Verify trailing stop arms once profit >= 1.5%, tracks peak,
        and triggers when price retreats by 1.0% callback from peak.
        """
        entry_price = 100.0
        self.rm.open_position(entry_price=entry_price, quantity=0.15)

        # 1. Price rises to 102.0 (+2.0% gain > 1.5% activation) -> Arms trailing stop
        should_exit, _, _ = self.rm.check_exit_conditions(102.0)
        self.assertFalse(should_exit)
        self.assertTrue(self.rm.position.trailing_armed)
        self.assertEqual(self.rm.position.peak_price, 102.0)

        # Trailing stop price is peak * (1 - 0.01) = 102.0 * 0.99 = 100.98

        # 2. Price climbs higher to 103.0 (+3.0%) -> Peak updates to 103.0
        should_exit, _, _ = self.rm.check_exit_conditions(103.0)
        self.assertFalse(should_exit)
        self.assertEqual(self.rm.position.peak_price, 103.0)
        # New trailing stop price: 103.0 * 0.99 = 101.97

        # 3. Price pulls back slightly to 102.5 (above 101.97) -> Does NOT exit
        should_exit, _, _ = self.rm.check_exit_conditions(102.5)
        self.assertFalse(should_exit)

        # 4. Price falls to 101.90 (below 101.97) -> TRAILING STOP TRIGGERS!
        should_exit, reason, details = self.rm.check_exit_conditions(101.90)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "TRAILING_STOP")
        self.assertAlmostEqual(details["peak_price"], 103.0, places=2)
        self.assertAlmostEqual(details["trailing_stop_price"], 101.97, places=2)
        # Profit locked in is ~+1.9%, safely in green!
        self.assertGreater(details["locked_in_profit_pct"], 1.5)

    # --------------------------------------------------------------------------
    # 4. CIRCUIT BREAKER / DAILY LOSS LIMIT TESTS
    # --------------------------------------------------------------------------
    def test_circuit_breaker_halts_entries_after_max_daily_loss(self):
        """Verify circuit breaker triggers when cumulative daily losses reach $1.00."""
        # Open and close trade with -$0.40 loss
        self.rm.open_position(entry_price=100.0, quantity=1.0)
        summary1 = self.rm.close_position(exit_price=99.60)
        self.assertAlmostEqual(summary1["pnl_usdt"], -0.40, places=2)
        self.assertFalse(self.rm.daily_tracker.circuit_breaker_triggered)

        # Open and close second trade with -$0.30 loss (total loss = $0.70 < $1.00)
        self.rm.open_position(entry_price=100.0, quantity=1.0)
        summary2 = self.rm.close_position(exit_price=99.70)
        self.assertAlmostEqual(summary2["pnl_usdt"], -0.30, places=2)
        self.assertFalse(self.rm.daily_tracker.circuit_breaker_triggered)

        # Open and close third trade with -$0.35 loss (total loss = $1.05 >= $1.00 limit)
        self.rm.open_position(entry_price=100.0, quantity=1.0)
        summary3 = self.rm.close_position(exit_price=99.65)
        self.assertAlmostEqual(summary3["pnl_usdt"], -0.35, places=2)
        self.assertTrue(summary3["circuit_breaker_tripped"])
        self.assertTrue(self.rm.daily_tracker.circuit_breaker_triggered)

        # Now test that evaluate_entry_filters strictly blocks new entries
        dummy_df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.002)
        can_enter, reason = self.rm.evaluate_entry_filters(dummy_df, trade_amount_usdt=15.0)
        self.assertFalse(can_enter)
        self.assertIn("Circuit breaker active", reason)

    def test_circuit_breaker_resets_on_day_rollover(self):
        """Verify circuit breaker automatically resets when a new day begins."""
        day1 = datetime(2026, 11, 5, 10, 0, 0)
        day2 = datetime(2026, 11, 6, 0, 1, 0)

        # Trip breaker on Day 1
        self.rm.open_position(entry_price=100.0, quantity=1.0, timestamp=day1)
        self.rm.close_position(exit_price=98.0, timestamp=day1)  # -$2.00 loss
        self.assertTrue(self.rm.daily_tracker.circuit_breaker_triggered)

        # Check circuit breaker on Day 2 -> Should auto-reset
        active, _ = self.rm.daily_tracker.is_circuit_breaker_active(
            self.config.max_daily_loss_usdt,
            current_time=day2
        )
        self.assertFalse(active)
        self.assertEqual(self.rm.daily_tracker.realized_losses, 0.0)

    # --------------------------------------------------------------------------
    # 5. MINIMUM VOLUME FILTER TESTS
    # --------------------------------------------------------------------------
    def test_volume_filter_rejects_low_volume_candles(self):
        """Verify entry is blocked if candle volume is below 80% of 20-period SMA."""
        # 29 candles with 1000 volume, but candle -2 has only 500 volume (50% of SMA)
        df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.002)
        df.loc[df.index[-2], "volume"] = 500  # Low volume on completed candle

        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.0)
        self.assertFalse(can_enter)
        self.assertIn("Volume too low", reason)

    def test_volume_filter_allows_normal_volume(self):
        """Verify entry passes when volume is sufficient."""
        df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.002)
        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.0)
        self.assertTrue(can_enter)
        self.assertEqual(reason, "All risk filters passed")

    # --------------------------------------------------------------------------
    # 6. MINIMUM VOLATILITY (ATR) FILTER TESTS
    # --------------------------------------------------------------------------
    def test_atr_volatility_filter_rejects_flat_sideways_chop(self):
        """Verify entry is rejected when market volatility (ATR) is below min threshold (0.2%)."""
        # Flat candles with high-low range of only 0.01 on price 100 (0.01% volatility)
        df = self._create_flat_candles(num_candles=30, close_price=100.0, noise=0.005)
        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.0)
        self.assertFalse(can_enter)
        self.assertIn("Volatility too low", reason)

    def test_atr_volatility_filter_allows_active_market(self):
        """Verify entry is permitted when ATR volatility is healthy."""
        df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.008, spread_pct=0.002)
        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.0)
        self.assertTrue(can_enter)

    # --------------------------------------------------------------------------
    # 7. EMA SPREAD FILTER TESTS
    # --------------------------------------------------------------------------
    def test_ema_spread_filter_rejects_parallel_lines(self):
        """Verify micro-crosses of almost identical EMAs are rejected."""
        df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.0001)
        # Manually force identical EMAs on completed candle
        df.loc[df.index[-2], "ema_spread_pct"] = 0.0001  # 0.01% < 0.05% minimum filter
        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.0)
        self.assertFalse(can_enter)
        self.assertIn("EMA spread too narrow", reason)

    # --------------------------------------------------------------------------
    # 8. MINIMUM NOTIONAL FILTER TESTS
    # --------------------------------------------------------------------------
    def test_min_notional_filter_protects_small_balance(self):
        """Verify orders smaller than Binance minimum notional ($5.00) are blocked."""
        df = self._create_dummy_candles(num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.002)
        # Attempting a $3.00 trade
        can_enter, reason = self.rm.evaluate_entry_filters(df, trade_amount_usdt=3.00)
        self.assertFalse(can_enter)
        self.assertIn("minimum notional requirement", reason)

        # $15 trade passes
        can_enter, _ = self.rm.evaluate_entry_filters(df, trade_amount_usdt=15.00)
        self.assertTrue(can_enter)

    # --------------------------------------------------------------------------
    # 9. STATUS SUMMARY & HELPERS
    # --------------------------------------------------------------------------
    def test_status_summary_output(self):
        """Verify status summary dict reflects live metrics."""
        summary = self.rm.get_status_summary()
        self.assertFalse(summary["in_position"])
        self.assertEqual(summary["daily_realized_loss"], 0.0)

        self.rm.open_position(entry_price=100.0, quantity=0.15)
        summary_in_pos = self.rm.get_status_summary(current_price=102.0)
        self.assertTrue(summary_in_pos["in_position"])
        self.assertAlmostEqual(summary_in_pos["entry_price"], 100.0)
        self.assertAlmostEqual(summary_in_pos["unrealized_pnl_pct"], 2.0)
        self.assertTrue(summary_in_pos["trailing_armed"])

    # --------------------------------------------------------------------------
    # Helper functions to generate synthetic candle data
    # --------------------------------------------------------------------------
    def _create_dummy_candles(self, num_candles=30, volume=1000, atr_pct=0.005, spread_pct=0.002):
        base_price = 100.0
        data = []
        for i in range(num_candles):
            close = base_price + i * 0.2
            high = close + (close * atr_pct)
            low = close - (close * atr_pct)
            open_p = close - 0.1
            data.append({
                "timestamp": datetime.now() - timedelta(minutes=(num_candles - i) * 5),
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            })
        df = pd.DataFrame(data)
        df = compute_all_risk_indicators(df)
        df["ema_spread_pct"] = spread_pct
        return df

    def _create_flat_candles(self, num_candles=30, close_price=100.0, noise=0.001):
        data = []
        for i in range(num_candles):
            high = close_price + noise
            low = close_price - noise
            data.append({
                "timestamp": datetime.now() - timedelta(minutes=(num_candles - i) * 5),
                "open": close_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 1000,
            })
        df = pd.DataFrame(data)
        df = compute_all_risk_indicators(df)
        return df


from bot import BotState, execute_trade, check_crossover_signal, compute_indicators


class MockExchange:
    """Mock CCXT exchange for testing order executions without network."""
    def __init__(self, last_price=50000.0):
        self.last_price = last_price
        self.buy_orders = []
        self.sell_orders = []

    def fetch_ticker(self, symbol):
        return {"symbol": symbol, "last": self.last_price}

    def create_market_buy_order(self, symbol, qty):
        order = {"id": f"mock_buy_{len(self.buy_orders)}", "symbol": symbol, "qty": qty, "price": self.last_price}
        self.buy_orders.append(order)
        return order

    def create_market_sell_order(self, symbol, qty):
        order = {"id": f"mock_sell_{len(self.sell_orders)}", "symbol": symbol, "qty": qty, "price": self.last_price}
        self.sell_orders.append(order)
        return order


class TestBotIntegration(unittest.TestCase):
    """Verifies seamless integration between bot.py and RiskManager."""

    def setUp(self):
        self.config = RiskConfig(
            stop_loss_pct=0.015,
            take_profit_pct=0.035,
            trailing_stop_enabled=True,
            trailing_stop_activation_pct=0.015,
            trailing_stop_callback_pct=0.010,
            max_daily_loss_usdt=1.00,
        )
        self.risk_manager = RiskManager(self.config)
        self.state = BotState(risk_manager=self.risk_manager)
        self.exchange = MockExchange(last_price=50000.0)

    def test_bot_buy_and_sell_cycle(self):
        """Verify bot state and risk manager synchronize on BUY and SELL execution."""
        # 1. Execute BUY
        execute_trade(
            exchange=self.exchange,
            action="BUY",
            symbol="BTC/USDT",
            trade_amount_usdt=15.0,
            state=self.state,
            reason="EMA_BULLISH_CROSS",
            exit_price=50000.0
        )
        self.assertTrue(self.state.in_position)
        self.assertEqual(self.state.entry_price, 50000.0)
        self.assertTrue(self.state.risk_manager.is_in_position)
        self.assertEqual(self.state.risk_manager.position.entry_price, 50000.0)

        # 2. Execute SELL at profit (51500.0 = +3.0%)
        execute_trade(
            exchange=self.exchange,
            action="SELL",
            symbol="BTC/USDT",
            trade_amount_usdt=15.0,
            state=self.state,
            reason="TAKE_PROFIT",
            exit_price=51500.0
        )
        self.assertFalse(self.state.in_position)
        self.assertEqual(self.state.entry_price, 0.0)
        self.assertFalse(self.state.risk_manager.is_in_position)
        self.assertGreater(self.state.risk_manager.daily_tracker.realized_pnl, 0.0)

    def test_bot_risk_exit_triggers_emergency_sell(self):
        """Verify a stop-loss risk condition triggers immediate SELL in bot workflow."""
        # Enter at 50,000
        execute_trade(
            exchange=self.exchange,
            action="BUY",
            symbol="BTC/USDT",
            trade_amount_usdt=15.0,
            state=self.state,
            reason="EMA_BULLISH_CROSS",
            exit_price=50000.0
        )

        # Price drops to 49,000 (-2.0%, exceeds -1.5% SL)
        current_price = 49000.0
        should_exit, reason, details = self.state.risk_manager.check_exit_conditions(current_price)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "STOP_LOSS")

        # Execute risk sell
        execute_trade(
            exchange=self.exchange,
            action="SELL",
            symbol="BTC/USDT",
            trade_amount_usdt=15.0,
            state=self.state,
            reason=reason,
            exit_price=current_price
        )
        self.assertFalse(self.state.in_position)
        self.assertGreater(self.state.risk_manager.daily_tracker.realized_losses, 0.0)


if __name__ == "__main__":
    unittest.main()
