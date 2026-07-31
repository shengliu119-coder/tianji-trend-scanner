from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


CN_TZ = ZoneInfo("Asia/Shanghai")
USER_AGENT = "tianji-trend-scanner/clean-v1"
HTTP_TIMEOUT = 20
MODEL_NAME = "澶╂満浼忓嚮路A/B瓒嬪娍璧风垎妯″瀷"
PORTFOLIO_NAME = "crypto-trend-scanner"

DEFAULT_SYMBOLS = [
    "FARTCOINUSDT",
    "UNIUSDT",
    "ADAUSDT",
    "ETHUSDT",
    "HYPEUSDT",
    "EIGENUSDT",
    "DASHUSDT",
    "BCHUSDT",
    "PUMPUSDT",
    "SEIUSDT",
    "LINKUSDT",
    "PEPEUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "PENGUUSDT",
    "ZECUSDT",
    "BONKUSDT",
    "CRVUSDT",
    "BTCUSDT",
    "TRUMPUSDT",
    "XAUTUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "VIRTUALUSDT",
    "SUIUSDT",
    "OKBUSDT",
    "AAVEUSDT",
    "WIFUSDT",
    "LTCUSDT",
    "ASTERUSDT",
    "ENAUSDT",
    "ETHFIUSDT",
    "ETCUSDT",
    "ONDOUSDT",
    "HBARUSDT",
    "GIGGLEUSDT",
    "KOMAUSDT",
    "GOATUSDT",
    "LIGHTUSDT",
    "NEIROUSDT",
]

SYMBOL_MAP = {
    "PEPEUSDT": "1000PEPEUSDT",
    "BONKUSDT": "1000BONKUSDT",
}

PRIMARY_SYMBOL = "ETHUSDT"
BTC_SYMBOL = "BTCUSDT"

SETUP_PATHS = {
    "15m": {"trigger": "15m", "higher": ["1h", "2h", "4h"]},
    "1h": {"trigger": "15m", "higher": ["2h", "4h"]},
    "2h": {"trigger": "15m", "higher": ["4h"]},
    "4h": {"trigger": "15m", "higher": ["1d"]},
}


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    model_name: str
    symbol: str
    actual_symbol: str
    direction: str
    grade: str
    status: str
    price: float
    entry_low: float
    entry_high: float
    invalid: float
    target1: float
    target2: float
    rr: float
    score: int
    market_state: str
    setup_tf: str
    trigger_tf: str
    setup_kind: str
    trigger_name: str
    reason: str
    action: str
    created_at: str

    @property
    def family_key(self) -> str:
        return f"{self.model_name}:{self.symbol}:{self.direction}"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def http_json(url: str, retries: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"request failed: {last_error}")


def http_post_json(url: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def load_config() -> dict[str, Any]:
    path = Path("config.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    config = config or {}
    config.setdefault("feishu", {})
    config.setdefault("scan", {})
    config.setdefault("crypto", {})
    config.setdefault("trend_pullback", {})
    config["feishu"].setdefault("enabled", True)
    config["feishu"].setdefault("webhook_env", "FEISHU_WEBHOOK")
    config["feishu"].setdefault("dry_run_env", "DRY_RUN")
    config["scan"].setdefault("state_file", "state/signals.json")
    config["scan"].setdefault("trade_ledger_file", "state/trades.jsonl")
    config["scan"].setdefault("performance_file", "state/performance.json")
    config["scan"].setdefault("performance_report", "reports/performance.md")
    config["scan"].setdefault("min_rr", 3.0)
    config["scan"].setdefault("max_distance_to_entry_pct", 2.0)
    config["scan"].setdefault("expiry_hours", 12)
    config["crypto"].setdefault("enabled", True)
    config["crypto"].setdefault("symbols", DEFAULT_SYMBOLS)
    config["crypto"].setdefault("symbol_map", SYMBOL_MAP)
    config["crypto"].setdefault("okx_discovery_enabled", True)
    config["crypto"].setdefault("okx_discovery_max_symbols", 30)
    config["crypto"].setdefault("okx_discovery_min_change_pct", 2.0)
    config["crypto"].setdefault("okx_discovery_min_volume_ccy", 300000.0)
    cfg = config["trend_pullback"]
    cfg.setdefault("max_retracement", 0.618)
    cfg.setdefault("min_impulse_atr", 1.35)
    cfg.setdefault("entry_trigger_atr_tolerance", 0.35)
    cfg.setdefault("ema52_retest_atr_tolerance", 0.55)
    cfg.setdefault("invalidation_atr_buffer", 0.18)
    cfg.setdefault("min_trend_pullback_bars", 4)
    cfg.setdefault("min_trend_pullback_depth_atr", 0.75)
    cfg.setdefault("min_trend_pullback_legs", 2)
    cfg.setdefault("trend_pullback_late_high_atr", 0.45)
    cfg.setdefault("same_tf_zero_axis_dif_atr", 0.16)
    cfg.setdefault("same_tf_zero_axis_hist_atr", 0.12)
    cfg.setdefault("prior_level_retest_atr_tolerance", 0.65)
    cfg.setdefault("zero_axis_consolidation_min_bars", 8)
    cfg.setdefault("zero_axis_consolidation_max_bars", 24)
    cfg.setdefault("zero_axis_max_entry_atr", 1.25)
    cfg.setdefault("zero_axis_confirm_bars", 2)
    cfg.setdefault("zero_axis_confirm_hist_atr", 0.025)
    cfg.setdefault("zero_axis_confirm_dea_atr", 0.025)
    cfg.setdefault("vegas_zero_axis_max_entry_atr", 1.6)
    cfg.setdefault("neckline_retest_max_entry_atr", 2.4)
    cfg.setdefault("impulse_box_min_bars", 6)
    cfg.setdefault("impulse_box_max_bars", 24)
    cfg.setdefault("impulse_box_min_impulse_atr", 3.0)
    cfg.setdefault("impulse_box_min_impulse_pct", 5.0)
    cfg.setdefault("impulse_box_max_width_atr", 4.2)
    cfg.setdefault("impulse_box_max_width_pct", 8.0)
    cfg.setdefault("impulse_box_max_entry_atr", 1.35)
    cfg.setdefault("impulse_box_max_rsi", 76.0)
    return config


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"signals": {}, "meta": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"signals": {}, "meta": {}}


def save_state(path: str, state: dict[str, Any]) -> None:
    ensure_parent(path)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: str, row: dict[str, Any]) -> None:
    ensure_parent(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: str, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1 - alpha))
    return out


def macd(values: list[float]) -> tuple[list[float], list[float], list[float]]:
    fast = ema(values, 12)
    slow = ema(values, 26)
    dif = [a - b for a, b in zip(fast, slow)]
    dea = ema(dif, 9)
    hist = [a - b for a, b in zip(dif, dea)]
    return dif, dea, hist


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) < 2:
        return [50.0] * len(values)
    gains = [0.0]
    losses = [0.0]
    for prev, cur in zip(values, values[1:]):
        diff = cur - prev
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    out: list[float] = []
    for i in range(len(values)):
        if i < period:
            out.append(50.0)
            continue
        avg_gain = sum(gains[i - period + 1 : i + 1]) / period
        avg_loss = sum(losses[i - period + 1 : i + 1]) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100 - 100 / (1 + rs))
    return out


def average_true_range(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 2:
        return 0.0
    trs = []
    completed = candles[:-1]
    for prev, cur in zip(completed[-period - 1 : -1], completed[-period:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / len(trs) if trs else 0.0


def summarize(candles: list[Candle]) -> dict[str, float]:
    closes = [c.close for c in candles]
    if len(closes) < 60:
        raise ValueError("not enough candles")
    dif, dea, hist = macd(closes)
    return {
        "open": candles[-1].open,
        "high": candles[-1].high,
        "low": candles[-1].low,
        "close": candles[-1].close,
        "ema20": ema(closes, 20)[-1],
        "ema24": ema(closes, 24)[-1],
        "ema52": ema(closes, 52)[-1],
        "ema144": ema(closes, 144)[-1],
        "ema169": ema(closes, 169)[-1],
        "dif": dif[-1],
        "dea": dea[-1],
        "hist": hist[-1],
        "hist_prev": hist[-2],
        "rsi": rsi(closes)[-1],
        "atr": average_true_range(candles),
        "recent_high": max(c.high for c in candles[-40:-1]),
        "recent_low": min(c.low for c in candles[-40:-1]),
    }


def binance_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    qs = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = f"https://fapi.binance.com/fapi/v1/markPriceKlines?{qs}"
    rows = http_json(url)
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]


def okx_inst_id(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    if base.startswith("1000"):
        base = base[4:]
    return f"{base}-USDT-SWAP"


def okx_bar(interval: str) -> str:
    return {
        "15m": "15m",
        "1h": "1H",
        "2h": "2H",
        "4h": "4H",
        "1d": "1D",
    }.get(interval, interval)


def okx_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    qs = urllib.parse.urlencode({"instId": okx_inst_id(symbol), "bar": okx_bar(interval), "limit": limit})
    url = f"https://www.okx.com/api/v5/market/mark-price-candles?{qs}"
    payload = http_json(url)
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX kline failed: {payload}")
    rows = sorted(payload.get("data", []), key=lambda r: int(r[0]))
    candles: list[Candle] = []
    for r in rows:
        candles.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), 0.0))
    return candles


def crypto_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    try:
        return binance_klines(symbol, interval, limit)
    except Exception as binance_exc:  # noqa: BLE001
        try:
            return okx_klines(symbol, interval, limit)
        except Exception as okx_exc:  # noqa: BLE001
            raise RuntimeError(f"Binance and OKX both failed: Binance={binance_exc}; OKX={okx_exc}") from okx_exc


def binance_24h_tickers() -> dict[str, dict[str, Any]]:
    try:
        rows = http_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
        return {str(row["symbol"]): row for row in rows}
    except Exception as exc:  # noqa: BLE001
        print(f"Binance 24h ticker unavailable, using OKX fallback: {exc}", file=sys.stderr)
        payload = http_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP")
        if str(payload.get("code")) != "0":
            raise RuntimeError(f"OKX tickers failed: {payload}")
        tickers: dict[str, dict[str, Any]] = {}
        for row in payload.get("data", []):
            inst_id = str(row.get("instId", ""))
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            base = inst_id.replace("-USDT-SWAP", "")
            symbol = f"{base}USDT"
            tickers[symbol] = row
            if symbol in {"PEPEUSDT", "BONKUSDT"}:
                tickers[f"1000{symbol}"] = row
        return tickers


def okx_24h_tickers() -> dict[str, dict[str, Any]]:
    payload = http_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP")
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX tickers failed: {payload}")
    tickers: dict[str, dict[str, Any]] = {}
    for row in payload.get("data", []):
        inst_id = str(row.get("instId", ""))
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        base = inst_id.replace("-USDT-SWAP", "")
        symbol = f"{base}USDT"
        tickers[symbol] = row
    return tickers


def okx_change_pct(row: dict[str, Any]) -> float:
    try:
        last = float(row.get("last") or 0)
        open24h = float(row.get("open24h") or 0)
    except (TypeError, ValueError):
        return 0.0
    return (last - open24h) / open24h * 100 if open24h > 0 else 0.0


def okx_volume_ccy(row: dict[str, Any]) -> float:
    for key in ("volCcy24h", "volCcy", "vol24h"):
        try:
            return float(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def discover_okx_symbols(config: dict[str, Any]) -> list[str]:
    crypto_cfg = config["crypto"]
    if not crypto_cfg.get("okx_discovery_enabled", True):
        return []
    max_symbols = int(crypto_cfg.get("okx_discovery_max_symbols", 30))
    min_change = float(crypto_cfg.get("okx_discovery_min_change_pct", 2.0))
    min_volume = float(crypto_cfg.get("okx_discovery_min_volume_ccy", 300000.0))
    try:
        rows = okx_24h_tickers()
    except Exception as exc:  # noqa: BLE001
        print(f"OKX discovery unavailable: {exc}", file=sys.stderr)
        return []
    candidates = [
        (symbol, okx_change_pct(row), okx_volume_ccy(row))
        for symbol, row in rows.items()
    ]
    candidates = [
        item
        for item in candidates
        if item[1] >= min_change and item[2] >= min_volume and item[0] not in {"BTCUSDT", "ETHUSDT"}
    ]
    candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
    return [symbol for symbol, _, _ in candidates[:max_symbols]]


def merge_symbols(primary: list[str], discovered: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for symbol in primary + discovered:
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def fetch_bundle(actual_symbol: str) -> tuple[dict[str, dict[str, float]], dict[str, list[Candle]]]:
    candle_map = {tf: crypto_klines(actual_symbol, tf, 240) for tf in ["15m", "1h", "2h", "4h", "1d"]}
    return {tf: summarize(candles) for tf, candles in candle_map.items()}, candle_map


def market_bias(frame: dict[str, float], direction: str) -> str:
    if direction == "long":
        strong = frame["close"] > frame["ema52"] and frame["ema24"] >= frame["ema52"] and frame["hist"] >= frame["hist_prev"]
        weak = frame["close"] < frame["ema52"] and frame["ema24"] < frame["ema52"] and frame["hist"] < frame["hist_prev"]
    else:
        strong = frame["close"] < frame["ema52"] and frame["ema24"] <= frame["ema52"] and frame["hist"] <= frame["hist_prev"]
        weak = frame["close"] > frame["ema52"] and frame["ema24"] > frame["ema52"] and frame["hist"] > frame["hist_prev"]
    if strong:
        return "aligned"
    if weak:
        return "opposite"
    return "neutral"


def higher_context(bundle: dict[str, dict[str, float]], setup_tf: str, direction: str) -> dict[str, bool | int]:
    higher = SETUP_PATHS[setup_tf]["higher"]
    biases = [market_bias(bundle[tf], direction) for tf in higher if tf in bundle]
    opposite = biases.count("opposite")
    aligned = biases.count("aligned")
    return {
        "hard_opposite": opposite >= 1,
        "a_ok": not biases or (opposite == 0 and aligned >= 1),
        "b_ok": opposite == 0,
        "aligned": aligned,
        "opposite": opposite,
    }


def local_start_protects_against(bundle: dict[str, dict[str, float]], direction: str) -> bool:
    frames = [bundle[tf] for tf in ("1h", "2h") if tf in bundle]
    if not frames:
        return False
    if direction == "short":
        return any(
            frame["close"] > frame["ema52"]
            and frame["ema24"] >= frame["ema52"]
            and frame["dif"] > 0
            and frame["hist"] >= frame["hist_prev"]
            and frame["low"] >= frame["ema52"] - frame["atr"] * 0.35
            for frame in frames
        )
    return any(
        frame["close"] < frame["ema52"]
        and frame["ema24"] <= frame["ema52"]
        and frame["dif"] < 0
        and frame["hist"] <= frame["hist_prev"]
        and frame["high"] <= frame["ema52"] + frame["atr"] * 0.35
        for frame in frames
    )


def local_direction_score(bundle: dict[str, dict[str, float]], direction: str) -> int:
    score = 0
    for tf in ("1h", "2h", "4h"):
        if tf not in bundle:
            continue
        if market_bias(bundle[tf], direction) == "aligned":
            score += 1
    return score


def is_btc(symbol: str) -> bool:
    return symbol == BTC_SYMBOL


def is_eth(symbol: str) -> bool:
    return symbol == PRIMARY_SYMBOL


def is_alt(symbol: str) -> bool:
    return symbol not in {BTC_SYMBOL, PRIMARY_SYMBOL}


def has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(item in text for item in keywords)


def disabled_c_trigger(trigger_name: str) -> bool:
    return has_any(
        trigger_name,
        (
            "\u53cc\u5e95",
            "\u5047\u8dcc\u7834",
            "\u6536\u56de",
            "2b_false_breakdown",
            "double_bottom",
        ),
    )


def weak_reversal_trigger(trigger_name: str) -> bool:
    return has_any(
        trigger_name,
        (
            "\u53cc\u5e95",
            "\u53cc\u9876",
            "\u62ac\u9ad8\u4f4e\u70b9",
            "\u964d\u4f4e\u9ad8\u70b9",
            "\u5047\u8dcc\u7834",
            "\u5047\u7a81\u7834",
            "\u6536\u56de",
            "\u627f\u538b",
            "double_bottom",
            "double_top",
            "higher_low",
            "lower_high",
        ),
    )


def macd_standalone_trigger(trigger_name: str) -> bool:
    return "MACD" in trigger_name


def pressure_short_trigger(trigger_name: str) -> bool:
    return has_any(
        trigger_name,
        (
            "2B",
            "lower_high",
            "lower_high_retest",
            "downtrend_retest_short",
            "2b_false_breakout",
            "breakdown_retest",
            "retest_short",
            "rejection",
        ),
    )
def two_hour_a_allowed(
    direction: str,
    trigger_name: str,
    setup: dict[str, Any],
    bundle: dict[str, dict[str, float]],
    gap: float,
    score: int,
) -> bool:
    if direction == "long" and bool(setup.get("zero_axis_ignition")):
        return gap <= 0.8 and score >= 90 and local_direction_score(bundle, direction) >= 2
    if macd_standalone_trigger(trigger_name):
        return False
    if not bool(setup.get("ema52")) or not bool(setup.get("macd")):
        return False
    if gap > 0.8 or score < 92:
        return False
    if direction == "short" and pressure_short_trigger(trigger_name):
        return local_direction_score(bundle, direction) >= 1
    return local_direction_score(bundle, direction) >= 2


def alt_small_tf_long_reversal(bundle: dict[str, dict[str, float]]) -> bool:
    for tf in ("15m", "1h"):
        frame = bundle.get(tf)
        if not frame:
            continue
        if (
            frame["close"] >= frame["ema24"] >= frame["ema52"]
            and frame["dif"] >= frame["dea"] - frame["atr"] * 0.02
            and frame["hist"] >= frame["hist_prev"]
            and frame["rsi"] >= 45
        ):
            return True
    return False


def alt_long_confirmed(bundle: dict[str, dict[str, float]]) -> bool:
    if not alt_small_tf_long_reversal(bundle):
        return False
    for tf in ("1h", "2h"):
        frame = bundle.get(tf)
        if not frame:
            continue
        if frame["ema24"] > frame["ema52"] and frame["close"] >= frame["ema52"] and frame["dif"] >= 0 and frame["hist"] >= frame["hist_prev"]:
            return True
    return False


def alt_short_confirmed(bundle: dict[str, dict[str, float]], setup: dict[str, Any], trigger_name: str) -> bool:
    pressure_retest = bool(setup.get("ema52")) or has_any(
        trigger_name,
        (
            "lower_high",
            "lower_high_retest",
            "downtrend_retest_short",
            "breakdown_retest",
            "rejection",
            "retest_short",
        ),
    )
    local_short = local_direction_score(bundle, "short") >= 2
    return pressure_retest and local_short


def bottom_box_setup(setup: dict[str, Any]) -> bool:
    return "box_high" in setup or has_any(
        str(setup.get("kind", "")),
        ("\u7bb1\u4f53", "\u76d8\u6574\u7bb1\u4f53", "box"),
    )


def local_countertrend_veto(bundle: dict[str, dict[str, float]], direction: str) -> bool:
    if direction == "short":
        if local_direction_score(bundle, "long") >= 2:
            return True
        for tf in ("1h", "2h"):
            frame = bundle.get(tf)
            if frame and frame["close"] > frame["ema24"] > frame["ema52"] and frame["dif"] > 0:
                return True
        return False

    if local_direction_score(bundle, "short") >= 2:
        return True
    for tf in ("1h", "2h"):
        frame = bundle.get(tf)
        if frame and frame["close"] < frame["ema24"] < frame["ema52"] and frame["dif"] < 0:
            return True
    return False


def alt_stage_allows_a(setup_tf: str, setup: dict[str, Any], bundle: dict[str, dict[str, float]], direction: str) -> bool:
    if direction == "long" and bool(setup.get("zero_axis_ignition")):
        if setup_tf == "4h":
            return False
        return setup_tf == "2h" and local_direction_score(bundle, "long") >= 2
    if direction == "short":
        return setup_tf in {"2h", "4h"} and local_direction_score(bundle, "short") >= 2
    if direction == "long" and bottom_box_setup(setup):
        return local_direction_score(bundle, "long") >= 1
    if setup_tf == "1h":
        return False
    return local_direction_score(bundle, direction) >= 2
def trigger_near_setup_key(
    setup_tf: str,
    setup: dict[str, Any],
    bundle: dict[str, dict[str, float]],
    trigger: dict[str, Any],
    direction: str,
) -> bool:
    level = float(trigger["level"])
    trigger_name = str(trigger["name"])
    setup_frame = bundle.get(setup_tf)
    if not setup_frame:
        return False

    setup_atr = max(setup_frame["atr"], level * 0.002)
    if bool(setup.get("impulse_box")):
        box_low = float(setup.get("box_low", level))
        box_high = float(setup.get("box_high", level))
        return direction == "long" and box_low - setup_atr * 0.75 <= level <= box_high + setup_atr * 0.45
    if bottom_box_setup(setup):
        box_high = float(setup.get("box_high", level))
        if direction == "long":
            return abs(level - box_high) <= setup_atr * 0.9 or level >= box_high - setup_atr * 0.45
        return False

    near_setup_ema = abs(level - setup_frame["ema52"]) <= setup_atr * 1.2 or abs(level - setup_frame["ema24"]) <= setup_atr * 1.0
    if direction == "long":
        return near_setup_ema or has_any(trigger_name, ("鍥炶俯", "MACD"))
    return near_setup_ema or has_any(trigger_name, ("鍙嶆娊", "鎵垮帇", "MACD", "lower_high", "lower_high_retest", "breakdown_retest"))
def long_key_level_acceptance(candles: list[Candle], level: float) -> bool:
    completed = candles[:-1]
    if len(completed) < 8:
        return False
    atr = average_true_range(candles)
    last, prev = completed[-1], completed[-2]
    body = max(abs(last.close - last.open), atr * 0.05)
    candle_range = max(last.high - last.low, atr * 0.05)
    lower_wick = min(last.close, last.open) - last.low
    near_level = abs(last.low - level) <= atr * 0.35 or last.low <= level <= last.high
    not_chasing = (last.close - level) <= atr * 0.55
    pinbar = lower_wick >= body * 1.5 and last.close >= last.open and (last.close - last.low) / candle_range >= 0.55
    reclaim = last.close > last.open and last.close > max(prev.high, level + atr * 0.03) and last.low <= level + atr * 0.35
    return near_level and not_chasing and (pinbar or reclaim)


def short_key_level_rejection(candles: list[Candle], level: float) -> bool:
    completed = candles[:-1]
    if len(completed) < 8:
        return False
    atr = average_true_range(candles)
    last, prev = completed[-1], completed[-2]
    body = max(abs(last.close - last.open), atr * 0.05)
    candle_range = max(last.high - last.low, atr * 0.05)
    upper_wick = last.high - max(last.close, last.open)
    near_level = abs(last.high - level) <= atr * 0.35 or last.low <= level <= last.high
    not_chasing = (level - last.close) <= atr * 0.55
    pinbar = upper_wick >= body * 1.5 and last.close <= last.open and (last.high - last.close) / candle_range >= 0.55
    rejection = last.close < last.open and last.close < min(prev.low, level - atr * 0.03) and last.high >= level - atr * 0.35
    return near_level and not_chasing and (pinbar or rejection)


def detect_market_state(btc: dict[str, dict[str, float]], eth: dict[str, dict[str, float]]) -> str:
    btc_4h, eth_4h, btc_1h = btc["4h"], eth["4h"], btc["1h"]
    btc_weak = btc_4h["close"] < btc_4h["ema52"] and btc_4h["hist"] < btc_4h["hist_prev"]
    eth_weak = eth_4h["close"] < eth_4h["ema52"] and eth_4h["hist"] < eth_4h["hist_prev"]
    btc_strong = btc_4h["close"] > btc_4h["ema52"] and btc_4h["hist"] >= btc_4h["hist_prev"]
    eth_strong = eth_4h["close"] > eth_4h["ema52"] and eth_4h["hist"] >= eth_4h["hist_prev"]
    if btc_1h["close"] < btc_1h["ema52"] and btc_1h["rsi"] < 32:
        return "\u6025\u8dcc"
    if btc_weak and eth_weak:
        return "\u5f31"
    if btc_strong and eth_strong:
        return "\u5f3a"
    return "\u9707\u8361"


def pivot_indices(values: list[float], side: str, radius: int = 2) -> list[int]:
    out = []
    for i in range(radius, len(values) - radius):
        window = values[i - radius : i + radius + 1]
        if side == "high" and values[i] == max(window):
            out.append(i)
        if side == "low" and values[i] == min(window):
            out.append(i)
    return out


def countertrend_leg_count(candles: list[Candle], direction: str, atr: float) -> int:
    if len(candles) < 2:
        return 0
    threshold = max(atr * 0.25, candles[-1].close * 0.001)
    legs = 0
    move = 0.0
    in_leg = False
    for prev, cur in zip(candles, candles[1:]):
        delta = cur.close - prev.close
        counter = delta < 0 if direction == "long" else delta > 0
        if counter:
            move += abs(delta)
            in_leg = True
            continue
        if in_leg and move >= threshold:
            legs += 1
        move = 0.0
        in_leg = False
    if in_leg and move >= threshold:
        legs += 1
    return legs


def trend_pullback_mature(
    pullback: list[Candle],
    direction: str,
    atr: float,
    cfg: dict[str, Any],
    impulse_extreme: float,
) -> bool:
    if not pullback or atr <= 0:
        return False
    min_bars = int(cfg.get("min_trend_pullback_bars", 4))
    min_depth = atr * float(cfg.get("min_trend_pullback_depth_atr", 0.75))
    min_legs = int(cfg.get("min_trend_pullback_legs", 2))
    late_atr = atr * float(cfg.get("trend_pullback_late_high_atr", 0.45))
    if len(pullback) < min_bars:
        return False
    if direction == "long":
        depth = impulse_extreme - min(c.low for c in pullback)
        if depth < min_depth:
            return False
        if impulse_extreme - pullback[-1].close < late_atr:
            return False
    else:
        depth = max(c.high for c in pullback) - impulse_extreme
        if depth < min_depth:
            return False
        if pullback[-1].close - impulse_extreme < late_atr:
            return False
    return countertrend_leg_count(pullback, direction, atr) >= min_legs


def same_timeframe_zero_axis_turn(
    dif: list[float],
    dea: list[float],
    hist: list[float],
    direction: str,
    atr: float,
    cfg: dict[str, Any],
) -> bool:
    if len(dif) < 14 or atr <= 0:
        return False
    dif_tol = atr * float(cfg.get("same_tf_zero_axis_dif_atr", 0.16))
    hist_tol = atr * float(cfg.get("same_tf_zero_axis_hist_atr", 0.12))
    zero_reset = min(abs(x) for x in dif[-12:]) <= dif_tol or min(abs(x) for x in hist[-12:]) <= hist_tol
    if direction == "long":
        turn = hist[-1] > hist[-2] and dif[-1] >= dea[-1] - dif_tol * 0.25 and dif[-1] > -dif_tol
    else:
        turn = hist[-1] < hist[-2] and dif[-1] <= dea[-1] + dif_tol * 0.25 and dif[-1] < dif_tol
    return zero_reset and turn


def higher_timeframe_zero_axis_support(
    candle_map: dict[str, list[Candle]],
    direction: str,
    cfg: dict[str, Any],
) -> bool:
    if direction != "long":
        return False
    confirm_bars = max(2, int(cfg.get("zero_axis_confirm_bars", 2)))
    for tf in ("1h", "2h", "4h"):
        candles = candle_map.get(tf)
        if not candles:
            continue
        completed = candles[:-1]
        if len(completed) < 80:
            continue
        closes = [c.close for c in completed]
        ema24 = ema(closes, 24)
        ema52 = ema(closes, 52)
        dif, dea, hist = macd(closes)
        atr = average_true_range(candles)
        if atr <= 0:
            continue

        reset_dif = dif[-(confirm_bars + 12) : -confirm_bars]
        reset_hist = hist[-(confirm_bars + 12) : -confirm_bars]
        if not reset_dif:
            continue
        zero_reset = (
            min(abs(x) for x in reset_dif) <= atr * float(cfg.get("same_tf_zero_axis_dif_atr", 0.16))
            or min(abs(x) for x in reset_hist) <= atr * float(cfg.get("same_tf_zero_axis_hist_atr", 0.12))
        )
        hist_confirm = all(
            x > atr * float(cfg.get("zero_axis_confirm_hist_atr", 0.025))
            for x in hist[-confirm_bars:]
        )
        dea_tol = atr * float(cfg.get("zero_axis_confirm_dea_atr", 0.025))
        dif_dea_confirm = all(dif[-i] >= dea[-i] - dea_tol for i in range(1, confirm_bars + 1))
        last = completed[-1]
        key_level = max(ema24[-1], ema52[-1])
        key_retest = last.low <= key_level + atr * 0.65 and last.close >= ema52[-1] - atr * 0.2
        if zero_reset and hist_confirm and dif_dea_confirm and key_retest:
            return True
    return False


def find_trend_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    completed = candles[:-1]
    if len(completed) < 90:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    max_ret = float(cfg.get("max_retracement", 0.618))
    min_impulse_atr = float(cfg.get("min_impulse_atr", 1.35))
    ema_tol = float(cfg.get("ema52_retest_atr_tolerance", 0.55))
    recent = completed[-72:]
    price = completed[-1].close

    if direction == "long":
        trend_ok = ema52[-1] >= ema52[-8] and price >= ema52[-1] - atr * 0.2
        if not trend_ok:
            return None
        impulse_start = min(c.low for c in recent[:-5])
        peak_pos = recent.index(max(recent[:-2], key=lambda c: c.high))
        impulse_high = recent[peak_pos].high
        amplitude = impulse_high - impulse_start
        pullback = recent[peak_pos + 1 :]
        pullback_low = min(c.low for c in pullback or recent[-10:])
        if amplitude <= atr * min_impulse_atr:
            return None
        retracement = (impulse_high - pullback_low) / amplitude
        prior_high = max(c.high for c in recent[:peak_pos] or recent[:1])
        prior_level_touch = (
            pullback_low <= prior_high + atr * float(cfg.get("prior_level_retest_atr_tolerance", 0.65))
            and min(c.close for c in pullback[-8:] or pullback or recent[-8:]) >= prior_high - atr * 0.35
        )
        touched_ema52 = any(c.low <= ema52[-len(recent) + i] + atr * ema_tol and c.close >= ema52[-len(recent) + i] - atr * 0.25 for i, c in enumerate(recent[-12:], start=len(recent) - 12))
        key_retest = touched_ema52 or prior_level_touch
        macd_reset = same_timeframe_zero_axis_turn(dif, dea, hist, "long", atr, cfg)
        mature_pullback = trend_pullback_mature(pullback, "long", atr, cfg, impulse_high)
        if retracement > max_ret or retracement < 0.03 or not mature_pullback or not key_retest or not macd_reset:
            return None
        return {"kind": "瓒嬪娍鍥炶俯", "target": impulse_high, "invalid_base": pullback_low, "retracement": retracement, "ema52": key_retest, "macd": macd_reset, "pullback_legs": countertrend_leg_count(pullback, "long", atr)}

    trend_ok = ema52[-1] <= ema52[-8] and price <= ema52[-1] + atr * 0.2
    if not trend_ok:
        return None
    impulse_start = max(c.high for c in recent[:-5])
    trough_pos = recent.index(min(recent[:-2], key=lambda c: c.low))
    impulse_low = recent[trough_pos].low
    amplitude = impulse_start - impulse_low
    pullback = recent[trough_pos + 1 :]
    rebound_high = max(c.high for c in pullback or recent[-10:])
    if amplitude <= atr * min_impulse_atr:
        return None
    retracement = (rebound_high - impulse_low) / amplitude
    prior_low = min(c.low for c in recent[:trough_pos] or recent[:1])
    prior_level_touch = (
        rebound_high >= prior_low - atr * float(cfg.get("prior_level_retest_atr_tolerance", 0.65))
        and max(c.close for c in pullback[-8:] or pullback or recent[-8:]) <= prior_low + atr * 0.35
    )
    touched_ema52 = any(c.high >= ema52[-len(recent) + i] - atr * ema_tol and c.close <= ema52[-len(recent) + i] + atr * 0.25 for i, c in enumerate(recent[-12:], start=len(recent) - 12))
    key_retest = touched_ema52 or prior_level_touch
    macd_reset = same_timeframe_zero_axis_turn(dif, dea, hist, "short", atr, cfg)
    mature_pullback = trend_pullback_mature(pullback, "short", atr, cfg, impulse_low)
    if retracement > max_ret or retracement < 0.03 or not mature_pullback or not key_retest or not macd_reset:
        return None
    return {"kind": "鍙嶅脊鎵垮帇", "target": impulse_low, "invalid_base": rebound_high, "retracement": retracement, "ema52": key_retest, "macd": macd_reset, "pullback_legs": countertrend_leg_count(pullback, "short", atr)}


def find_bottom_box_breakout_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if direction != "long":
        return None
    completed = candles[:-1]
    if len(completed) < 90:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    box = completed[-72:-10]
    recent = completed[-10:]
    box_high = max(c.high for c in box)
    box_low = min(c.low for c in box)
    box_mid = (box_high + box_low) / 2
    box_width = box_high - box_low
    if box_width <= 0 or box_width > atr * 12:
        return None

    low_touches = sum(1 for c in box[-48:] if c.low <= box_low + atr * 0.8)
    if low_touches < 2:
        return None

    breakout_seen = any(c.close > box_high + atr * 0.12 for c in recent[:-1])
    last = completed[-1]
    retest_ok = min(c.low for c in recent[-6:]) <= box_high + atr * 0.7 and last.close >= box_high - atr * 0.2
    trend_turn = last.close > ema52[-1] and ema24[-1] >= ema52[-1] - atr * 0.12 and dif[-1] >= dea[-1] and dif[-1] > -atr * 0.08
    not_overextended = (last.close - box_high) <= atr * 2.2
    if not (breakout_seen and retest_ok and trend_turn and not_overextended):
        return None

    recent_lows = [c.low for c in recent]
    return {
        "kind": "搴曢儴绠变綋绐佺牬鍥炶俯",
        "target": max(box_high + box_width, max(c.high for c in recent)),
        "invalid_base": min(min(recent_lows), box_high - atr * 0.35),
        "retracement": 0.0,
        "ema52": True,
        "macd": hist[-1] >= hist[-2],
        "box_high": box_high,
        "box_low": box_low,
        "box_mid": box_mid,
    }


def find_downtrend_retest_short_setup(candles: list[Candle], cfg: dict[str, Any]) -> dict[str, Any] | None:
    completed = candles[:-1]
    if len(completed) < 160:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    ema144 = ema(closes, 144)
    ema169 = ema(closes, 169)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    recent = completed[-48:]
    prior = completed[-120:-48]
    last = completed[-1]
    vegas_top = max(ema144[-1], ema169[-1])

    trend_ok = ema52[-1] <= ema52[-8] and ema24[-1] <= ema52[-1] + atr * 0.15 and last.close <= ema24[-1] + atr * 0.45
    if not trend_ok:
        return None

    impulse_high = max(c.high for c in recent[:-4])
    trough_pos = recent.index(min(recent[:-3], key=lambda c: c.low))
    impulse_low = recent[trough_pos].low
    amplitude = impulse_high - impulse_low
    if amplitude <= atr * float(cfg.get("min_impulse_atr", 1.35)):
        return None

    pullback = recent[trough_pos + 1 :]
    if len(pullback) < int(cfg.get("min_trend_pullback_bars", 4)):
        return None

    rebound_high = max(c.high for c in pullback)
    retracement = (rebound_high - impulse_low) / amplitude
    if retracement < 0.28 or retracement > float(cfg.get("max_retracement", 0.618)):
        return None

    prior_high = max(c.high for c in prior)
    key_level = max(ema24[-1], ema52[-1], vegas_top, prior_high - atr * 0.15)
    touched_key = rebound_high >= key_level - atr * 0.25
    rejection = (
        last.close <= key_level + atr * 0.12
        and last.close < last.open
        and last.high >= key_level - atr * 0.18
    )
    macd_reset = same_timeframe_zero_axis_turn(dif, dea, hist, "short", atr, cfg)
    mature_pullback = trend_pullback_mature(pullback, "short", atr, cfg, impulse_low)
    if not (touched_key and rejection and macd_reset and mature_pullback):
        return None

    invalid_base = max(rebound_high, prior_high) + atr * 0.18
    target = min(impulse_low, last.close - atr * 2.0)
    return {
        "kind": "downtrend_retest_short",
        "target": target,
        "invalid_base": invalid_base,
        "retracement": retracement,
        "ema52": True,
        "macd": True,
        "direct_trigger": {
            "name": "downtrend_retest_short",
            "level": key_level,
            "invalid": invalid_base,
            "quality": 13,
            "confirmed": True,
        },
    }


def find_neckline_retest_zero_axis_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if direction != "long":
        return None
    completed = candles[:-1]
    if len(completed) < 160:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    ema144 = ema(closes, 144)
    ema169 = ema(closes, 169)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    recent = completed[-30:]
    prior = completed[-110:-30]
    last = completed[-1]
    vegas_top = max(ema144[-1], ema169[-1])
    neckline = max(vegas_top, ema52[-1] - atr * 0.25)

    impulse_high = max(c.high for c in recent[:-3])
    retest_low = min(c.low for c in recent[-10:])
    retest_close_low = min(c.close for c in recent[-10:])
    old_low = min(c.low for c in prior)
    old_high = max(c.high for c in prior)

    broke_neckline = impulse_high >= neckline + atr * 1.6
    retested_neckline = retest_low <= neckline + atr * 0.95 and retest_close_low >= neckline - atr * 0.45
    not_chasing = last.close <= neckline + atr * float(cfg.get("neckline_retest_max_entry_atr", 2.4))
    trend_repaired = last.close >= ema52[-1] - atr * 0.15 and ema24[-1] >= ema52[-1] - atr * 0.55
    macd_zero_turn = abs(dif[-1]) <= atr * 0.55 and hist[-1] >= hist[-2] and hist[-1] > -atr * 0.12
    reversal_context = old_high - old_low >= atr * 3.0 and neckline > old_low + atr * 1.2
    if not (broke_neckline and retested_neckline and not_chasing and trend_repaired and macd_zero_turn and reversal_context):
        return None

    return {
        "kind": "4h_neckline_retest_zero_axis",
        "target": max(impulse_high, last.close + atr * 2.2),
        "invalid_base": min(retest_low, neckline - atr * 0.65),
        "retracement": 0.0,
        "ema52": True,
        "macd": True,
        "neckline_retest": True,
        "neckline": neckline,
        "box_high": neckline,
    }


def find_zero_axis_ema52_ignition_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if direction != "long":
        return None
    completed = candles[:-1]
    if len(completed) < 100:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    min_bars = int(cfg.get("zero_axis_consolidation_min_bars", 8))
    max_bars = int(cfg.get("zero_axis_consolidation_max_bars", 24))
    max_entry_atr = float(cfg.get("zero_axis_max_entry_atr", 1.25))
    confirm_bars = max(2, int(cfg.get("zero_axis_confirm_bars", 2)))
    hist_min = atr * float(cfg.get("zero_axis_confirm_hist_atr", 0.025))
    dea_tol = atr * float(cfg.get("zero_axis_confirm_dea_atr", 0.025))
    base = completed[-90:-max_bars]
    if len(base) < 20:
        return None

    impulse_low = min(c.low for c in base[-48:])
    impulse_high = max(c.high for c in base[-48:])
    impulse = impulse_high - impulse_low
    if impulse <= atr * float(cfg.get("min_impulse_atr", 1.35)):
        return None

    best: dict[str, Any] | None = None
    for bars in range(min_bars, max_bars + 1):
        cons = completed[-bars:]
        prior = completed[-bars - 36 : -bars]
        if len(prior) < 12:
            continue
        cons_high = max(c.high for c in cons)
        cons_low = min(c.low for c in cons)
        cons_width = cons_high - cons_low
        prior_high = max(c.high for c in prior)
        prior_low = min(c.low for c in prior)
        prior_range = prior_high - prior_low
        if cons_width <= 0 or cons_width > max(atr * 5.0, cons_high * 0.08):
            continue
        if prior_range <= 0 or (prior_high - prior_low) < atr * 1.8:
            continue

        first_breakout = any(c.close > prior_high + atr * 0.15 for c in cons[: max(2, bars // 3)])
        if not first_breakout:
            continue
        ema_support_ok = all(
            c.close >= ema52[-bars + i] - atr * 0.18 and c.low >= ema52[-bars + i] - atr * 0.85
            for i, c in enumerate(cons)
        )
        if not ema_support_ok:
            continue

        macd_was_positive = max(dif[-bars - 10 : -bars + 1]) > atr * 0.05
        reset_end = -confirm_bars
        reset_start = max(-bars, reset_end - 8)
        reset_dif = dif[reset_start:reset_end]
        reset_hist = hist[reset_start:reset_end]
        zero_reset = bool(reset_dif) and (
            min(abs(x) for x in reset_dif) <= atr * 0.12
            or min(abs(x) for x in reset_hist) <= atr * 0.08
        )
        hist_confirm = all(x > hist_min for x in hist[-confirm_bars:])
        dif_dea_confirm = all(dif[-i] >= dea[-i] - dea_tol for i in range(1, confirm_bars + 1))
        turn_up = hist_confirm and dif_dea_confirm and hist[-1] >= hist[-2]
        if not (macd_was_positive and zero_reset and turn_up):
            continue
        if ema24[-1] < ema52[-1] - atr * 0.1:
            continue

        last = completed[-1]
        support = max(ema52[-1], cons_low)
        entry_level = max(support, min(last.close, ema52[-1] + atr * 0.35))
        if last.close - entry_level > atr * max_entry_atr:
            continue
        if rsi(closes)[-1] > 76:
            continue

        quality = 14
        if cons_width <= atr * 3.2:
            quality += 1
        if last.close >= cons_high - atr * 0.4:
            quality += 1
        candidate = {
            "kind": "zero_axis_ema52_ignition",
            "target": max(cons_high + cons_width, last.close + atr * 2.2),
            "invalid_base": min(cons_low, ema52[-1] - atr * 0.25),
            "retracement": 0.0,
            "ema52": True,
            "macd": True,
            "zero_axis_ignition": True,
            "direct_trigger": {
                "name": "zero_axis_ema52_ignition",
                "level": entry_level,
                "invalid": min(cons_low, ema52[-1] - atr * 0.25),
                "quality": quality,
                "confirmed": True,
            },
        }
        if best is None or candidate["direct_trigger"]["quality"] > best["direct_trigger"]["quality"]:
            best = candidate
    return best


def find_impulse_box_zero_axis_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if direction != "long":
        return None
    completed = candles[:-1]
    if len(completed) < 110:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    min_bars = int(cfg.get("impulse_box_min_bars", 6))
    max_bars = int(cfg.get("impulse_box_max_bars", 24))
    min_impulse_atr = float(cfg.get("impulse_box_min_impulse_atr", 3.0))
    min_impulse_pct = float(cfg.get("impulse_box_min_impulse_pct", 5.0))
    max_width_atr = float(cfg.get("impulse_box_max_width_atr", 4.2))
    max_width_pct = float(cfg.get("impulse_box_max_width_pct", 8.0))
    max_entry_atr = float(cfg.get("impulse_box_max_entry_atr", 1.35))
    max_rsi = float(cfg.get("impulse_box_max_rsi", 76.0))
    last = completed[-1]
    last_rsi = rsi(closes)[-1]
    if last_rsi > max_rsi:
        return None

    best: dict[str, Any] | None = None
    for bars in range(min_bars, max_bars + 1):
        box = completed[-bars:]
        prior = completed[-bars - 42 : -bars]
        if len(prior) < 24:
            continue

        prior_lows = [c.low for c in prior]
        prior_highs = [c.high for c in prior]
        low_pos = prior_lows.index(min(prior_lows))
        high_pos = prior_highs.index(max(prior_highs))
        if low_pos >= high_pos or high_pos < len(prior) // 2:
            continue

        impulse_low = prior_lows[low_pos]
        impulse_high = prior_highs[high_pos]
        impulse = impulse_high - impulse_low
        impulse_pct = impulse / impulse_low * 100 if impulse_low > 0 else 0.0
        if impulse < atr * min_impulse_atr or impulse_pct < min_impulse_pct:
            continue

        box_high = max(c.high for c in box)
        box_low = min(c.low for c in box)
        box_width = box_high - box_low
        if box_width <= 0:
            continue
        if box_width > atr * max_width_atr or box_width / box_high * 100 > max_width_pct:
            continue
        if box_low < impulse_low + impulse * 0.45:
            continue
        if box_high < impulse_high - max(atr * 1.2, box_high * 0.018):
            continue
        if last.close < box_low - atr * 0.15 or last.close > box_high + atr * 0.35:
            continue

        support_holds = all(
            c.close >= ema52[-bars + i] - atr * 0.30 and c.low >= ema52[-bars + i] - atr * 1.10
            for i, c in enumerate(box)
        )
        if not support_holds or ema24[-1] < ema52[-1] - atr * 0.20:
            continue

        macd_was_positive = max(dif[-bars - 24 : -bars + 1]) > atr * 0.06
        zero_reset = min(abs(x) for x in dif[-bars:]) <= atr * 0.22 or min(abs(x) for x in hist[-bars:]) <= atr * 0.14
        hist_turn = hist[-1] >= hist[-2] or (len(hist) >= 3 and hist[-1] >= hist[-3])
        macd_ready = hist[-1] > -atr * 0.14 and dif[-1] >= dea[-1] - atr * 0.12 and hist_turn
        if not (macd_was_positive and zero_reset and macd_ready):
            continue

        entry_base = max(ema24[-1], ema52[-1], box_low + box_width * 0.30)
        entry_level = min(max(entry_base, last.close - atr * 0.20), box_high)
        if abs(last.close - entry_level) > atr * max_entry_atr:
            continue

        quality = 11
        if box_width <= atr * 3.2:
            quality += 1
        if box_low >= ema52[-1] - atr * 0.25:
            quality += 1
        if hist[-1] >= hist[-2] and dif[-1] >= dea[-1] - atr * 0.05:
            quality += 1

        invalid_base = min(box_low, ema52[-1] - atr * 0.25)
        candidate = {
            "kind": "impulse_box_zero_axis",
            "target": max(box_high + box_width * 1.2, last.close + atr * 2.4),
            "invalid_base": invalid_base,
            "retracement": 0.0,
            "ema52": True,
            "macd": True,
            "zero_axis_ignition": True,
            "impulse_box": True,
            "box_low": box_low,
            "box_high": box_high,
            "direct_trigger": {
                "name": "impulse_box_zero_axis",
                "level": entry_level,
                "invalid": invalid_base,
                "quality": quality,
                "confirmed": True,
            },
        }
        if best is None or candidate["direct_trigger"]["quality"] > best["direct_trigger"]["quality"]:
            best = candidate
    return best


def find_vegas_zero_axis_ignition_setup(candles: list[Candle], direction: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if direction != "long":
        return None
    completed = candles[:-1]
    if len(completed) < 190:
        return None
    closes = [c.close for c in completed]
    ema24 = ema(closes, 24)
    ema52 = ema(closes, 52)
    ema144 = ema(closes, 144)
    ema169 = ema(closes, 169)
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    if atr <= 0:
        return None

    last = completed[-1]
    vegas_top = max(ema144[-1], ema169[-1])
    vegas_bottom = min(ema144[-1], ema169[-1])
    recent = completed[-48:]
    recent_high = max(c.high for c in recent)
    recent_low = min(c.low for c in recent)
    crossed_from_below = any(
        c.close < max(ema144[-len(recent) + i], ema169[-len(recent) + i]) - atr * 0.08
        for i, c in enumerate(recent[:-4])
    )
    above_vegas = last.close >= vegas_top - atr * 0.08 and ema52[-1] >= vegas_top - atr * 0.35
    if not (crossed_from_below and above_vegas):
        return None

    pullback = completed[-12:]
    support_level = max(ema24[-1], ema52[-1], vegas_top)
    support_touch = any(c.low <= support_level + atr * 0.45 for c in pullback[-8:])
    support_hold = min(c.close for c in pullback[-8:]) >= vegas_bottom - atr * 0.55
    if not (support_touch and support_hold):
        return None

    zero_reset = min(abs(x) for x in dif[-12:]) <= atr * 0.16 or min(abs(x) for x in hist[-12:]) <= atr * 0.10
    turn_up = hist[-1] >= hist[-2] and (dif[-1] >= dea[-1] or dif[-1] > -atr * 0.08)
    if not (zero_reset and turn_up):
        return None

    max_entry_atr = float(cfg.get("vegas_zero_axis_max_entry_atr", 1.6))
    entry_level = max(support_level, min(last.close, support_level + atr * 0.35))
    if last.close - entry_level > atr * max_entry_atr:
        return None
    if rsi(closes)[-1] > 76:
        return None

    invalid_base = min(recent_low, vegas_bottom - atr * 0.25)
    target = max(recent_high, last.close + atr * 2.2)
    return {
        "kind": "15m_vegas_zero_axis_ignition",
        "target": target,
        "invalid_base": invalid_base,
        "retracement": 0.0,
        "ema52": True,
        "macd": True,
        "zero_axis_ignition": True,
        "vegas_zero_axis_ignition": True,
        "direct_trigger": {
            "name": "15m_vegas_zero_axis_ignition",
            "level": entry_level,
            "invalid": invalid_base,
            "quality": 12,
            "confirmed": True,
        },
    }


def detect_trigger(candles: list[Candle], direction: str, tolerance_atr: float) -> dict[str, Any] | None:
    completed = candles[:-1]
    if len(completed) < 40:
        return None
    sample = completed[-36:]
    closes = [c.close for c in completed]
    dif, dea, hist = macd(closes)
    atr = average_true_range(candles)
    highs = [c.high for c in sample]
    lows = [c.low for c in sample]
    last, prev = sample[-1], sample[-2]
    candidates: list[dict[str, Any]] = []
    recent3_high = max(c.high for c in sample[-3:])
    recent3_low = min(c.low for c in sample[-3:])

    if direction == "long":
        post = dif[-18:]
        zero_retest = max(post) > 0 and min(post[-8:]) <= atr * 0.08 and min(post[-8:]) >= -atr * 0.08
        body = max(abs(last.close - last.open), atr * 0.05)
        lower_wick = min(last.close, last.open) - last.low
        golden_k = last.close > last.open and (last.close > prev.high or lower_wick >= body * 1.2)
        if zero_retest and golden_k and hist[-1] > hist[-2] and dif[-1] >= dea[-1]:
            candidates.append({"name": "MACD鍥炶俯0杞撮噾K", "level": prev.high, "invalid": min(c.low for c in sample[-6:]), "quality": 12, "confirmed": last.close > prev.high})
        lows_idx = pivot_indices(lows, "low", 1)
        if len(lows_idx) >= 2:
            a, b = lows_idx[-2], lows_idx[-1]
            neckline = max(highs[a + 1 : b] or [last.high])
            if len(sample) - 1 - b <= 12 and abs(lows[b] - lows[a]) <= atr * tolerance_atr:
                candidates.append({"name": "15m鍙屽簳鍙嶈浆", "level": neckline, "invalid": min(lows[a], lows[b]), "quality": 10, "confirmed": last.close > neckline})
            if len(sample) - 1 - b <= 12 and lows[b] > lows[a] + atr * 0.05:
                candidates.append({"name": "15m鎶珮浣庣偣鍙嶈浆", "level": neckline, "invalid": lows[b], "quality": 9, "confirmed": last.close > neckline})
        prior_low = min(lows[-16:-3])
        swept = min(lows[-8:]) < prior_low - atr * 0.05 and last.close > prior_low
        reclaim_ok = last.close > max(prev.high, recent3_high - atr * 0.12) or (last.close > last.open and lower_wick >= body * 1.2)
        if swept and reclaim_ok and last.close > prev.high:
            candidates.append({"name": "15m 2B\u5047\u8dcc\u7834\u6536\u56de", "level": prior_low, "invalid": min(lows[-8:]), "quality": 11, "confirmed": True})
        prior_high = max(highs[-18:-6])
        retest = max(highs[-8:]) > prior_high + atr * 0.12 and min(lows[-6:]) <= prior_high + atr * 0.25 and last.close >= prior_high and last.close > prev.high
        if retest:
            candidates.append({"name": "15m绐佺牬鍥炶俯", "level": prior_high, "invalid": min(lows[-6:]), "quality": 10, "confirmed": True})
    else:
        post = dif[-18:]
        zero_retest = min(post) < 0 and max(post[-8:]) >= -atr * 0.08 and max(post[-8:]) <= atr * 0.08
        body = max(abs(last.close - last.open), atr * 0.05)
        upper_wick = last.high - max(last.close, last.open)
        golden_k = last.close < last.open and (last.close < prev.low or upper_wick >= body * 1.2)
        if zero_retest and golden_k and hist[-1] < hist[-2] and dif[-1] <= dea[-1]:
            candidates.append({"name": "MACD鍙嶆娊0杞磋浆寮盞", "level": prev.low, "invalid": max(c.high for c in sample[-6:]), "quality": 12, "confirmed": last.close < prev.low})
        highs_idx = pivot_indices(highs, "high", 1)
        if len(highs_idx) >= 2:
            a, b = highs_idx[-2], highs_idx[-1]
            neckline = min(lows[a + 1 : b] or [last.low])
            if len(sample) - 1 - b <= 12 and abs(highs[b] - highs[a]) <= atr * tolerance_atr:
                candidates.append({"name": "15m鍙岄《鍙嶈浆", "level": neckline, "invalid": max(highs[a], highs[b]), "quality": 10, "confirmed": last.close < neckline})
            if len(sample) - 1 - b <= 12 and highs[b] < highs[a] - atr * 0.05:
                candidates.append({"name": "15m闄嶄綆楂樼偣鍙嶈浆", "level": neckline, "invalid": highs[b], "quality": 9, "confirmed": last.close < neckline})
        prior_high = max(highs[-16:-3])
        swept = max(highs[-8:]) > prior_high + atr * 0.05 and last.close < prior_high
        reject_ok = last.close < min(prev.low, recent3_low + atr * 0.12) or (last.close < last.open and upper_wick >= body * 1.2)
        if swept and reject_ok and last.close < prev.low:
            candidates.append({"name": "15m 2B\u5047\u7a81\u7834\u56de\u843d", "level": prior_high, "invalid": max(highs[-8:]), "quality": 11, "confirmed": True})
        prior_low = min(lows[-18:-6])
        retest_touch = last.high >= prior_low - atr * 0.15
        retest_reject = last.close <= prior_low and last.close < prev.low and (prior_low - last.close) <= atr * 0.45
        retest = min(lows[-8:]) < prior_low - atr * 0.12 and retest_touch and retest_reject
        if retest:
            candidates.append({"name": "15m璺岀牬鍙嶆娊", "level": prior_low, "invalid": max(highs[-6:]), "quality": 10, "confirmed": True})

    confirmed = [item for item in candidates if item["confirmed"] and item["quality"] >= 10]
    return max(confirmed, key=lambda x: x["quality"], default=None)


def rr_long(price: float, invalid: float, target: float) -> float:
    risk = price - invalid
    return (target - price) / risk if risk > 0 else -1


def rr_short(price: float, invalid: float, target: float) -> float:
    risk = invalid - price
    return (price - target) / risk if risk > 0 else -1


def entry_gap_pct(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    ref = low if price < low else high
    return abs(price - ref) / price * 100


def setup_timeframe_rank(tf: str) -> int:
    return {"15m": 0, "1h": 1, "2h": 2, "4h": 3, "1d": 4}.get(tf, 0)


def signal_selection_key(sig: Signal) -> tuple[int, int, int, float]:
    grade_rank = 2 if sig.grade == "A" else 1
    return (grade_rank, setup_timeframe_rank(sig.setup_tf), sig.score, sig.rr)


def human_rule_name(name: str) -> str:
    mapping = {
        "impulse_box_zero_axis": "\u9996\u6bb5\u62c9\u5347\u540e\u5e73\u53f0\u84c4\u529b+MACD\u96f6\u8f74\u4fee\u590d",
        "zero_axis_ema52_ignition": "EMA52\u56de\u8e29\u4f01\u7a33+MACD\u56de\u5f520\u8f74\u8d77\u7206",
        "15m_vegas_zero_axis_ignition": "\u7a81\u7834Vegas\u901a\u9053\u56de\u8e29+MACD\u56de\u5f520\u8f74\u8d77\u7206",
        "4h_neckline_retest_zero_axis": "\u9888\u7ebf\u56de\u8e29\u4e0d\u7834+MACD\u56de\u5f520\u8f74\u8d77\u7206",
        "2b_false_breakdown_reclaim": "2B\u5047\u8dcc\u7834\u6536\u56de",
        "2b_false_breakout_rejection": "2B\u5047\u7a81\u7834\u627f\u538b",
        "breakdown_retest_short": "\u8dcc\u7834\u5e73\u53f0\u540e\u53cd\u62bd\u627f\u538b",
        "double_bottom_reversal": "\u53cc\u5e95\u53cd\u8f6c",
        "downtrend_retest_short": "4H\u4e0b\u8dcc\u8d8b\u52bf\u56de\u8e29\u91cd\u65b0\u627f\u538b",
    }
    return mapping.get(name, name)


def near_prior_high_veto(bundle: dict[str, dict[str, float]], trigger_name: str, direction: str) -> bool:
    if direction == "long" and "鍥炶俯" not in trigger_name:
        frame = bundle["4h"]
        return frame["recent_high"] > 0 and (frame["recent_high"] - frame["close"]) / frame["close"] * 100 <= 1.5
    if direction == "short":
        for tf in ("1h", "4h"):
            frame = bundle[tf]
            support = frame["recent_low"]
            close = frame["close"]
            atr = frame["atr"]
            if support > 0 and close > 0 and (close - support) <= max(atr * 0.8, close * 0.018):
                return True
    return False


def evaluate_direction(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    candle_map: dict[str, list[Candle]],
    market_state: str,
    direction: str,
    config: dict[str, Any],
) -> Signal | None:
    if direction == "long" and market_state in {"\u5f31", "\u6025\u8dcc"} and display_symbol not in {"BTCUSDT", "ETHUSDT"}:
        return None
    if direction == "short" and market_state == "\u5f3a":
        return None

    if local_start_protects_against(bundle, direction):
        return None
    if local_countertrend_veto(bundle, direction):
        return None
    if direction == "short" and local_direction_score(bundle, direction) == 0:
        return None

    scan_cfg = config["scan"]
    pb_cfg = config["trend_pullback"]
    min_rr = float(scan_cfg["min_rr"])
    max_gap = float(scan_cfg["max_distance_to_entry_pct"])
    best: Signal | None = None

    for setup_tf, path_cfg in SETUP_PATHS.items():
        if setup_tf == "15m":
            setup = (
                find_impulse_box_zero_axis_setup(candle_map[setup_tf], direction, pb_cfg)
                or find_vegas_zero_axis_ignition_setup(candle_map[setup_tf], direction, pb_cfg)
            )
            if setup and not bool(setup.get("impulse_box")) and not higher_timeframe_zero_axis_support(candle_map, direction, pb_cfg):
                continue
        else:
            setup = None
            if direction == "short" and setup_tf in {"2h", "4h"}:
                setup = find_downtrend_retest_short_setup(candle_map[setup_tf], pb_cfg)
            setup = (
                setup
                or find_impulse_box_zero_axis_setup(candle_map[setup_tf], direction, pb_cfg)
                or find_neckline_retest_zero_axis_setup(candle_map[setup_tf], direction, pb_cfg)
                or find_zero_axis_ema52_ignition_setup(candle_map[setup_tf], direction, pb_cfg)
                or find_bottom_box_breakout_setup(candle_map[setup_tf], direction, pb_cfg)
                or find_trend_setup(candle_map[setup_tf], direction, pb_cfg)
            )
        if not setup:
            continue
        direct_trigger = setup.get("direct_trigger")
        if direct_trigger:
            trigger_tf = setup_tf
            trigger = dict(direct_trigger)
        else:
            trigger_tf = str(path_cfg["trigger"])
            trigger = detect_trigger(candle_map[trigger_tf], direction, float(pb_cfg["entry_trigger_atr_tolerance"]))
            if not trigger and bool(setup.get("neckline_retest")) and trigger_tf == "15m":
                vegas_setup = find_vegas_zero_axis_ignition_setup(candle_map[trigger_tf], direction, pb_cfg)
                if vegas_setup:
                    trigger = dict(vegas_setup["direct_trigger"])
        if not trigger:
            continue
        if trigger_tf != "15m" and str(trigger["name"]).startswith("15m"):
            trigger = dict(trigger)
            trigger["name"] = trigger_tf + str(trigger["name"])[3:]
        trigger_name = str(trigger["name"])
        if disabled_c_trigger(trigger_name):
            continue
        if is_btc(display_symbol):
            if setup_tf != "4h" or weak_reversal_trigger(trigger_name):
                continue
        elif is_alt(display_symbol):
            if weak_reversal_trigger(trigger_name):
                continue
            if direction == "long" and not alt_long_confirmed(bundle):
                continue
            neckline_vegas_trigger = bool(setup.get("neckline_retest")) and "vegas" in str(trigger["name"])
            if direction == "long" and not (bool(setup.get("zero_axis_ignition")) or neckline_vegas_trigger) and not long_key_level_acceptance(candle_map[trigger_tf], float(trigger["level"])):
                continue
            if direction == "short" and not alt_short_confirmed(bundle, setup, trigger_name):
                continue
            if direction == "short" and not short_key_level_rejection(candle_map[trigger_tf], float(trigger["level"])):
                continue
            if not trigger_near_setup_key(setup_tf, setup, bundle, trigger, direction):
                continue
        context = higher_context(bundle, setup_tf, direction)
        if context["hard_opposite"] and not (is_alt(display_symbol) and direction == "long" and bottom_box_setup(setup) and local_direction_score(bundle, "long") >= 2):
            continue

        price = bundle[trigger_tf]["close"]
        atr = average_true_range(candle_map[trigger_tf])
        buffer = atr * float(pb_cfg["invalidation_atr_buffer"])
        if direction == "long":
            entry_low = float(trigger["level"]) - atr * 0.18
            entry_high = float(trigger["level"]) + atr * 0.35
            invalid = min(float(trigger["invalid"]), float(setup["invalid_base"])) - buffer
            risk = price - invalid
            structure_target = float(setup.get("target", price + risk * 2.0))
            if structure_target > price and rr_long(price, invalid, structure_target) >= 1.8:
                target1 = structure_target
            elif "box_high" in setup:
                continue
            else:
                target1 = price + risk * 2.0
            target2 = price + risk * 3.0
            rr = rr_long(price, invalid, target2)
        else:
            entry_low = float(trigger["level"]) - atr * 0.35
            entry_high = float(trigger["level"]) + atr * 0.18
            invalid = max(float(trigger["invalid"]), float(setup["invalid_base"])) + buffer
            risk = invalid - price
            target1 = price - risk * 2.0
            target2 = price - risk * 3.0
            rr = rr_short(price, invalid, target2)

        gap = entry_gap_pct(price, entry_low, entry_high)
        if rr < min_rr or gap > max_gap:
            continue
        if near_prior_high_veto(bundle, trigger_name, direction):
            continue
        if is_alt(display_symbol) and gap > 2.0:
            continue
        if direction == "long" and bundle[trigger_tf]["rsi"] > 76:
            continue
        if direction == "short" and bundle[trigger_tf]["rsi"] < 24:
            continue

        score = 55
        score += 10 if market_state in {"\u5f3a", "\u9707\u8361"} else 5
        score += 10 if context["a_ok"] else 5
        score += min(15, int(float(trigger["quality"])))
        score += 8 if setup["ema52"] else 0
        score += 8 if setup["macd"] else 0
        score += 8 if rr >= 2.5 else 4
        score -= 8 if gap > 1.2 else 0
        grade = "A" if score >= 85 and context["a_ok"] and gap <= 1.2 else "B"
        if bool(setup.get("impulse_box")):
            grade = "B"
        if setup_tf == "4h" and direction == "long" and bool(setup.get("zero_axis_ignition")) and not bool(setup.get("neckline_retest")) and not bottom_box_setup(setup):
            grade = "B"
        if macd_standalone_trigger(trigger_name):
            grade = "B"
        if setup_tf == "2h" and not two_hour_a_allowed(direction, trigger_name, setup, bundle, gap, score):
            grade = "B"
        if is_btc(display_symbol) and not (setup_tf == "4h" and score >= 92 and gap <= 0.8):
            grade = "B"
        if is_alt(display_symbol) and not (context["a_ok"] and score >= 88 and gap <= 1.0 and alt_stage_allows_a(setup_tf, setup, bundle, direction)):
            grade = "B"
        status = "\u5165\u573a\u533a\u5185" if entry_low <= price <= entry_high else "\u63a5\u8fd1\u5165\u573a"
        direction_text = "\u505a\u591a" if direction == "long" else "\u505a\u7a7a"
        setup_label = human_rule_name(str(setup["kind"]))
        trigger_label = human_rule_name(trigger_name)
        reason = (
            f"{setup_tf} {setup_label}\uff0c\u56de\u8c03\u672a\u8d85\u8fc761.8%\uff0c"
            f"{trigger_tf} \u51fa\u73b0{trigger_label}\uff0c\u9ad8\u4e00\u7ea7\u7ed3\u6784\u672a\u5f3a\u53cd\u5411"
        )
        action = "\u0041\u7c7b\u53ef\u6309\u8ba1\u5212\u5c0f\u4ed3\u8bd5\u6267\u884c\uff0c\u5fc5\u987b\u6302\u5931\u6548\u4f4d" if grade == "A" else "\u0042\u7c7b\u89c2\u5bdf\uff0c\u53ea\u5728\u5165\u573a\u533a\u786e\u8ba4\u540e\u6267\u884c"
        signal = Signal(
            model_name=MODEL_NAME,
            symbol=display_symbol,
            actual_symbol=actual_symbol,
            direction=direction_text,
            grade=grade,
            status=status,
            price=price,
            entry_low=entry_low,
            entry_high=entry_high,
            invalid=invalid,
            target1=target1,
            target2=target2,
            rr=rr,
            score=score,
            market_state=market_state,
            setup_tf=setup_tf,
            trigger_tf=trigger_tf,
            setup_kind=setup_label,
            trigger_name=trigger_label,
            reason=reason,
            action=action,
            created_at=now_iso(),
        )
        if best is None or signal_selection_key(signal) > signal_selection_key(best):
            best = signal
    return best


def choose_signal(long_sig: Signal | None, short_sig: Signal | None, bundle: dict[str, dict[str, float]]) -> Signal | None:
    if long_sig and short_sig:
        long_score = local_direction_score(bundle, "long")
        short_score = local_direction_score(bundle, "short")
        if long_score != short_score:
            return long_sig if long_score > short_score else short_sig
        return max([long_sig, short_sig], key=lambda s: (s.grade == "A", s.score, s.rr))
    return long_sig or short_sig


def signal_priority(sig: Signal) -> tuple[int, int, float]:
    if sig.grade != "A":
        return (9, -sig.score, -sig.rr)
    if is_eth(sig.symbol):
        return (0, -sig.score, -sig.rr)
    if is_alt(sig.symbol) and has_any(sig.setup_kind, ("\u7bb1\u4f53", "\u76d8\u6574\u7bb1\u4f53", "box")):
        return (1, -sig.score, -sig.rr)
    if is_alt(sig.symbol):
        return (2, -sig.score, -sig.rr)
    if is_btc(sig.symbol):
        return (3, -sig.score, -sig.rr)
    return (4, -sig.score, -sig.rr)


def priority_icon(sig: Signal) -> str:
    if sig.grade == "A" and sig.status in {"\u5165\u573a\u533a\u5185", "\u63a5\u8fd1\u5165\u573a"}:
        return "A"
    if sig.grade == "A":
        return "A"
    return "B"


def render_signal_message(sig: Signal, event: str = "push") -> str:
    title = f"\u8d8b\u52bf\u673a\u4f1a\uff5c{sig.symbol}\uff5c{sig.direction}{sig.grade}\u7c7b"
    return "\n".join(
        [
            title,
            "",
            f"\u73b0\u4ef7\uff1a{sig.price:.6g}",
            f"\u72b6\u6001\uff1a{sig.status}",
            f"\u5165\u573a\u533a\uff1a{sig.entry_low:.6g}-{sig.entry_high:.6g}",
            f"\u5931\u6548\u4f4d\uff1a{sig.invalid:.6g}",
            f"\u76ee\u68071\uff1a{sig.target1:.6g}",
            "",
            f"\u539f\u56e0\uff1a{sig.reason}",
            f"\u5904\u7406\uff1a{sig.action}",
        ]
    )


def status_icon_v2(status: str) -> str:
    if any(marker in status for marker in ("\u5931\u6548", "\u8fc7\u671f", "\u4f5c\u5e9f")):
        return "X"
    if status in {"\u5165\u573a\u533a\u5185", "\u63a5\u8fd1\u5165\u573a"}:
        return "OK"
    if "\u89c2\u5bdf" in status:
        return "B"
    return "I"


def direction_badge(direction: str) -> str:
    if "\u591a" in direction or "long" in direction.lower():
        return "\u591a"
    if "\u7a7a" in direction or "short" in direction.lower():
        return "\u7a7a"
    return direction


def status_badge(status: str, grade: str) -> str:
    if "\u5165\u573a" in status:
        return "\u63a5\u8fd1\u5165\u573a" if "\u63a5\u8fd1" in status else "\u5165\u573a\u533a"
    if "\u5931\u6548" in status:
        return "\u5931\u6548"
    if "\u76ee\u6807" in status:
        return "\u76ee\u6807"
    return "\u53ef\u6267\u884c" if grade == "A" else "\u89c2\u5bdf"


def signal_icon_v2(sig: Signal) -> str:
    if "\u5931\u6548" in sig.status or "\u8fc7\u671f" in sig.status or "\u4f5c\u5e9f" in sig.status:
        return "X"
    if sig.grade == "A" and sig.status == "\u5165\u573a\u533a\u5185":
        return "A"
    if sig.grade == "A":
        return "A"
    return "B"


def render_signal_message_v2(sig: Signal, event: str = "push") -> str:
    suffix = "\u53ef\u6267\u884c" if sig.grade == "A" else "\u89c2\u5bdf\uff0c\u4e0d\u8ffd\u5355"
    title = f"\u8d8b\u52bf\u673a\u4f1a\uff5c{sig.symbol}\uff5c{sig.direction}{suffix}"
    return "\n".join(
        [
            title,
            "",
            f"\u73b0\u4ef7\uff1a{sig.price:.6g}",
            f"\u72b6\u6001\uff1a{sig.status}",
            f"\u5165\u573a\u533a\uff1a{sig.entry_low:.6g}-{sig.entry_high:.6g}",
            f"\u5931\u6548\u4f4d\uff1a{sig.invalid:.6g}",
            f"\u76ee\u68071\uff1a{sig.target1:.6g}",
            "",
            f"\u539f\u56e0\uff1a{sig.reason}",
            f"\u5904\u7406\uff1a{sig.action}",
        ]
    )


def feishu_send(config: dict[str, Any], text: str) -> None:
    if not config["feishu"].get("enabled", True):
        return
    if os.getenv(config["feishu"]["dry_run_env"]):
        print(text)
        return
    webhook = os.getenv(config["feishu"]["webhook_env"])
    if not webhook:
        print("FEISHU_WEBHOOK is not set; skip notification", file=sys.stderr)
        return
    http_post_json(webhook, {"msg_type": "text", "content": {"text": text}})


def is_duplicate(state: dict[str, Any], sig: Signal, expiry_hours: int) -> bool:
    old = state.get("signals", {}).get(sig.family_key)
    if not old:
        return False
    old_created = old.get("created_at")
    try:
        created_at = datetime.fromisoformat(old_created)
    except Exception:
        return False
    if datetime.now(CN_TZ) - created_at > timedelta(hours=expiry_hours):
        return False
    old_status = old.get("status")
    old_grade = old.get("grade")
    if old_grade != sig.grade or old_status != sig.status:
        return False
    return True


def scan_crypto(config: dict[str, Any], state: dict[str, Any]) -> list[Signal]:
    if not config["crypto"].get("enabled", True):
        return []
    base_symbols = list(config["crypto"].get("symbols", DEFAULT_SYMBOLS))
    discovered_symbols = discover_okx_symbols(config)
    symbols = merge_symbols(base_symbols, discovered_symbols)
    symbol_map = dict(config["crypto"].get("symbol_map", SYMBOL_MAP))
    bundle_cache: dict[str, tuple[dict[str, dict[str, float]], dict[str, list[Candle]]]] = {}

    def get(actual: str) -> tuple[dict[str, dict[str, float]], dict[str, list[Candle]]]:
        if actual not in bundle_cache:
            bundle_cache[actual] = fetch_bundle(actual)
        return bundle_cache[actual]

    btc_bundle, _ = get("BTCUSDT")
    eth_bundle, _ = get("ETHUSDT")
    market_state = detect_market_state(btc_bundle, eth_bundle)
    state.setdefault("meta", {})["last_market_state"] = market_state
    state["meta"]["last_okx_discovery_count"] = len(discovered_symbols)
    state["meta"]["last_okx_discovery_symbols"] = discovered_symbols

    signals: list[Signal] = []
    for display_symbol in symbols:
        actual = symbol_map.get(display_symbol, display_symbol)
        try:
            bundle, candle_map = get(actual)
            long_sig = evaluate_direction(display_symbol, actual, bundle, candle_map, market_state, "long", config)
            short_sig = evaluate_direction(display_symbol, actual, bundle, candle_map, market_state, "short", config)
            chosen = choose_signal(long_sig, short_sig, bundle)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {display_symbol}: {exc}", file=sys.stderr)
            continue
        if chosen:
            signals.append(chosen)
    return sorted(signals, key=signal_priority)


def update_performance(config: dict[str, Any], state: dict[str, Any]) -> None:
    rows = list(state.get("signals", {}).values())
    perf = {
        "updated_at": now_iso(),
        "model_name": PORTFOLIO_NAME,
        "overall": {
            "active_signals": len(rows),
            "a_count": sum(1 for r in rows if r.get("grade") == "A"),
            "b_count": sum(1 for r in rows if r.get("grade") == "B"),
        },
    }
    write_json(config["scan"]["performance_file"], perf)
    ensure_parent(config["scan"]["performance_report"])
    Path(config["scan"]["performance_report"]).write_text(
        f"# Scanner Performance\n\nUpdated: {perf['updated_at']}\n\nActive signals: {len(rows)}\n",
        encoding="utf-8",
    )


def main() -> int:
    config = load_config()
    state = load_state(config["scan"]["state_file"])
    state.setdefault("signals", {})
    state.setdefault("meta", {})
    expiry_hours = int(config["scan"].get("expiry_hours", 12))

    try:
        candidates = scan_crypto(config, state)
    except Exception as exc:  # noqa: BLE001
        print(f"scan failed: {exc}", file=sys.stderr)
        save_state(config["scan"]["state_file"], state)
        return 1

    pushed = 0
    for sig in candidates:
        if sig.grade != "A" and not (sig.grade == "B" and sig.status in {"\u5165\u573a\u533a\u5185", "\u63a5\u8fd1\u5165\u573a"}):
            continue
        if is_duplicate(state, sig, expiry_hours):
            continue
        state["signals"][sig.family_key] = asdict(sig)
        append_jsonl(config["scan"]["trade_ledger_file"], asdict(sig))
        feishu_send(config, render_signal_message_v2(sig))
        pushed += 1
        if pushed >= 3:
            break

    state["meta"]["last_scan_at"] = now_iso()
    state["meta"]["last_candidates"] = len(candidates)
    save_state(config["scan"]["state_file"], state)
    update_performance(config, state)

    if pushed == 0:
        print("DONT_NOTIFY")
    else:
        print(f"NOTIFIED {pushed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

