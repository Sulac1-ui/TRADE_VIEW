"""
ML Predictor Engine for Live Crypto Trading
Combines 9/15 EMA trend with Random Forest / Gradient Boosting models
to predict next-candle direction (UP / DOWN), confidence percentage,
and clear actionable advice (BUY / SELL / WAIT).
"""

import os
import time
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
import joblib

logger = logging.getLogger("ML_Predictor")

MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models"))
os.makedirs(MODEL_DIR, exist_ok=True)

class MLTradingPredictor:
    def __init__(self, model_type: str = "rf"):
        self.model_type = model_type
        self.scaler = StandardScaler()
        if model_type == "gb":
            self.model = GradientBoostingClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, random_state=42)
        else:
            self.model = RandomForestClassifier(n_estimators=120, max_depth=6, min_samples_split=4, random_state=42)
        self.is_trained = False
        self.feature_names = []

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts robust multi-factor technical indicators:
        - 9 EMA, 15 EMA, 50 EMA, 200 EMA
        - EMA Spread % & Rate of Change
        - RSI (Relative Strength Index)
        - ATR Volatility %
        - MACD & Signal Line
        - Volume Momentum (Volume vs 20 SMA)
        - Price Return lags (1, 2, 3, 5 periods)
        """
        data = df.copy()
        close = data["close"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"]

        # EMAs
        data["ema_9"] = close.ewm(span=9, adjust=False).mean()
        data["ema_15"] = close.ewm(span=15, adjust=False).mean()
        data["ema_50"] = close.ewm(span=50, adjust=False).mean()
        data["ema_spread_pct"] = (data["ema_9"] - data["ema_15"]) / close * 100.0
        data["ema_dist_50"] = (close - data["ema_50"]) / close * 100.0

        # RSI (14-period)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        data["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD (12, 26, 9)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        data["macd"] = ema_12 - ema_26
        data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
        data["macd_hist"] = data["macd"] - data["macd_signal"]

        # ATR Volatility %
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        data["atr_pct"] = (tr.rolling(window=14).mean() / close) * 100.0

        # Volume Momentum
        vol_sma = volume.rolling(window=20).mean()
        data["vol_ratio"] = volume / (vol_sma + 1e-9)

        # Price momentum / returns
        data["ret_1"] = close.pct_change(1) * 100.0
        data["ret_3"] = close.pct_change(3) * 100.0
        data["ret_5"] = close.pct_change(5) * 100.0

        self.feature_names = [
            "ema_spread_pct", "ema_dist_50", "rsi_14", "macd_hist",
            "atr_pct", "vol_ratio", "ret_1", "ret_3", "ret_5"
        ]

        return data

    def train_on_history(self, df: pd.DataFrame, horizon: int = 1) -> Dict[str, Any]:
        """
        Trains model on historical candles.
        Target: 1 if close in `horizon` candles > current close, else 0.
        """
        data = self.extract_features(df)
        data["target"] = (data["close"].shift(-horizon) > data["close"]).astype(int)
        
        # Drop rows with NaN from rolling calculations or shifted target
        clean_df = data.dropna(subset=self.feature_names + ["target"])
        if len(clean_df) < 50:
            raise ValueError(f"Insufficient candle history for ML training: {len(clean_df)} valid rows.")

        X = clean_df[self.feature_names]
        y = clean_df["target"]

        # Train/Test Split (last 20% for test)
        split_idx = int(len(clean_df) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        self.model.fit(X_train_scaled, y_train)
        train_acc = self.model.score(X_train_scaled, y_train)
        test_acc = self.model.score(X_test_scaled, y_test)
        self.is_trained = True

        logger.info(f"Model ({self.model_type.upper()}) trained. Train Acc: {train_acc*100:.1f}% | Test Acc: {test_acc*100:.1f}%")
        return {
            "model_type": self.model_type,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "train_accuracy_pct": round(train_acc * 100, 2),
            "test_accuracy_pct": round(test_acc * 100, 2),
        }

    def predict_current(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Predicts next candle direction and generates clear, unambiguous trader advice.
        """
        if not self.is_trained:
            # Auto-train if not trained yet
            self.train_on_history(df)

        data = self.extract_features(df)
        latest_row = data.iloc[[-1]][self.feature_names].fillna(0)
        X_scaled = self.scaler.transform(latest_row)

        probs = self.model.predict_proba(X_scaled)[0]
        prob_down = float(probs[0])
        prob_up = float(probs[1])

        direction = "UP" if prob_up > prob_down else "DOWN"
        confidence = max(prob_up, prob_down) * 100.0

        # Technical EMA Context
        latest_close = float(data["close"].iloc[-1])
        ema9 = float(data["ema_9"].iloc[-1])
        ema15 = float(data["ema_15"].iloc[-1])
        ema_spread = ((ema9 - ema15) / latest_close) * 100.0
        rsi = float(data["rsi_14"].iloc[-1])

        # Synthesize Clear Action Advice
        action = "WAIT / HOLD"
        action_color = "#94a3b8"
        reasoning = []

        if direction == "UP" and confidence >= 58.0:
            if ema9 > ema15:
                action = "BUY"
                action_color = "#10b981"
                reasoning.append(f"Strong confluence: ML predicts UP with {confidence:.1f}% confidence & EMA 9 is above EMA 15.")
            elif rsi < 35:
                action = "BUY (OVERSOLD REVERSAL)"
                action_color = "#10b981"
                reasoning.append(f"ML predicts UP ({confidence:.1f}%) and RSI ({rsi:.1f}) indicates oversold rebound.")
            else:
                action = "PREPARE BUY"
                action_color = "#38bdf8"
                reasoning.append(f"ML leans UP ({confidence:.1f}%), wait for EMA 9 to confirm cross above EMA 15.")

        elif direction == "DOWN" and confidence >= 58.0:
            if ema9 < ema15:
                action = "SELL / TAKE PROFIT"
                action_color = "#ef4444"
                reasoning.append(f"Strong confluence: ML predicts DOWN with {confidence:.1f}% confidence & EMA 9 is below EMA 15.")
            elif rsi > 70:
                action = "SELL (OVERBOUGHT PEAK)"
                action_color = "#ef4444"
                reasoning.append(f"ML predicts DOWN ({confidence:.1f}%) and RSI ({rsi:.1f}) indicates overbought exhaustion.")
            else:
                action = "PREPARE SELL / TIGHTEN STOP"
                action_color = "#f97316"
                reasoning.append(f"ML leans DOWN ({confidence:.1f}%), keep tight stop-loss or prepare to exit.")
        else:
            action = "WAIT / INDECISIVE"
            action_color = "#eab308"
            reasoning.append(f"Confidence ({confidence:.1f}%) is in neutral zone (<58%). Market is ranging.")

        return {
            "prediction": direction,
            "confidence_pct": round(confidence, 1),
            "prob_up_pct": round(prob_up * 100, 1),
            "prob_down_pct": round(prob_down * 100, 1),
            "action": action,
            "action_color": action_color,
            "current_price": latest_close,
            "ema_9": round(ema9, 2),
            "ema_15": round(ema15, 2),
            "ema_spread_pct": round(ema_spread, 3),
            "rsi_14": round(rsi, 1),
            "reasoning": " ".join(reasoning),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

if __name__ == "__main__":
    import ccxt
    print("Testing ML Engine with live Binance data...")
    ex = ccxt.binance()
    candles = ex.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=150)
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    
    predictor = MLTradingPredictor(model_type="rf")
    metrics = predictor.train_on_history(df)
    pred = predictor.predict_current(df)
    
    print("\n--- ML LIVE PREDICTION RESULT ---")
    print(f"Prediction:     {pred['prediction']} (Confidence: {pred['confidence_pct']}%)")
    print(f"Recommended:    {pred['action']}")
    print(f"Price:          ${pred['current_price']:.2f}")
    print(f"EMA 9 vs 15:    {pred['ema_9']} vs {pred['ema_15']} (Spread: {pred['ema_spread_pct']}%)")
    print(f"RSI 14:         {pred['rsi_14']}")
    print(f"Reasoning:      {pred['reasoning']}")
