"""
Comprehensive Multi-Model Forecasting Engine for Crypto Trading:
Combines:
1. ARIMA Time-Series Econometric Model (AutoRegressive Integrated Moving Average)
2. Machine Learning Classifier (Random Forest + Gradient Boosting)
3. Technical Confluence (9/15 EMA, RSI, MACD, Volume)
Provides an ensemble consensus: UP / DOWN, target forecast price, and BUY / SELL / WAIT advice.
"""

import os
import time
import logging
import warnings
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")
logger = logging.getLogger("Forecaster")

class HybridTradingForecaster:
    def __init__(self):
        self.scaler = StandardScaler()
        self.rf_model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
        self.gb_model = GradientBoostingClassifier(n_estimators=80, learning_rate=0.05, max_depth=3, random_state=42)
        self.is_trained = False
        self.feature_names = []

    def compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
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

        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        data["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        data["macd"] = ema_12 - ema_26
        data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
        data["macd_hist"] = data["macd"] - data["macd_signal"]

        # Returns
        data["ret_1"] = close.pct_change(1) * 100.0
        data["ret_3"] = close.pct_change(3) * 100.0
        data["vol_ratio"] = volume / (volume.rolling(window=20).mean() + 1e-9)

        self.feature_names = ["ema_spread_pct", "rsi_14", "macd_hist", "ret_1", "ret_3", "vol_ratio"]
        return data

    def run_arima_forecast(self, close_series: pd.Series, steps: int = 1) -> Tuple[float, float, str]:
        """
        Fits an ARIMA(2, 1, 2) on recent closing prices to predict the next price level.
        Returns: (forecasted_price, expected_change_pct, arima_direction)
        """
        try:
            # Use last 80-100 candles for clean convergence
            recent_prices = close_series.iloc[-100:].values
            current_price = float(recent_prices[-1])

            model = ARIMA(recent_prices, order=(2, 1, 2))
            model_fit = model.fit()
            forecast_result = model_fit.forecast(steps=steps)
            predicted_price = float(forecast_result[0])

            change_pct = ((predicted_price - current_price) / current_price) * 100.0
            direction = "UP" if predicted_price > current_price else "DOWN"
            return predicted_price, round(change_pct, 3), direction
        except Exception as e:
            logger.warning(f"ARIMA fit fallback: {e}")
            curr = float(close_series.iloc[-1])
            return curr, 0.0, "NEUTRAL"

    def train_ml_models(self, df: pd.DataFrame):
        data = self.compute_technical_indicators(df)
        data["target"] = (data["close"].shift(-1) > data["close"]).astype(int)
        clean = data.dropna(subset=self.feature_names + ["target"])

        if len(clean) < 40:
            return

        X = clean[self.feature_names]
        y = clean["target"]
        X_scaled = self.scaler.fit_transform(X)

        self.rf_model.fit(X_scaled, y)
        self.gb_model.fit(X_scaled, y)
        self.is_trained = True

    def predict_ensemble(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Runs ARIMA + Random Forest + Gradient Boosting + EMA Rule Check
        Generates a consolidated actionable signal.
        """
        if not self.is_trained:
            self.train_ml_models(df)

        data = self.compute_technical_indicators(df)
        latest_close = float(data["close"].iloc[-1])
        ema9 = float(data["ema_9"].iloc[-1])
        ema15 = float(data["ema_15"].iloc[-1])
        rsi = float(data["rsi_14"].iloc[-1])
        spread = float(data["ema_spread_pct"].iloc[-1])

        # 1. ARIMA Forecast
        arima_price, arima_change_pct, arima_dir = self.run_arima_forecast(data["close"])

        # 2. ML Classifier Predictions
        latest_features = data.iloc[[-1]][self.feature_names].fillna(0)
        features_scaled = self.scaler.transform(latest_features)

        rf_prob = self.rf_model.predict_proba(features_scaled)[0]
        gb_prob = self.gb_model.predict_proba(features_scaled)[0]

        # Ensemble average probabilities
        prob_up = float((rf_prob[1] + gb_prob[1]) / 2.0)
        prob_down = float((rf_prob[0] + gb_prob[0]) / 2.0)
        ml_dir = "UP" if prob_up > prob_down else "DOWN"
        ml_conf = max(prob_up, prob_down) * 100.0

        # 3. Consensus Engine
        # Votes: ARIMA (1 vote), ML Classifier (1 vote), EMA 9/15 (1 vote)
        votes_up = 0
        votes_down = 0

        if arima_dir == "UP": votes_up += 1
        elif arima_dir == "DOWN": votes_down += 1

        if ml_dir == "UP": votes_up += 1
        elif ml_dir == "DOWN": votes_down += 1

        if ema9 > ema15: votes_up += 1
        elif ema9 < ema15: votes_down += 1

        # Synthesize final recommendation
        if votes_up >= 2 and rsi < 70:
            recommendation = "BUY"
            color = "#10b981"
            explanation = f"Bullish Confluence ({votes_up}/3 votes): ARIMA targets ${arima_price:.2f} ({arima_change_pct:+.2f}%), ML {ml_conf:.0f}% confidence, EMA 9 > 15."
        elif votes_down >= 2 and rsi > 30:
            recommendation = "SELL"
            color = "#ef4444"
            explanation = f"Bearish Confluence ({votes_down}/3 votes): ARIMA targets ${arima_price:.2f} ({arima_change_pct:+.2f}%), ML {ml_conf:.0f}% confidence, EMA 9 < 15."
        else:
            recommendation = "WAIT / HOLD"
            color = "#eab308"
            explanation = f"Mixed signals / Market Consolidation. Votes: {votes_up} UP vs {votes_down} DOWN. Wait for alignment."

        return {
            "current_price": latest_close,
            "recommendation": recommendation,
            "badge_color": color,
            "consensus": "STRONG BULLISH" if votes_up == 3 else ("BULLISH" if votes_up == 2 else ("STRONG BEARISH" if votes_down == 3 else ("BEARISH" if votes_down == 2 else "NEUTRAL"))),
            "arima": {
                "forecast_price": round(arima_price, 2),
                "expected_change_pct": arima_change_pct,
                "direction": arima_dir,
            },
            "ml_classifier": {
                "direction": ml_dir,
                "confidence_pct": round(ml_conf, 1),
                "prob_up_pct": round(prob_up * 100, 1),
                "prob_down_pct": round(prob_down * 100, 1),
            },
            "technical": {
                "ema_9": round(ema9, 2),
                "ema_15": round(ema15, 2),
                "ema_spread_pct": round(spread, 3),
                "rsi_14": round(rsi, 1),
            },
            "explanation": explanation,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

if __name__ == "__main__":
    import ccxt
    ex = ccxt.binance()
    print("Testing Hybrid ARIMA + ML Engine...")
    candles = ex.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=120)
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    forecaster = HybridTradingForecaster()
    res = forecaster.predict_ensemble(df)
    
    print("\n================ HYBRID FORECASTER RESULT ================")
    print(f"Current Price:      ${res['current_price']:.2f}")
    print(f"Action Recommendation: {res['recommendation']}")
    print(f"Consensus:          {res['consensus']}")
    print(f"ARIMA Next Price:   ${res['arima']['forecast_price']:.2f} ({res['arima']['expected_change_pct']:+.2f}%) [{res['arima']['direction']}]")
    print(f"ML Direction:       {res['ml_classifier']['direction']} ({res['ml_classifier']['confidence_pct']}% conf)")
    print(f"EMA 9 vs 15:        {res['technical']['ema_9']} vs {res['technical']['ema_15']}")
    print(f"Explanation:        {res['explanation']}")
    print("==========================================================")
