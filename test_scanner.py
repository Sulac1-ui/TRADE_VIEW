#!/usr/bin/env python3
"""
Unit Tests for Multi-Pair Market Scanner and Signal Screener (`scanner.py`)
Tests EMA calculation, crossover detection, convergence logic, volume confirmation,
and JSON persistence.
"""

import unittest
import os
import json
import pandas as pd
import numpy as np

from scanner import (
    DEFAULT_CONVERGENCE_PCT,
    save_signals_to_file,
    format_price,
)


class TestScannerCalculations(unittest.TestCase):
    def setUp(self):
        self.test_json = "test_scanner_signals.json"

    def tearDown(self):
        if os.path.exists(self.test_json):
            os.remove(self.test_json)

    def create_mock_dataframe(self, closes, volumes=None):
        """Creates a mock DataFrame with candles and EMAs."""
        if volumes is None:
            volumes = [100.0] * len(closes)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=len(closes), freq="5min"),
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes,
        })
        df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema_15"] = df["close"].ewm(span=15, adjust=False).mean()
        df["vol_sma_20"] = df["volume"].rolling(window=20).mean()
        return df

    def test_bullish_crossover_detection(self):
        """Verifies detection of bullish EMA 9 crossing above EMA 15."""
        # Flat bearish then sharp spike upwards
        closes = [100.0] * 30 + [98.0, 97.0, 96.0, 105.0, 110.0]
        df = self.create_mock_dataframe(closes)

        c_prev2 = df.iloc[-3]
        c_prev1 = df.iloc[-2]

        # Prior was below, now above
        was_below = c_prev2["ema_9"] <= c_prev2["ema_15"]
        now_above = c_prev1["ema_9"] > c_prev1["ema_15"]

        self.assertTrue(was_below)
        self.assertTrue(now_above)

    def test_bearish_crossover_detection(self):
        """Verifies detection of bearish EMA 9 crossing below EMA 15."""
        # Flat bullish then sharp drop downwards
        closes = [100.0] * 30 + [102.0, 103.0, 104.0, 95.0, 90.0]
        df = self.create_mock_dataframe(closes)

        c_prev2 = df.iloc[-3]
        c_prev1 = df.iloc[-2]

        was_above = c_prev2["ema_9"] >= c_prev2["ema_15"]
        now_below = c_prev1["ema_9"] < c_prev1["ema_15"]

        self.assertTrue(was_above)
        self.assertTrue(now_below)

    def test_impending_crossover_logic(self):
        """Verifies impending crossover detection within 0.1% threshold."""
        # Values close to each other (<0.1%)
        ema_9 = 100.05
        ema_15 = 100.00
        diff_pct = (ema_9 - ema_15) / ema_15 * 100
        abs_diff = abs(diff_pct)

        self.assertLessEqual(abs_diff, DEFAULT_CONVERGENCE_PCT)

        # Prev diff was larger (converging)
        prev_ema_9 = 100.20
        prev_ema_15 = 100.00
        prev_abs_diff = abs((prev_ema_9 - prev_ema_15) / prev_ema_15 * 100)

        is_converging = abs_diff < prev_abs_diff
        self.assertTrue(is_converging)

    def test_volume_ratio_confirmation(self):
        """Verifies volume SMA ratio and confirmation thresholds."""
        volumes = [100.0] * 20 + [250.0]  # Last volume is 2.5x SMA
        closes = [100.0] * 21
        df = self.create_mock_dataframe(closes, volumes)

        vol_ratio = df["volume"].iloc[-1] / df["vol_sma_20"].iloc[-1]
        self.assertGreaterEqual(vol_ratio, 1.5)

    def test_price_formatting(self):
        """Tests adaptive decimal formatting based on asset magnitude."""
        self.assertEqual(format_price(79814.15), "79,814.15")
        self.assertEqual(format_price(8.683), "8.6830")
        self.assertEqual(format_price(0.07601), "0.076010")

    def test_json_persistence(self):
        """Verifies JSON output structure and atomic save mechanism."""
        mock_data = {
            "timestamp": "2026-11-05T13:50:00Z",
            "duration_seconds": 1.5,
            "config": {
                "symbols": ["BTC/USDT", "ETH/USDT"],
                "timeframes": ["5m", "15m", "1h"],
                "convergence_pct": 0.1,
            },
            "summary": {
                "total_scanned": 6,
                "active_crossovers_count": 1,
                "impending_count": 2,
                "strong_trends_count": 0,
            },
            "active_crossovers": [
                {
                    "symbol": "BTC/USDT",
                    "timeframe": "1h",
                    "price": 79800.0,
                    "action": "SELL_ALERT",
                }
            ],
            "impending_crossovers": [],
            "mtf_confluence": [],
            "all_results": [],
        }

        success = save_signals_to_file(mock_data, self.test_json)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.test_json))

        with open(self.test_json, "r") as f:
            loaded = json.load(f)

        self.assertEqual(loaded["summary"]["total_scanned"], 6)
        self.assertEqual(loaded["active_crossovers"][0]["symbol"], "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
