from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


USER_AGENT = "tianji-trend-scanner/2.0"
HTTP_TIMEOUT = 20
CN_TZ = ZoneInfo("Asia/Shanghai")
FINAL_STATES = {"目标1达成", "失效", "过期"}
NOTIFY_EVENTS = {"push", "upgrade", "touch_entry", "trigger", "target1", "invalid", "expire"}
COMPARE_FIELDS = (
    "signal_id",
    "grade",
    "status",
    "entry_low",
    "entry_high",
    "invalid",
    "target1",
    "push_price",
    "trigger_price",
    "open",
    "triggered",
    "final_r",
    "last_event",
)


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
    market: str
    symbol: str
    direction: str
    grade: str
    stage: str
    status: str
    price: float
    entry_low: float
    entry_high: float
    invalid: float
    target1: float
    market_state: str
    setup_state: str
    reason: str
    action: str
    score: int
    actual_symbol: str

    @property
    def family_key(self) -> str:
        return f"{self.market}:{self.symbol}:{self.direction}"

    @property
    def signal_id(self) -> str:
        ts = datetime.now(CN_TZ).strftime("%Y%m%d%H%M%S")
        return f"{ts}:{self.symbol}:{self.direction}:{self.grade}"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def http_json(url: str, timeout: int = HTTP_TIMEOUT, retries: int = 3, sleep_s: float = 0.8) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(sleep_s * (attempt + 1))
    raise RuntimeError(f"request failed: {last_error}")


def http_post_json(url: str, payload: dict[str, Any], timeout: int = HTTP_TIMEOUT) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def load_config() -> dict[str, Any]:
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config.setdefault("feishu", {})
    config.setdefault("scan", {})
    config.setdefault("crypto", {})
    config.setdefault("us_stocks", {})
    config.setdefault("cn_stocks", {})

    config["feishu"].setdefault("enabled", True)
    config["feishu"].setdefault("webhook_env", "FEISHU_WEBHOOK")
    config["feishu"].setdefault("dry_run_env", "DRY_RUN")

    config["scan"].setdefault("state_file", "state/signals.json")
    config["scan"].setdefault("trade_ledger_file", "state/trades.jsonl")
    config["scan"].setdefault("performance_file", "state/performance.json")
    config["scan"].setdefault("performance_report", "reports/performance.md")
    config["scan"].setdefault("expiry_hours", 12)
    config["scan"].setdefault("min_rr", 2.0)
    config["scan"].setdefault("max_distance_to_entry_pct", 2.5)

    config["crypto"].setdefault("enabled", True)
    config["crypto"].setdefault("symbols", [])
    config["crypto"].setdefault("symbol_map", {})

    config["us_stocks"].setdefault("enabled", False)
    config["cn_stocks"].setdefault("enabled", False)
    return config


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"signals": {}, "meta": {"schema": 1, "updated_at": None}}
    with p.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if "signals" not in state or not isinstance(state["signals"], dict):
        state["signals"] = {}
    state.setdefault("meta", {"schema": 1, "updated_at": None})
    return state


def save_state(path: str, state: dict[str, Any]) -> None:
    ensure_parent(path)
    state.setdefault("meta", {})
    state["meta"]["updated_at"] = now_iso()
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def load_jsonl(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def append_jsonl(path: str, row: dict[str, Any]) -> None:
    ensure_parent(path)
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def write_json(path: str, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_text(path: str, text: str) -> None:
    ensure_parent(path)
    with Path(path).open("w", encoding="utf-8") as f:
        f.write(text)


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1 - alpha))
    return out


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) < period + 1:
        return [50.0] * len(values)
    out = [50.0] * period
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        avg_gain += max(diff, 0)
        avg_loss += abs(min(diff, 0))
    avg_gain /= period
    avg_loss /= period
    for i in range(period, len(values)):
        if i > period:
            diff = values[i] - values[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(diff, 0)) / period
            avg_loss = (avg_loss * (period - 1) + abs(min(diff, 0))) / period
        rs = avg_gain / avg_loss if avg_loss else 100.0
        out.append(100 - 100 / (1 + rs))
    return out[: len(values)]


def macd(values: list[float]) -> tuple[list[float], list[float], list[float]]:
    e12 = ema(values, 12)
    e26 = ema(values, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    hist = [a - b for a, b in zip(dif, dea)]
    return dif, dea, hist


def pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else 0.0


def fmt_price(x: float) -> str:
    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.3f}"
    return f"{x:.5f}"


def summarize(candles: list[Candle]) -> dict[str, float]:
    if len(candles) < 60:
        raise ValueError("not enough candles")
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    dif, dea, hist = macd(closes)
    return {
        "open": candles[-1].open,
        "high": candles[-1].high,
        "low": candles[-1].low,
        "close": closes[-1],
        "ema10": ema(closes, 10)[-1],
        "ema20": ema(closes, 20)[-1],
        "ema24": ema(closes, 24)[-1],
        "ema52": ema(closes, 52)[-1],
        "ema144": ema(closes, 144)[-1],
        "ema169": ema(closes, 169)[-1],
        "rsi": rsi(closes)[-1],
        "dif": dif[-1],
        "dea": dea[-1],
        "hist": hist[-1],
        "hist_prev": hist[-2] if len(hist) > 1 else hist[-1],
        "vol": vols[-1],
        "vol_ma10": sum(vols[-10:]) / min(10, len(vols)),
        "high20": max(c.high for c in candles[-20:]),
        "low20": min(c.low for c in candles[-20:]),
    }


def binance_mark_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    qs = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = f"https://fapi.binance.com/fapi/v1/markPriceKlines?{qs}"
    rows = http_json(url, retries=2)
    return [
        Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), 0.0)
        for r in rows
    ]


def okx_inst_id(symbol: str) -> str:
    base = symbol.upper()
    if base.startswith("1000PEPE"):
        base = "PEPEUSDT"
    if base.startswith("1000BONK"):
        base = "BONKUSDT"
    if base.endswith("USDT"):
        base = base[:-4]
    return f"{base}-USDT-SWAP"


def okx_bar(interval: str) -> str:
    return {
        "1d": "1D",
        "4h": "4H",
        "2h": "2H",
        "1h": "1H",
        "30m": "30m",
        "15m": "15m",
    }.get(interval, interval)


def okx_mark_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    qs = urllib.parse.urlencode({"instId": okx_inst_id(symbol), "bar": okx_bar(interval), "limit": limit})
    url = f"https://www.okx.com/api/v5/market/candles?{qs}"
    payload = http_json(url, retries=3)
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX candles failed: {payload.get('msg') or payload.get('code')}")
    rows = list(reversed(payload.get("data", [])))
    return [
        Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0.0))
        for r in rows
    ]


def crypto_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    try:
        return okx_mark_klines(symbol, interval, limit)
    except Exception as okx_exc:  # noqa: BLE001
        try:
            return binance_mark_klines(symbol, interval, limit)
        except Exception as binance_exc:  # noqa: BLE001
            raise RuntimeError(f"OKX and Binance both failed: OKX={okx_exc}; Binance={binance_exc}") from binance_exc


def binance_24h_tickers() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = http_json("https://fapi.binance.com/fapi/v1/ticker/24hr", retries=2)
        for row in rows:
            symbol = row.get("symbol")
            if symbol:
                out[symbol] = row
    except Exception as exc:  # noqa: BLE001
        print(f"Binance 24h ticker unavailable, using OKX fallback: {exc}", file=sys.stderr)

    try:
        payload = http_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP", retries=3)
        if str(payload.get("code")) == "0":
            for row in payload.get("data", []):
                inst_id = str(row.get("instId", ""))
                if inst_id.endswith("-USDT-SWAP"):
                    base = inst_id.replace("-USDT-SWAP", "")
                    symbol = f"{base}USDT"
                    out.setdefault(symbol, row)
                    if symbol == "PEPEUSDT":
                        out.setdefault("1000PEPEUSDT", row)
                    if symbol == "BONKUSDT":
                        out.setdefault("1000BONKUSDT", row)
    except Exception as exc:  # noqa: BLE001
        print(f"OKX 24h ticker fallback unavailable: {exc}", file=sys.stderr)

    return out


def fetch_bundle(symbol: str) -> dict[str, dict[str, float]]:
    bundle: dict[str, dict[str, float]] = {}
    for interval in ("1d", "4h", "2h", "1h", "30m", "15m"):
        candles = crypto_klines(symbol, interval)
        bundle[interval] = summarize(candles)
    return bundle


def candle_cache_get(cache: dict[str, dict[str, dict[str, float]]], symbol: str) -> dict[str, dict[str, float]]:
    if symbol not in cache:
        cache[symbol] = fetch_bundle(symbol)
    return cache[symbol]


def detect_market_state(btc_4h: dict[str, float], eth_4h: dict[str, float], btc_1h: dict[str, float]) -> str:
    acute = btc_1h["close"] < btc_1h["ema20"] and btc_1h["rsi"] < 35 and pct(btc_1h["close"], btc_1h["ema20"]) < -2.5
    weak = btc_4h["close"] < btc_4h["ema20"] and eth_4h["close"] < eth_4h["ema20"] and btc_4h["close"] < btc_4h["ema52"] and eth_4h["close"] < eth_4h["ema52"]
    strong = btc_4h["close"] > btc_4h["ema20"] and eth_4h["close"] > eth_4h["ema20"] and btc_1h["rsi"] >= 50
    if acute:
        return "急跌"
    if weak:
        return "弱"
    if strong:
        return "强"
    return "震荡"


def pivots(values: list[float], side: str) -> list[float]:
    out: list[float] = []
    for i in range(2, len(values) - 2):
        window = values[i - 2 : i + 3]
        if side == "low" and values[i] == min(window):
            out.append(values[i])
        if side == "high" and values[i] == max(window):
            out.append(values[i])
    return out


def pullback_quality(candles: list[Candle]) -> tuple[int, bool]:
    lows = [c.low for c in candles[-40:]]
    points = pivots(lows, "low")
    if len(points) < 2:
        return len(points), False
    higher_low = points[-1] >= points[-2] * 0.985
    return min(len(points), 3), higher_low


def rebound_quality(candles: list[Candle]) -> tuple[int, bool]:
    highs = [c.high for c in candles[-40:]]
    points = pivots(highs, "high")
    if len(points) < 2:
        return len(points), False
    lower_high = points[-1] <= points[-2] * 1.015
    return min(len(points), 3), lower_high


def risk_reward_long(price: float, entry_low: float, invalid: float, target1: float) -> float:
    risk = price - invalid
    reward = target1 - price
    return reward / risk if risk > 0 else 0.0


def risk_reward_short(price: float, entry_high: float, invalid: float, target1: float) -> float:
    risk = invalid - price
    reward = price - target1
    return reward / risk if risk > 0 else 0.0


def vegas_bounds(frame: dict[str, float]) -> tuple[float, float]:
    low = min(frame["ema144"], frame["ema169"])
    high = max(frame["ema144"], frame["ema169"])
    return low, high


def macd_repairing_to_zero(frame: dict[str, float]) -> bool:
    improving_hist = frame["hist"] >= frame["hist_prev"]
    near_zero = abs(frame["dif"]) <= frame["close"] * 0.025
    bullish_crossing = frame["dif"] >= frame["dea"] or frame["hist"] > 0
    return improving_hist and (near_zero or bullish_crossing)


def small_reversal(frame: dict[str, float]) -> bool:
    reclaim_fast_ma = frame["close"] >= frame["ema20"] or frame["close"] >= frame["ema24"]
    momentum_repair = frame["hist"] >= frame["hist_prev"] and frame["rsi"] >= 42
    return reclaim_fast_ma and momentum_repair


def is_long_direction(direction: str) -> bool:
    return direction in {"做多", "鍋氬"}


def is_short_direction(direction: str) -> bool:
    return direction in {"做空", "鍋氱┖"}


def vegas_pullback_long_context(bundle: dict[str, dict[str, float]]) -> bool:
    h4 = bundle["4h"]
    h2 = bundle.get("2h", bundle["1h"])
    price = bundle["1h"]["close"]
    h2_low, h2_high = vegas_bounds(h2)
    h4_low, h4_high = vegas_bounds(h4)
    near_h2_vegas = h2_low * 0.985 <= price <= h2_high * 1.04
    near_h4_vegas = h4_low * 0.985 <= price <= h4_high * 1.06
    support_not_broken = price >= h2["low20"] * 1.003 or h2["rsi"] >= 43
    return (near_h2_vegas or near_h4_vegas) and macd_repairing_to_zero(h4) and support_not_broken


def evaluate_vegas_pullback_long(display_symbol: str, actual_symbol: str, bundle: dict[str, dict[str, float]], market_state: str, max_distance_pct: float, min_rr: float) -> Signal | None:
    h4 = bundle["4h"]
    h2 = bundle.get("2h", bundle["1h"])
    h1 = bundle["1h"]
    m30 = bundle.get("30m", h1)
    m15 = bundle["15m"]
    price = h1["close"]

    h2_low, h2_high = vegas_bounds(h2)
    if not vegas_pullback_long_context(bundle):
        return None

    entry_low = h2_low * 0.995
    entry_high = h2_high * 1.018
    if price > entry_high * (1 + max_distance_pct / 100):
        return None
    if price < entry_low * 0.985:
        return None

    invalid = min(h2["low20"], h2_low * 0.982)
    target1 = max(h2["high20"], h4["high20"], price + (price - invalid) * 2.2)
    rr = risk_reward_long(price, entry_low, invalid, target1)
    if rr < min_rr:
        return None

    trigger_ok = small_reversal(m15) and small_reversal(m30)
    partial_trigger = small_reversal(m15) or small_reversal(m30) or h1["close"] >= h1["ema24"]
    volume_ok = m15["vol"] >= m15["vol_ma10"] * 0.75
    current_near_entry = entry_low * 0.995 <= price <= entry_high * 1.015

    score = 48
    score += 16 if macd_repairing_to_zero(h4) else 0
    score += 12 if h2_low * 0.995 <= price <= h2_high * 1.025 else 6
    score += 12 if trigger_ok else (6 if partial_trigger
