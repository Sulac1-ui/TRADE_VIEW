import os
import configparser
import logging
from typing import Tuple, List, Dict, Any

logger = logging.getLogger("RuleVerifier")

RULES_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "trading_rules.txt"))

class TradingRules:
    def __init__(self, filepath: str = RULES_FILE_PATH):
        self.filepath = filepath
        self.config = configparser.ConfigParser()
        self.reload()

    def reload(self):
        """Reload rules from trading_rules.txt on every cycle."""
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"CRITICAL: Rules file not found at {self.filepath}!")
        self.config.read(self.filepath)

    @property
    def allow_real_money_trading(self) -> bool:
        return self.config.getboolean("SECURITY_AND_ENVIRONMENT", "ALLOW_REAL_MONEY_TRADING", fallback=False)

    @property
    def allowed_pairs(self) -> List[str]:
        raw = self.config.get("SECURITY_AND_ENVIRONMENT", "ALLOWED_PAIRS", fallback="BTC/USDT")
        return [p.strip().upper() for p in raw.split(",")]

    @property
    def max_trade_amount(self) -> float:
        return self.config.getfloat("CAPITAL_PROTECTION", "MAX_TRADE_AMOUNT_USDT", fallback=15.0)

    @property
    def min_wallet_reserve(self) -> float:
        return self.config.getfloat("CAPITAL_PROTECTION", "MIN_WALLET_RESERVE_USDT", fallback=5.0)

    @property
    def max_loss_per_trade_pct(self) -> float:
        return self.config.getfloat("CAPITAL_PROTECTION", "MAX_ALLOWED_LOSS_PER_TRADE_PCT", fallback=0.015)

    @property
    def max_daily_loss_usdt(self) -> float:
        return self.config.getfloat("CIRCUIT_BREAKERS", "MAX_DAILY_LOSS_USDT", fallback=1.00)

    @property
    def max_consecutive_losses(self) -> int:
        return self.config.getint("CIRCUIT_BREAKERS", "MAX_CONSECUTIVE_LOSSES", fallback=3)

    @property
    def max_trades_per_day(self) -> int:
        return self.config.getint("CIRCUIT_BREAKERS", "MAX_TRADES_PER_DAY", fallback=10)

    @property
    def min_timeframe(self) -> str:
        return self.config.get("MARKET_CONDITIONS", "MIN_TIMEFRAME", fallback="15m").strip().lower()

    @property
    def min_atr_pct(self) -> float:
        return self.config.getfloat("MARKET_CONDITIONS", "MIN_ATR_VOLATILITY_PCT", fallback=0.002)

    @property
    def min_volume_ratio(self) -> float:
        return self.config.getfloat("MARKET_CONDITIONS", "MIN_VOLUME_RATIO", fallback=0.80)

    def validate_pre_flight(self, symbol: str, timeframe: str, trade_amount: float, dry_run: bool) -> Tuple[bool, str]:
        """
        Validates configuration against trading_rules.txt before starting or entering trades.
        Returns: (is_allowed: bool, reason: str)
        """
        self.reload()

        # 1. Real money safety latch
        if not dry_run and not self.allow_real_money_trading:
            return False, "RULE BREACH: Real money trading is disabled in trading_rules.txt (ALLOW_REAL_MONEY_TRADING=False)"

        # 2. Allowed pairs check
        if symbol.upper() not in self.allowed_pairs:
            return False, f"RULE BREACH: Symbol '{symbol}' is not in ALLOWED_PAIRS: {self.allowed_pairs}"

        # 3. Trade amount ceiling
        if trade_amount > self.max_trade_amount:
            return False, f"RULE BREACH: Trade amount ${trade_amount:.2f} exceeds MAX_TRADE_AMOUNT_USDT (${self.max_trade_amount:.2f})"

        # 4. Timeframe restrictions (must be >= MIN_TIMEFRAME)
        tf_rank = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
        current_rank = tf_rank.get(timeframe.lower(), 0)
        min_rank = tf_rank.get(self.min_timeframe, 15)
        if current_rank < min_rank and not dry_run:
            return False, f"RULE BREACH: Timeframe '{timeframe}' is too low! Minimum allowed in trading_rules.txt is '{self.min_timeframe}'"

        return True, "ALL RULES VERIFIED OK"
