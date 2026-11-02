"""Settings: defaults + user overrides persisted to data/settings.json.

Every editable value has a default here. Updates are type-checked against the default's type and,
where given, clamped to BOUNDS, so a bad value from the UI can never crash a scan."""
from __future__ import annotations
import copy, json, os, pathlib, threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = pathlib.Path(os.getenv("KRAKEN_DATA") or (ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = DATA / "settings.json"

DEFAULTS: dict = {
    "chain": "sol",
    "mode": "SHADOW",                 # SHADOW = paper trades only · LIVE = real swaps via gmgn-cli
    "screen": {
        "interval": "1h", "limit": 100, "auto": False, "auto_every_min": 10,
        "max_top10": 0.35, "max_dev_hold": 0.10, "max_bundler": 0.30, "max_rug": 0.30,
        "max_buy_tax": 0.10, "max_sell_tax": 0.10, "require_renounced": True,
        "min_liquidity": 10000, "min_mcap": 20000, "max_mcap": 5000000, "min_smart_money": 1,
        "min_score": 40, "show_rejected": True,
    },
    "hunter": {
        "setup": "floor", "auto": True, "auto_every_min": 10, "scan_n": 30,
        "min_mcap": 20000, "max_mcap": 1000000, "max_age_h": 0, "min_age_min": 20, "min_liq": 10000,
        "min_base_min": 45, "max_range": 0.18,
        "min_pump": 2.5, "min_retrace": 0.60, "max_vol_ratio": 0.25, "near_low": 1.15,
        "max_mc_vs_ath": 0.40, "max_chg_1h": 0.25, "max_chg_5m": 0.06,
        "min_usd_per_min_floor": 15, "min_usd_per_min_any": 100,
        "max_dev_launches": 100, "max_logo_dups": 5, "skip_wash": True, "min_buys_1h": 5,
        "label_tp": 0.30, "label_sl": 0.15, "label_horizon_min": 120,
    },
    "autotrade": {
        "enabled": False, "live": False, "min_score": 40, "size": 0.05, "tp": 0.30, "sl": 0.15,
        "max_hold_min": 120, "max_open": 5, "daily_loss_limit": 0.25, "cooldown_h": 6,
        "unlock_trades": 100, "unlock_profit_factor": 1.3,
    },
    "risk": {
        "buy_size": 0.05, "max_positions": 10, "max_exposure": 1.0, "daily_loss_limit": 0.5,
        "slippage": 0.15, "stop_loss": 0.25, "take_profit": 1.0, "monitor_every_s": 30,
        "exit_on_safety_drop": True,
    },
    "alerts": {
        "enabled": False, "min_score": 60, "on_floor": True, "on_screen": False, "on_exit": True,
        "ntfy_topic": "", "telegram_token": "", "telegram_chat_id": "", "discord_webhook": "",
    },
    "rate": {"min_gap_s": 1.2, "max_inflight": 1},   # free GMGN tier; Plus tier ≈ 0.15 / 4
}

BOUNDS: dict = {
    "screen.limit": (10, 100), "screen.auto_every_min": (2, 1440),
    "hunter.scan_n": (1, 100), "hunter.auto_every_min": (2, 1440), "hunter.min_base_min": (5, 2880),
    "hunter.max_range": (0.01, 2.0), "hunter.min_pump": (1.0, 1000.0), "hunter.min_retrace": (0.0, 0.999),
    "hunter.max_vol_ratio": (0.01, 10.0), "hunter.near_low": (1.0, 5.0), "hunter.max_mc_vs_ath": (0.01, 1.0),
    "hunter.max_dev_launches": (0, 100000), "hunter.max_logo_dups": (0, 10000), "hunter.min_buys_1h": (0, 10000),
    "hunter.label_tp": (0.01, 10.0), "hunter.label_sl": (0.01, 0.99), "hunter.label_horizon_min": (10, 1440),
    "autotrade.min_score": (0, 100), "autotrade.size": (0.0001, 1000.0), "autotrade.tp": (0.01, 10.0),
    "autotrade.sl": (0.01, 0.99), "autotrade.max_hold_min": (5, 1440), "autotrade.max_open": (1, 50),
    "autotrade.daily_loss_limit": (0.0001, 1000.0), "autotrade.cooldown_h": (0, 168),
    "autotrade.unlock_trades": (30, 10000), "autotrade.unlock_profit_factor": (1.0, 10.0),
    "risk.buy_size": (0.0001, 1000.0), "risk.max_positions": (1, 100), "risk.slippage": (0.001, 0.5),
    "risk.stop_loss": (0.01, 0.99), "risk.take_profit": (0.01, 100.0), "risk.monitor_every_s": (5, 3600),
    "rate.min_gap_s": (0.05, 10.0), "rate.max_inflight": (1, 8),
}
CHOICES = {"mode": ("SHADOW", "LIVE"), "chain": ("sol", "bsc", "base", "eth"),
           "hunter.setup": ("floor", "any"), "screen.interval": ("1m", "5m", "1h", "6h", "24h")}
SECRET_KEYS = {"telegram_token", "discord_webhook"}


class Settings:
    def __init__(self, path: pathlib.Path = SETTINGS_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                self._merge(self.data, json.loads(path.read_text(encoding="utf-8")), "", strict=False)
            except Exception as e:
                print(f"[kraken] ignoring unreadable {path}: {e}")

    def get(self, dotted: str = ""):
        with self.lock:
            cur = self.data
            for k in filter(None, dotted.split(".")):
                cur = cur[k]
            return copy.deepcopy(cur)

    def __getitem__(self, section):
        with self.lock:
            return self.data[section]

    def update(self, patch: dict) -> dict:
        with self.lock:
            new = copy.deepcopy(self.data)
            self._merge(new, patch, "", strict=True)
            self.data = new
            self.save()
            return self.public()

    def reset(self, section: str | None = None) -> dict:
        with self.lock:
            if section:
                self.data[section] = copy.deepcopy(DEFAULTS[section])
            else:
                self.data = copy.deepcopy(DEFAULTS)
            self.save()
            return self.public()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def public(self) -> dict:
        """Settings for the UI: secrets masked (set / not set), never echoed back."""
        d = copy.deepcopy(self.data)
        for k in SECRET_KEYS:
            if d["alerts"].get(k):
                d["alerts"][k] = "••••set"
        return d

    def _merge(self, dst: dict, src: dict, prefix: str, strict: bool):
        for k, v in (src or {}).items():
            path = f"{prefix}{k}"
            if k not in dst:
                if strict:
                    raise ValueError(f"unknown setting {path}")
                continue
            d = dst[k]
            if isinstance(d, dict):
                if not isinstance(v, dict):
                    raise ValueError(f"{path} must be an object")
                self._merge(d, v, path + ".", strict)
                continue
            if isinstance(v, str) and v == "••••set":
                continue                                   # masked secret sent back unchanged
            dst[k] = self._coerce(path, d, v)

    @staticmethod
    def _coerce(path, default, v):
        try:
            if isinstance(default, bool):
                if not isinstance(v, bool):
                    raise TypeError
            elif isinstance(default, int):
                if isinstance(v, bool):
                    raise TypeError
                v = int(round(float(v)))
            elif isinstance(default, float):
                if isinstance(v, bool):
                    raise TypeError
                v = float(v)
            elif isinstance(default, str):
                v = str(v).strip()
        except (TypeError, ValueError):
            raise ValueError(f"{path} must be a {type(default).__name__}")
        if path in BOUNDS:
            lo, hi = BOUNDS[path]
            if not (lo <= v <= hi):
                raise ValueError(f"{path} must be between {lo} and {hi}")
        if path in CHOICES and v not in CHOICES[path]:
            raise ValueError(f"{path} must be one of {', '.join(CHOICES[path])}")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            raise ValueError(f"{path} can't be negative")
        return v
