from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import yaml


MODEL_NAME = "天机伏击·A/B趋势起爆模型"
LEGACY_MODEL_NAME = "天机伏击·趋势回踩模型"
MACRO_MODEL_NAME = "天机伏击·主流币大周期反转模型"
PORTFOLIO_NAME = "三模型并行扫描"
MODEL_PRIORITY = {
    LEGACY_MODEL_NAME: 0,
    MODEL_NAME: 1,
    MACRO_MODEL_NAME: 2,
}
DEFAULT_MACRO_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "ETCUSDT",
)
SHORT_TIMEFRAMES = ("1d", "4h", "2h", "1h", "30m", "15m")
MACRO_TIMEFRAMES = ("1w",) + SHORT_TIMEFRAMES
USER_AGENT = "tianji-trend-scanner/3.0"
HTTP_TIMEOUT = 20
CN_TZ = ZoneInfo("Asia/Shanghai")
NOTIFY_EVENTS = {"push", "upgrade", "touch_entry", "trigger", "target1", "invalid", "expire"}
FINAL_STATES = {"目标1达成", "失效", "过期"}
MODEL_SPECS = (
    {"name": LEGACY_MODEL_NAME, "variant": "legacy"},
    {"name": MODEL_NAME, "variant": "breakout"},
    {"name": MACRO_MODEL_NAME, "variant": "macro"},
)
SNAPSHOT_FIELDS = (
    "model_name",
    "family_key",
    "signal_id",
    "market",
    "symbol",
    "actual_symbol",
    "direction",
    "grade",
    "stage",
    "setup_state",
    "status",
    "last_event",
    "previous_status",
    "price",
    "push_price",
    "entry_low",
    "entry_high",
    "invalid",
    "target1",
    "market_state",
    "reason",
    "action",
    "score",
    "open",
    "triggered",
    "trigger_price",
    "final_r",
    "max_floating_r",
    "max_drawdown_r",
    "notified",
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
    model_name: str
    market: str
    symbol: str
    actual_symbol: str
    direction: str
    grade: str
    stage: str
    setup_state: str
    status: str
    price: float
    entry_low: float
    entry_high: float
    invalid: float
    target1: float
    market_state: str
    reason: str
    action: str
    score: int

    @property
    def family_key(self) -> str:
        return f"{self.model_name}:{self.symbol}:{self.direction}"

    @property
    def signal_id(self) -> str:
        ts = datetime.now(CN_TZ).strftime("%Y%m%d%H%M%S")
        safe_model = self.model_name.replace(" ", "_")
        return f"{ts}:{safe_model}:{self.symbol}:{self.direction}:{self.grade}"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def http_json(url: str, timeout: int = HTTP_TIMEOUT, retries: int = 3, sleep_s: float = 0.8) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
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


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config.setdefault("model", {})
    config.setdefault("models", [])
    config.setdefault("macro", {})
    config.setdefault("feishu", {})
    config.setdefault("scan", {})
    config.setdefault("crypto", {})

    config["model"].setdefault("name", MODEL_NAME)
    config["model"].setdefault("output_grade", "A/B类")
    if not config["models"]:
        config["models"] = [
            {"name": LEGACY_MODEL_NAME, "variant": "legacy", "output_grade": "A/B类"},
            {"name": MODEL_NAME, "variant": "breakout", "output_grade": "A/B类"},
            {"name": MACRO_MODEL_NAME, "variant": "macro", "output_grade": "A/B类"},
        ]
    elif not any(str(model.get("name")) == MACRO_MODEL_NAME for model in config["models"]):
        config["models"].append({"name": MACRO_MODEL_NAME, "variant": "macro", "output_grade": "A/B类"})

    config["macro"].setdefault("enabled", True)
    config["macro"].setdefault("symbols", list(DEFAULT_MACRO_SYMBOLS))
    config["macro"].setdefault("min_rr", 2.2)
    config["macro"].setdefault("max_distance_to_entry_pct", 2.5)

    config["feishu"].setdefault("enabled", True)
    config["feishu"].setdefault("webhook_env", "FEISHU_WEBHOOK")
    config["feishu"].setdefault("dry_run_env", "DRY_RUN")

    config["scan"].setdefault("timezone", "Asia/Shanghai")
    config["scan"].setdefault("state_file", "state/signals.json")
    config["scan"].setdefault("trade_ledger_file", "state/trades.jsonl")
    config["scan"].setdefault("performance_file", "state/performance.json")
    config["scan"].setdefault("performance_report", "reports/performance.md")
    config["scan"].setdefault("expiry_hours", 12)
    config["scan"].setdefault("min_rr", 2.0)
    config["scan"].setdefault("max_distance_to_entry_pct", 2.5)
    config["scan"].setdefault("full_scan_interval_minutes", 60)
    config["scan"].setdefault("open_signal_refresh_minutes", 15)
    config["scan"].setdefault("v2_enabled", True)
    config["scan"].setdefault("v2_max_distance_to_entry_pct", 2.0)

    config["crypto"].setdefault("enabled", True)
    config["crypto"].setdefault("symbols", [])
    config["crypto"].setdefault("symbol_map", {})

    return config
def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"signals": {}, "meta": {"schema": 2, "updated_at": None, "model_name": PORTFOLIO_NAME}}
    with p.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state.get("signals"), dict):
        state["signals"] = {}
    state.setdefault("meta", {})
    state["meta"].setdefault("schema", 2)
    state["meta"].setdefault("model_name", PORTFOLIO_NAME)
    state["meta"].setdefault("updated_at", None)
    return state


def save_state(path: str, state: dict[str, Any]) -> None:
    ensure_parent(path)
    state.setdefault("meta", {})
    state["meta"]["schema"] = 2
    state["meta"]["model_name"] = PORTFOLIO_NAME
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
    fast = ema(values, 12)
    slow = ema(values, 26)
    dif = [a - b for a, b in zip(fast, slow)]
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
    rows = http_json(url, retries=3)
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), 0.0) for r in rows]


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
        "1w": "1W",
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
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0.0)) for r in rows]


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
                if not inst_id.endswith("-USDT-SWAP"):
                    continue
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


def fetch_bundle(symbol: str) -> tuple[dict[str, dict[str, float]], dict[str, list[Candle]]]:
    candle_map: dict[str, list[Candle]] = {}
    bundle: dict[str, dict[str, float]] = {}
    for interval in MACRO_TIMEFRAMES:
        candles = crypto_klines(symbol, interval)
        candle_map[interval] = candles
        bundle[interval] = summarize(candles)
    for interval in ("1w", "1d", "4h", "1h"):
        if interval in candle_map:
            bundle[f"{interval}_pullbacks"], bundle[f"{interval}_higher_low"] = pullback_quality(candle_map[interval])
            bundle[f"{interval}_rebounds"], bundle[f"{interval}_lower_high"] = rebound_quality(candle_map[interval])
    return bundle, candle_map


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
    return min(len(points), 3), points[-1] >= points[-2] * 0.985


def rebound_quality(candles: list[Candle]) -> tuple[int, bool]:
    highs = [c.high for c in candles[-40:]]
    points = pivots(highs, "high")
    if len(points) < 2:
        return len(points), False
    return min(len(points), 3), points[-1] <= points[-2] * 1.015


def risk_reward_long(price: float, invalid: float, target1: float) -> float:
    risk = price - invalid
    reward = target1 - price
    return reward / risk if risk > 0 else 0.0


def risk_reward_short(price: float, invalid: float, target1: float) -> float:
    risk = invalid - price
    reward = price - target1
    return reward / risk if risk > 0 else 0.0


def entry_gap_pct(price: float, entry_low: float, entry_high: float) -> float:
    if entry_low <= price <= entry_high:
        return 0.0
    ref = entry_low if price < entry_low else entry_high
    return abs(pct(price, ref)) if ref else 999.0


def long_structure_broken(bundle: dict[str, dict[str, float]]) -> bool:
    h1 = bundle["1h"]
    h2 = bundle["2h"]
    h4 = bundle["4h"]
    support = min(h1["low20"], h2["low20"], h4["low20"])
    return h1["close"] < support * 0.995


def short_structure_broken(bundle: dict[str, dict[str, float]]) -> bool:
    h1 = bundle["1h"]
    h2 = bundle["2h"]
    h4 = bundle["4h"]
    resistance = max(h1["high20"], h2["high20"], h4["high20"])
    return h1["close"] > resistance * 1.005


def vegas_bounds(frame: dict[str, float]) -> tuple[float, float]:
    low = min(frame["ema144"], frame["ema169"])
    high = max(frame["ema144"], frame["ema169"])
    return low, high


def macd_repairing_to_zero(frame: dict[str, float]) -> bool:
    improving_hist = frame["hist"] >= frame["hist_prev"]
    near_zero = abs(frame["dif"]) <= frame["close"] * 0.025
    bullish_crossing = frame["dif"] >= frame["dea"] or frame["hist"] > 0
    return improving_hist and (near_zero or bullish_crossing)


def small_reversal(frame: dict[str, float], direction: str) -> bool:
    if direction == "做多":
        return (frame["close"] >= frame["ema20"] or frame["close"] >= frame["ema24"]) and frame["hist"] >= frame["hist_prev"] and frame["rsi"] >= 42
    return (frame["close"] <= frame["ema20"] or frame["close"] <= frame["ema24"]) and frame["hist"] <= frame["hist_prev"] and frame["rsi"] <= 58


def is_long_direction(direction: str) -> bool:
    return direction == "做多"


def is_short_direction(direction: str) -> bool:
    return direction == "做空"


def detect_market_state(btc_4h: dict[str, float], eth_4h: dict[str, float], btc_1h: dict[str, float]) -> str:
    acute = btc_1h["close"] < btc_1h["ema20"] and btc_1h["rsi"] < 35 and pct(btc_1h["close"], btc_1h["ema20"]) < -2.5
    weak = (
        btc_4h["close"] < btc_4h["ema20"]
        and eth_4h["close"] < eth_4h["ema20"]
        and btc_4h["close"] < btc_4h["ema52"]
        and eth_4h["close"] < eth_4h["ema52"]
    )
    strong = (
        btc_4h["close"] > btc_4h["ema20"]
        and eth_4h["close"] > eth_4h["ema20"]
        and btc_1h["rsi"] >= 50
        and eth_4h["hist"] >= eth_4h["hist_prev"]
    )
    if acute:
        return "急跌"
    if weak:
        return "弱"
    if strong:
        return "强"
    return "震荡"


def near_any_band(price: float, values: list[float], max_distance_pct: float) -> bool:
    return min(abs(pct(price, value)) for value in values if value > 0) <= max_distance_pct if values else False


def model_score_base(direction: str, market_state: str) -> int:
    if direction == "做多":
        return {"强": 20, "震荡": 14, "弱": 6, "急跌": 2}.get(market_state, 0)
    return {"强": 4, "震荡": 10, "弱": 18, "急跌": 20}.get(market_state, 0)


def long_cap_for_market(market_state: str) -> str:
    return "A类" if market_state in {"强", "震荡"} else "B类观察，不追单"


def short_cap_for_market(market_state: str) -> str:
    return "A类" if market_state in {"弱", "急跌"} else "B类观察，不追空"


def evaluate_long(display_symbol: str, actual_symbol: str, bundle: dict[str, dict[str, float]], market_state: str, max_distance_pct: float, min_rr: float, model_name: str) -> Signal | None:
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h2 = bundle["2h"]
    h1 = bundle["1h"]
    m15 = bundle["15m"]
    price = h1["close"]

    if h1["rsi"] > 75 and not small_reversal(h1, "做多") and not small_reversal(m15, "做多"):
        return None
    if market_state == "急跌":
        return None

    pullbacks = int(bundle.get("1h_pullbacks", 0) or 0)
    higher_low = bool(bundle.get("1h_higher_low", False))
    near_band = near_any_band(price, [h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"], h2["ema24"], h2["ema52"]], max_distance_pct)
    daily_ok = daily["close"] >= min(daily["ema20"], daily["ema52"])
    h4_ok = h4["close"] >= min(h4["ema20"], h4["ema52"]) or macd_repairing_to_zero(h4)
    trigger_ok = small_reversal(m15, "做多") and small_reversal(h1, "做多")
    partial_trigger = small_reversal(m15, "做多") or small_reversal(h1, "做多")
    volume_ok = m15["vol"] >= m15["vol_ma10"] * 0.8

    if not near_band or pullbacks < 1:
        return None
    if price > max(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * (1 + max_distance_pct / 100):
        return None
    if price < min(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * (1 - max_distance_pct / 100):
        return None

    entry_low = min(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * 0.995
    entry_high = max(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * 1.01
    invalid = min(h1["low20"], h2["low20"], entry_low * 0.975)
    target1 = max(h1["high20"], h4["high20"], price + (price - invalid) * 2.2)
    rr = risk_reward_long(price, invalid, target1)
    if rr < min_rr:
        return None
    if entry_gap_pct(price, entry_low, entry_high) > max_distance_pct:
        return None
    if not (daily_ok or h4_ok):
        return None
    if long_structure_broken(bundle):
        return None

    score = model_score_base("做多", market_state)
    score += 18 if daily_ok else 0
    score += 10 if h4_ok else 0
    score += 10 if pullbacks >= 2 else 6
    score += 6 if higher_low else 0
    score += 12 if trigger_ok else (6 if partial_trigger else 0)
    score += 6 if volume_ok else 0
    score += 8 if rr >= 2.0 else 0
    score += 6 if rr >= 3.0 else 0

    if score >= 85 and trigger_ok and volume_ok and h4_ok and pullbacks >= 2 and higher_low and market_state == "强":
        grade = "A类"
    elif score >= 70 and market_state in {"强", "震荡", "弱"} and (partial_trigger or entry_low <= price <= entry_high):
        grade = "B类观察，不追单"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "平台突破回踩" if pullbacks >= 2 else "主升回踩"
    setup_state = f"{pullbacks}段回调 + {'动能修复' if macd_repairing_to_zero(h1) else '等待确认'}"
    reason = f"{market_state}环境；{setup_state}；{'1H反包确认' if trigger_ok else '等待1H确认'}；2H/4H结构承接"
    action = "等待触发确认后按失效位执行" if grade == "A类" else "观察，不追单"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做多",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )


def evaluate_short(display_symbol: str, actual_symbol: str, bundle: dict[str, dict[str, float]], market_state: str, max_distance_pct: float, min_rr: float, model_name: str) -> Signal | None:
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h2 = bundle["2h"]
    h1 = bundle["1h"]
    m15 = bundle["15m"]
    price = h1["close"]

    if h1["rsi"] < 25 and not small_reversal(h1, "做空") and not small_reversal(m15, "做空"):
        return None
    if market_state == "强":
        return None

    rebounds = int(bundle.get("1h_rebounds", 0) or 0)
    lower_high = bool(bundle.get("1h_lower_high", False))
    near_band = near_any_band(price, [h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"], h2["ema24"], h2["ema52"]], max_distance_pct)
    daily_ok = daily["close"] <= max(daily["ema20"], daily["ema52"])
    h4_ok = h4["close"] <= max(h4["ema20"], h4["ema52"]) or h4["hist"] <= h4["hist_prev"]
    trigger_ok = small_reversal(m15, "做空") and small_reversal(h1, "做空")
    partial_trigger = small_reversal(m15, "做空") or small_reversal(h1, "做空")
    volume_ok = m15["vol"] >= m15["vol_ma10"] * 0.8

    if not near_band or rebounds < 1:
        return None
    if price < min(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * (1 - max_distance_pct / 100):
        return None
    if price > max(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * (1 + max_distance_pct / 100):
        return None

    entry_low = min(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * 0.99
    entry_high = max(h1["ema24"], h1["ema52"], h1["ema144"], h1["ema169"]) * 1.005
    invalid = max(h1["high20"], h2["high20"], entry_high * 1.025)
    target1 = min(h1["low20"], h4["low20"], price - (invalid - price) * 2.2)
    rr = risk_reward_short(price, invalid, target1)
    if rr < min_rr:
        return None

    if entry_gap_pct(price, entry_low, entry_high) > max_distance_pct:
        return None
    if not (daily_ok or h4_ok):
        return None
    if short_structure_broken(bundle):
        return None

    score = model_score_base("做空", market_state)
    score += 18 if daily_ok else 0
    score += 10 if h4_ok else 0
    score += 10 if rebounds >= 2 else 6
    score += 6 if lower_high else 0
    score += 12 if trigger_ok else (6 if partial_trigger else 0)
    score += 6 if volume_ok else 0
    score += 8 if rr >= 2.0 else 0
    score += 6 if rr >= 3.0 else 0

    if score >= 85 and trigger_ok and volume_ok and h4_ok and rebounds >= 2 and lower_high and market_state in {"弱", "急跌"}:
        grade = "A类"
    elif score >= 70 and market_state in {"震荡", "弱", "急跌"} and (partial_trigger or entry_low <= price <= entry_high):
        grade = "B类观察，不追空"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "反弹承压" if rebounds >= 2 else "空头延续"
    setup_state = f"{rebounds}段反弹 + {'动能转弱' if h1['hist'] <= h1['hist_prev'] else '等待确认'}"
    reason = f"{market_state}环境；{setup_state}；{'1H承压确认' if trigger_ok else '等待1H确认'}；2H/4H压力位承压"
    action = "等待反弹承压后按失效位执行" if grade == "A类" else "观察，不追空"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做空",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )


def evaluate_legacy_long(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    market_state: str,
    max_distance_pct: float,
    min_rr: float,
    model_name: str,
) -> Signal | None:
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h2 = bundle["2h"]
    h1 = bundle["1h"]
    m15 = bundle["15m"]
    price = h1["close"]

    if market_state == "急跌" or h1["rsi"] > 76:
        return None

    pullbacks = int(bundle.get("1h_pullbacks", 0) or 0)
    higher_low = bool(bundle.get("1h_higher_low", False))
    near_band = near_any_band(price, [h1["ema20"], h1["ema24"], h1["ema52"], h2["ema20"], h2["ema24"], h2["ema52"]], max_distance_pct + 0.5)
    daily_ok = daily["close"] >= daily["ema20"] or daily["close"] >= daily["ema52"]
    h4_ok = h4["close"] >= h4["ema20"] and h4["hist"] >= h4["hist_prev"]
    trigger_ok = m15["close"] >= m15["ema20"] and m15["hist"] >= m15["hist_prev"] and m15["rsi"] >= 44
    volume_ok = m15["vol"] >= m15["vol_ma10"] * 0.7

    if not daily_ok or not h4_ok or not near_band or pullbacks < 1 or not higher_low:
        return None

    entry_low = min(h1["ema20"], h1["ema24"], h1["ema52"]) * 0.993
    entry_high = max(h1["ema20"], h1["ema24"], h1["ema52"]) * 1.015
    if price > entry_high * 1.03:
        return None

    invalid = min(h1["low20"], h2["low20"], entry_low * 0.972)
    target1 = max(h1["high20"], price + (price - invalid) * 2.0)
    rr = risk_reward_long(price, invalid, target1)
    if rr < min_rr:
        return None

    score = model_score_base("做多", market_state)
    score += 16 if daily_ok else 0
    score += 12 if h4_ok else 0
    score += 10 if pullbacks >= 2 else 6
    score += 5 if higher_low else 0
    score += 10 if trigger_ok else 4
    score += 6 if volume_ok else 0
    score += 6 if rr >= 2.0 else 0

    if score >= 82 and trigger_ok and volume_ok and market_state == "强" and entry_low <= price <= entry_high * 1.01:
        grade = "A类"
    elif score >= 68 and entry_low <= price <= entry_high:
        grade = "B类观察，不追单"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "主升回踩" if pullbacks == 1 else "平台突破回踩"
    setup_state = f"{pullbacks}段回调 + {'量能确认' if volume_ok else '等待量能'}"
    reason = f"{market_state}环境；{stage}；{'1H转强' if trigger_ok else '等待1H确认'}；4H趋势未破"
    action = "等待触发确认后按失效位执行" if grade == "A类" else "观察，不追单"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做多",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )


def evaluate_legacy_short(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    market_state: str,
    max_distance_pct: float,
    min_rr: float,
    model_name: str,
) -> Signal | None:
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h2 = bundle["2h"]
    h1 = bundle["1h"]
    m15 = bundle["15m"]
    price = h1["close"]

    if market_state == "强" or h1["rsi"] < 24:
        return None

    rebounds = int(bundle.get("1h_rebounds", 0) or 0)
    lower_high = bool(bundle.get("1h_lower_high", False))
    near_band = near_any_band(price, [h1["ema20"], h1["ema24"], h1["ema52"], h2["ema20"], h2["ema24"], h2["ema52"]], max_distance_pct + 0.5)
    daily_ok = daily["close"] <= daily["ema20"] or daily["close"] <= daily["ema52"]
    h4_ok = h4["close"] <= h4["ema20"] and h4["hist"] <= h4["hist_prev"]
    trigger_ok = m15["close"] <= m15["ema20"] and m15["hist"] <= m15["hist_prev"] and m15["rsi"] <= 56
    volume_ok = m15["vol"] >= m15["vol_ma10"] * 0.7

    if not daily_ok or not h4_ok or not near_band or rebounds < 1 or not lower_high:
        return None

    entry_low = min(h1["ema20"], h1["ema24"], h1["ema52"]) * 0.985
    entry_high = max(h1["ema20"], h1["ema24"], h1["ema52"]) * 1.008
    if price < entry_low * 0.97:
        return None

    invalid = max(h1["high20"], h2["high20"], entry_high * 1.022)
    target1 = min(h1["low20"], price - (invalid - price) * 2.0)
    rr = risk_reward_short(price, invalid, target1)
    if rr < min_rr:
        return None

    score = model_score_base("做空", market_state)
    score += 16 if daily_ok else 0
    score += 12 if h4_ok else 0
    score += 10 if rebounds >= 2 else 6
    score += 5 if lower_high else 0
    score += 10 if trigger_ok else 4
    score += 6 if volume_ok else 0
    score += 6 if rr >= 2.0 else 0

    if score >= 82 and trigger_ok and volume_ok and market_state in {"弱", "急跌"} and entry_low <= price <= entry_high * 1.01:
        grade = "A类"
    elif score >= 68 and entry_low <= price <= entry_high:
        grade = "B类观察，不追空"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "反弹承压" if rebounds == 1 else "空头延续"
    setup_state = f"{rebounds}段反弹 + {'量能确认' if volume_ok else '等待量能'}"
    reason = f"{market_state}环境；{stage}；{'1H承压' if trigger_ok else '等待1H确认'}；4H压力未收回"
    action = "等待反弹承压后按失效位执行" if grade == "A类" else "观察，不追空"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做空",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )



def macro_long_cap_for_market(market_state: str) -> str:
    if market_state in {"强", "震荡"}:
        return "A类"
    return "B类观察，不追单"


def macro_short_cap_for_market(market_state: str) -> str:
    if market_state in {"弱", "急跌"}:
        return "A类"
    return "B类观察，不追单"


def evaluate_macro_long(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    market_state: str,
    max_distance_pct: float,
    min_rr: float,
    model_name: str,
) -> Signal | None:
    weekly = bundle["1w"]
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h1 = bundle["1h"]
    price = h4["close"]

    weekly_pullbacks = int(bundle.get("1w_pullbacks", 0) or 0)
    daily_pullbacks = int(bundle.get("1d_pullbacks", 0) or 0)
    h4_pullbacks = int(bundle.get("4h_pullbacks", 0) or 0)
    weekly_higher_low = bool(bundle.get("1w_higher_low", False))
    daily_higher_low = bool(bundle.get("1d_higher_low", False))
    h4_higher_low = bool(bundle.get("4h_higher_low", False))

    weekly_repair = weekly["close"] >= weekly["ema20"] and weekly["hist"] >= weekly["hist_prev"] and weekly["rsi"] >= 44
    daily_repair = daily["close"] >= daily["ema20"] and daily["hist"] >= daily["hist_prev"] and daily["rsi"] >= 46
    h4_trigger = h4["close"] >= h4["ema20"] and h4["hist"] >= h4["hist_prev"] and h4["rsi"] >= 42
    near_band = near_any_band(
        price,
        [weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]],
        max_distance_pct,
    )

    if not weekly_repair:
        return None
    if market_state == "急跌" and not (daily_repair and h4_trigger and weekly_higher_low):
        return None

    structure_ok = weekly_pullbacks >= 1 and daily_pullbacks >= 1 and h4_pullbacks >= 1 and weekly_higher_low and daily_higher_low and h4_higher_low
    if not structure_ok and not (weekly_higher_low and daily_higher_low and h4_higher_low):
        return None
    if not near_band:
        return None
    if price > max(weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]) * (1 + max_distance_pct / 100):
        return None

    entry_low = min(weekly["ema20"], daily["ema20"], h4["ema20"], h4["ema52"]) * 0.993
    entry_high = max(weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]) * 1.01
    invalid = min(weekly["low20"], daily["low20"], h4["low20"], entry_low * 0.968)
    target1 = max(weekly["high20"], daily["high20"], h4["high20"], price + (price - invalid) * 2.5)
    rr = risk_reward_long(price, invalid, target1)
    if rr < min_rr:
        return None
    if entry_gap_pct(price, entry_low, entry_high) > max_distance_pct:
        return None

    score = 0
    score += 18 if weekly_repair else 0
    score += 16 if daily_repair else 0
    score += 14 if h4_trigger else 6
    score += 8 if structure_ok else 4
    score += 8 if near_band else 0
    score += 8 if rr >= 2.0 else 0
    score += 4 if rr >= 3.0 else 0
    score += 4 if market_state in {"强", "震荡"} else 0

    if score >= 82 and weekly_repair and daily_repair and h4_trigger and structure_ok and market_state in {"强", "震荡"}:
        grade = "A类"
    elif score >= 68 and (daily_repair or h4_trigger):
        grade = "B类观察，不追单"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "长期筑底确认" if weekly_higher_low and daily_higher_low and h4_trigger else "周线修复回踩"
    setup_state = f"周线修复 + 日线{'抬高低点' if daily_higher_low else '待修复'} + 4H{'触发确认' if h4_trigger else '等待确认'}"
    reason = f"周线修复，日线结构改善，4H回踩确认，目标看向前高区"
    action = "按失效位执行，等待目标1" if grade == "A类" else "观察，不追单"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做多",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )


def evaluate_macro_short(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    market_state: str,
    max_distance_pct: float,
    min_rr: float,
    model_name: str,
) -> Signal | None:
    weekly = bundle["1w"]
    daily = bundle["1d"]
    h4 = bundle["4h"]
    h1 = bundle["1h"]
    price = h4["close"]

    weekly_rebounds = int(bundle.get("1w_rebounds", 0) or 0)
    daily_rebounds = int(bundle.get("1d_rebounds", 0) or 0)
    h4_rebounds = int(bundle.get("4h_rebounds", 0) or 0)
    weekly_lower_high = bool(bundle.get("1w_lower_high", False))
    daily_lower_high = bool(bundle.get("1d_lower_high", False))
    h4_lower_high = bool(bundle.get("4h_lower_high", False))

    weekly_weak = weekly["close"] <= weekly["ema20"] and weekly["hist"] <= weekly["hist_prev"] and weekly["rsi"] <= 58
    daily_break = daily["close"] < daily["ema20"] and daily["close"] < daily["ema52"] and daily["hist"] <= daily["hist_prev"]
    h4_reject = h4["close"] <= h4["ema20"] and h4["hist"] <= h4["hist_prev"] and h4["rsi"] <= 58
    near_band = near_any_band(
        price,
        [weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]],
        max_distance_pct,
    )

    if not weekly_weak:
        return None
    if market_state == "强":
        return None
    if not near_band:
        return None

    structure_ok = weekly_rebounds >= 1 and daily_rebounds >= 1 and h4_rebounds >= 1 and weekly_lower_high and daily_lower_high and h4_lower_high
    if not structure_ok and not (weekly_lower_high and daily_lower_high and h4_lower_high):
        return None
    if not (daily_break or h4_reject):
        return None
    if price < min(weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]) * (1 - max_distance_pct / 100):
        return None

    entry_low = min(weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]) * 0.99
    entry_high = max(weekly["ema20"], weekly["ema52"], daily["ema20"], daily["ema52"], h4["ema20"], h4["ema52"]) * 1.006
    invalid = max(weekly["high20"], daily["high20"], h4["high20"], entry_high * 1.03)
    target1 = min(weekly["low20"], daily["low20"], h4["low20"], price - (invalid - price) * 2.5)
    rr = risk_reward_short(price, invalid, target1)
    if rr < min_rr:
        return None
    if entry_gap_pct(price, entry_low, entry_high) > max_distance_pct:
        return None

    score = 0
    score += 18 if weekly_weak else 0
    score += 16 if daily_break else 0
    score += 14 if h4_reject else 6
    score += 8 if structure_ok else 4
    score += 8 if near_band else 0
    score += 8 if rr >= 2.0 else 0
    score += 4 if rr >= 3.0 else 0
    score += 4 if market_state in {"弱", "急跌"} else 0

    if score >= 82 and weekly_weak and daily_break and h4_reject and structure_ok and market_state in {"弱", "急跌", "震荡"}:
        grade = "A类"
    elif score >= 68 and (daily_break or h4_reject):
        grade = "B类观察，不追单"
    else:
        return None

    status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    stage = "长期顶部确认" if weekly_lower_high and daily_lower_high and h4_reject else "周线转弱回抽"
    setup_state = f"周线转弱 + 日线{'跌破结构' if daily_break else '等待确认'} + 4H{'反抽承压' if h4_reject else '等待确认'}"
    reason = f"周线转弱，日线破位，4H反抽承压，目标看向前低区"
    action = "按失效位执行，等待目标1" if grade == "A类" else "观察，不追单"

    return Signal(
        model_name=model_name,
        market="币圈",
        symbol=display_symbol,
        actual_symbol=actual_symbol,
        direction="做空",
        grade=grade,
        stage=stage,
        setup_state=setup_state,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        market_state=market_state,
        reason=reason,
        action=action,
        score=int(score),
    )


def choose_signal(long_sig: Signal | None, short_sig: Signal | None, market_state: str) -> Signal | None:
    if long_sig and short_sig:
        if long_sig.grade != short_sig.grade:
            return long_sig if long_sig.grade == "A类" else short_sig
        if long_sig.score != short_sig.score:
            return long_sig if long_sig.score > short_sig.score else short_sig
        if market_state in {"强", "震荡"}:
            return long_sig
        return short_sig
    return long_sig or short_sig


def render_grade(sig: Signal) -> str:
    return sig.grade if sig.grade == "A类" else "B类"


def render_push_message(sig: Signal, event: str = "push", previous_status: str | None = None) -> str:
    title = f"趋势机会｜{sig.model_name}｜{sig.symbol}｜{sig.direction}｜{render_grade(sig)}"
    lines = [
        title,
        "",
        f"模型：{sig.model_name}",
        f"现价：{fmt_price(sig.price)}",
        f"状态：{sig.status}",
    ]
    if previous_status:
        lines.append(f"原状态：{previous_status}")
    lines.extend(
        [
            f"入场区：{fmt_price(sig.entry_low)}-{fmt_price(sig.entry_high)}",
            f"失效位：{fmt_price(sig.invalid)}",
            f"目标1：{fmt_price(sig.target1)}",
            f"阶段：{sig.stage}",
            f"原因：{sig.reason}",
            f"处理：{sig.action}",
        ]
    )
    if event != "push":
        lines.insert(5, f"事件：{event}")
    return "\n".join(lines)


def feishu_send(config: dict[str, Any], text: str) -> None:
    feishu = config.get("feishu", {})
    webhook = os.environ.get(feishu.get("webhook_env", "FEISHU_WEBHOOK"), "")
    dry_run = os.environ.get(feishu.get("dry_run_env", "DRY_RUN"), "").lower() in {"1", "true", "yes"}
    if not feishu.get("enabled", True) or dry_run or not webhook:
        print("DRY_RUN or missing FEISHU_WEBHOOK; message:")
        print(text)
        return
    http_post_json(webhook, {"msg_type": "text", "content": {"text": text}})


def normalized_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    return {key: snapshot.get(key) for key in SNAPSHOT_FIELDS}


def snapshot_changed(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    return normalized_snapshot(old) != normalized_snapshot(new)


def make_snapshot(sig: Signal, event: str, previous_status: str | None = None, current_price: float | None = None, trigger_price: float | None = None, final_r: float = 0.0, max_floating_r: float = 0.0, max_drawdown_r: float = 0.0, open_: bool = True, triggered: bool = False, notified: bool = False, origin_signal_id: str | None = None) -> dict[str, Any]:
    price = current_price if current_price is not None else sig.price
    snapshot = {
        "model_name": sig.model_name,
        "family_key": sig.family_key,
        "signal_id": sig.signal_id,
        "market": sig.market,
        "symbol": sig.symbol,
        "actual_symbol": sig.actual_symbol,
        "direction": sig.direction,
        "grade": sig.grade,
        "stage": sig.stage,
        "setup_state": sig.setup_state,
        "status": sig.status,
        "last_event": event,
        "previous_status": previous_status,
        "price": round(price, 8),
        "push_price": round(sig.price, 8),
        "entry_low": round(sig.entry_low, 8),
        "entry_high": round(sig.entry_high, 8),
        "invalid": round(sig.invalid, 8),
        "target1": round(sig.target1, 8),
        "market_state": sig.market_state,
        "reason": sig.reason,
        "action": sig.action,
        "score": int(sig.score),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "open": open_,
        "triggered": triggered,
        "trigger_price": round(trigger_price, 8) if trigger_price is not None else None,
        "final_r": round(final_r, 4),
        "max_floating_r": round(max_floating_r, 4),
        "max_drawdown_r": round(max_drawdown_r, 4),
        "notified": notified,
    }
    if origin_signal_id:
        snapshot["origin_signal_id"] = origin_signal_id
    return snapshot


def ledger_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    row = dict(snapshot)
    row["ledger_time"] = now_iso()
    return row


def is_notifiable(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("grade") in {"A类", "B类"} and snapshot.get("last_event") in NOTIFY_EVENTS


def event_priority(snapshot: dict[str, Any]) -> int:
    return {
        "target1": 5,
        "invalid": 5,
        "expire": 4,
        "trigger": 3,
        "upgrade": 2,
        "push": 1,
        "touch_entry": 0,
    }.get(str(snapshot.get("last_event")), -1)


def external_symbol_key(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("symbol") or snapshot.get("actual_symbol") or snapshot.get("family_key") or "")


def external_signal_rank(snapshot: dict[str, Any]) -> tuple[int, int, int, int]:
    grade_rank = 1 if snapshot.get("grade") == "A类" else 0
    return (
        grade_rank,
        event_priority(snapshot),
        int(snapshot.get("score", 0) or 0),
        MODEL_PRIORITY.get(str(snapshot.get("model_name")), -1),
    )


def select_external_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners: dict[str, dict[str, Any]] = {}
    for event in events:
        if not is_notifiable(event):
            continue
        key = external_symbol_key(event)
        current = winners.get(key)
        if current is None or external_signal_rank(event) > external_signal_rank(current):
            winners[key] = event
    return list(winners.values())


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(CN_TZ)
    except Exception:
        return None


def should_run_full_scan(state: dict[str, Any], config: dict[str, Any]) -> bool:
    scan_cfg = config.get("scan", {})
    interval_minutes = int(scan_cfg.get("full_scan_interval_minutes", 60))
    last_full_scan_at = parse_time(state.get("meta", {}).get("last_full_scan_at"))
    if last_full_scan_at is None:
        return True
    return datetime.now(CN_TZ) - last_full_scan_at >= timedelta(minutes=interval_minutes)


def hours_since(value: str | None) -> float | None:
    dt = parse_time(value)
    if dt is None:
        return None
    return (datetime.now(CN_TZ) - dt).total_seconds() / 3600


def update_open_trade(snapshot: dict[str, Any], bundle: dict[str, dict[str, float]], expiry_hours: int) -> dict[str, Any] | None:
    current = bundle["1h"]["close"]
    h1 = bundle["1h"]
    m15 = bundle["15m"]
    old_status = snapshot.get("status")
    triggered = bool(snapshot.get("triggered"))
    entry_low = float(snapshot["entry_low"])
    entry_high = float(snapshot["entry_high"])
    invalid = float(snapshot["invalid"])
    target1 = float(snapshot["target1"])
    direction = str(snapshot["direction"])
    push_price = float(snapshot["push_price"])
    trigger_price = snapshot.get("trigger_price")
    entry_ref = float(trigger_price if trigger_price is not None else push_price)
    risk = abs(entry_ref - invalid) or 1e-9
    current_r = (current - entry_ref) / risk if is_long_direction(direction) else (entry_ref - current) / risk
    max_float = max(float(snapshot.get("max_floating_r", 0.0) or 0.0), current_r)
    max_dd = min(float(snapshot.get("max_drawdown_r", 0.0) or 0.0), current_r)
    new_status = old_status
    event = None
    open_ = bool(snapshot.get("open", True))
    final_r = float(snapshot.get("final_r", 0.0) or 0.0)
    trigger_price_new = trigger_price

    if not triggered:
        if entry_low <= current <= entry_high and old_status != "触达入场区":
            new_status = "触达入场区"
            event = "touch_entry"

        confirm_long = is_long_direction(direction) and current >= entry_high and h1["close"] > h1["ema20"] and h1["hist"] >= h1["hist_prev"] and m15["close"] > m15["ema20"]
        confirm_short = is_short_direction(direction) and current <= entry_low and h1["close"] < h1["ema20"] and h1["hist"] <= h1["hist_prev"] and m15["close"] < m15["ema20"]
        if confirm_long or confirm_short:
            new_status = "触发确认"
            event = "trigger"
            triggered = True
            trigger_price_new = current
            open_ = True
            final_r = 0.0
        else:
            age = hours_since(snapshot.get("created_at") or snapshot.get("updated_at"))
            if age is not None and age >= expiry_hours:
                new_status = "过期"
                event = "expire"
                open_ = False
                final_r = 0.0
    else:
        target_hit = (is_long_direction(direction) and current >= target1) or (is_short_direction(direction) and current <= target1)
        invalid_hit = (is_long_direction(direction) and current <= invalid) or (is_short_direction(direction) and current >= invalid)
        if target_hit and old_status != "目标1达成":
            new_status = "目标1达成"
            event = "target1"
            open_ = False
            final_r = current_r
        elif invalid_hit and old_status != "失效":
            new_status = "失效"
            event = "invalid"
            open_ = False
            final_r = -1.0
        else:
            age = hours_since(snapshot.get("trigger_time") or snapshot.get("created_at") or snapshot.get("updated_at"))
            if age is not None and age >= expiry_hours:
                new_status = "过期"
                event = "expire"
                open_ = False
                final_r = current_r

    if event is None or new_status == old_status:
        snapshot["max_floating_r"] = round(max_float, 4)
        snapshot["max_drawdown_r"] = round(max_dd, 4)
        snapshot["final_r"] = round(final_r, 4)
        snapshot["trigger_price"] = round(trigger_price_new, 8) if trigger_price_new is not None else None
        snapshot["triggered"] = triggered
        snapshot["open"] = open_
        return None

    updated = dict(snapshot)
    updated["status"] = new_status
    updated["last_event"] = event
    updated["price"] = round(current, 8)
    updated["trigger_price"] = round(trigger_price_new, 8) if trigger_price_new is not None else None
    updated["triggered"] = triggered
    updated["open"] = open_
    updated["final_r"] = round(final_r, 4)
    updated["max_floating_r"] = round(max_float, 4)
    updated["max_drawdown_r"] = round(max_dd, 4)
    updated["updated_at"] = now_iso()
    return updated


def update_open_signals(state: dict[str, Any], bundle_cache: dict[str, dict[str, dict[str, float]]], config: dict[str, Any]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    expiry_hours = int(config["scan"]["expiry_hours"])
    signals = state.setdefault("signals", {})
    for family_key, snapshot in list(signals.items()):
        if not snapshot.get("open", True):
            continue
        actual_symbol = snapshot.get("actual_symbol") or snapshot.get("symbol")
        if not actual_symbol:
            continue
        try:
            bundle = bundle_cache.setdefault(actual_symbol, build_bundle(actual_symbol))
        except Exception as exc:  # noqa: BLE001
            print(f"skip open family {family_key}: {exc}", file=sys.stderr)
            continue
        updated = update_open_trade(snapshot, bundle, expiry_hours)
        if updated is None:
            continue
        signals[family_key] = updated
        updates.append(updated)
    return updates


def build_bundle(symbol: str) -> dict[str, dict[str, float]]:
    bundle, _ = fetch_bundle(symbol)
    return bundle


def evaluate_symbol(
    display_symbol: str,
    actual_symbol: str,
    bundle: dict[str, dict[str, float]],
    market_state: str,
    max_distance_pct: float,
    min_rr: float,
    model_name: str,
    variant: str,
) -> Signal | None:
    if variant == "legacy":
        long_sig = evaluate_legacy_long(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
        short_sig = evaluate_legacy_short(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
    elif variant == "macro":
        long_sig = evaluate_macro_long(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
        short_sig = evaluate_macro_short(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
    else:
        long_sig = evaluate_long(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
        short_sig = evaluate_short(display_symbol, actual_symbol, bundle, market_state, max_distance_pct, min_rr, model_name)
    return choose_signal(long_sig, short_sig, market_state)


def scan_crypto(config: dict[str, Any], state: dict[str, Any], bundle_cache: dict[str, dict[str, dict[str, float]]]) -> tuple[list[Signal], str]:
    crypto_cfg = config.get("crypto", {})
    macro_cfg = config.get("macro", {})
    if not crypto_cfg.get("enabled", True):
        return [], "震荡"

    models = list(config.get("models", [])) or [
        {"name": config.get("model", {}).get("name", MODEL_NAME), "variant": "breakout"},
        {"name": LEGACY_MODEL_NAME, "variant": "legacy"},
        {"name": MACRO_MODEL_NAME, "variant": "macro"},
    ]
    symbols = list(crypto_cfg.get("symbols", []))
    macro_symbols = list(macro_cfg.get("symbols", DEFAULT_MACRO_SYMBOLS) or DEFAULT_MACRO_SYMBOLS)
    symbol_map = crypto_cfg.get("symbol_map", {})
    ticker_map = binance_24h_tickers()

    def get_bundle(actual_symbol: str) -> dict[str, dict[str, float]]:
        if actual_symbol not in bundle_cache:
            bundle_cache[actual_symbol] = build_bundle(actual_symbol)
        return bundle_cache[actual_symbol]

    try:
        btc_bundle = get_bundle("BTCUSDT")
        eth_bundle = get_bundle("ETHUSDT")
    except Exception as exc:  # noqa: BLE001
        print(f"market bundle unavailable: {exc}", file=sys.stderr)
        return [], "震荡"

    market_state = detect_market_state(btc_bundle["4h"], eth_bundle["4h"], btc_bundle["1h"])
    signals: list[Signal] = []
    for model in models:
        model_name = str(model.get("name", MODEL_NAME))
        variant = str(model.get("variant", "breakout"))
        if variant == "macro" and not macro_cfg.get("enabled", True):
            continue
        scan_symbols = macro_symbols if variant == "macro" else symbols
        model_min_rr = float(macro_cfg.get("min_rr", crypto_cfg.get("min_rr", config["scan"]["min_rr"]))) if variant == "macro" else float(crypto_cfg.get("min_rr", config["scan"]["min_rr"]))
        for display_symbol in scan_symbols:
            actual_symbol = symbol_map.get(display_symbol, display_symbol)
            if actual_symbol not in ticker_map:
                continue
            try:
                bundle = get_bundle(actual_symbol)
            except Exception as exc:  # noqa: BLE001
                print(f"skip crypto {display_symbol}: {exc}", file=sys.stderr)
                continue

            chosen = evaluate_symbol(
                display_symbol,
                actual_symbol,
                bundle,
                market_state,
                float(
                    crypto_cfg.get(
                        "v2_max_distance_to_entry_pct",
                        crypto_cfg.get("max_distance_to_entry_pct", config["scan"]["v2_max_distance_to_entry_pct"]),
                    )
                ),
                model_min_rr,
                model_name,
                variant,
            )
            if chosen is None:
                continue
            signals.append(chosen)

    return signals, market_state


def render_signal_message(sig: Signal, event: str = "push", previous_status: str | None = None) -> str:
    title = f"趋势机会｜{sig.model_name}｜{sig.symbol}｜{sig.direction}｜{render_grade(sig)}"
    lines = [
        title,
        "",
        f"模型：{sig.model_name}",
        f"现价：{fmt_price(sig.price)}",
        f"状态：{sig.status}",
    ]
    if previous_status:
        lines.append(f"原状态：{previous_status}")
    if event != "push":
        lines.append(f"事件：{event}")
    lines.extend(
        [
            f"入场区：{fmt_price(sig.entry_low)}-{fmt_price(sig.entry_high)}",
            f"失效位：{fmt_price(sig.invalid)}",
            f"目标1：{fmt_price(sig.target1)}",
            f"阶段：{sig.stage}",
            f"原因：{sig.reason}",
            f"处理：{sig.action}",
        ]
    )
    return "\n".join(lines)


def notify_and_record(config: dict[str, Any], state: dict[str, Any], snapshot: dict[str, Any]) -> None:
    payload = dict(snapshot)
    payload["notified"] = True
    signal = Signal(
        model_name=payload["model_name"],
        market=payload["market"],
        symbol=payload["symbol"],
        actual_symbol=payload.get("actual_symbol") or payload["symbol"],
        direction=payload["direction"],
        grade=payload["grade"],
        stage=payload["stage"],
        setup_state=payload["setup_state"],
        status=payload["status"],
        price=float(payload["price"]),
        entry_low=float(payload["entry_low"]),
        entry_high=float(payload["entry_high"]),
        invalid=float(payload["invalid"]),
        target1=float(payload["target1"]),
        market_state=payload["market_state"],
        reason=payload["reason"],
        action=payload["action"],
        score=int(payload["score"]),
    )
    message = render_signal_message(signal, event=payload.get("last_event", "push"), previous_status=payload.get("previous_status"))
    feishu_send(config, message)


def render_table(title: str, rows: list[tuple[str, Any]]) -> str:
    if not rows:
        return f"## {title}\n无样本\n"
    lines = [f"## {title}", "| 项目 | 数值 |", "| --- | --- |"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return "\n".join(lines)


def render_group(title: str, group: dict[str, dict[str, Any]]) -> str:
    if not group:
        return f"## {title}\n无样本\n"
    rows = [f"## {title}", "| 分组 | 样本 | 已触发 | 胜率 | 平均R |", "| --- | --- | --- | --- | --- |"]
    for key in sorted(group):
        item = group[key]
        rows.append(f"| {key} | {item['families']} | {item['triggered']} | {item['win_rate'] * 100:.1f}% | {item['avg_r']:.2f} |")
    rows.append("")
    return "\n".join(rows)


def compute_performance(trades: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for row in trades:
        family = row.get("family_key")
        if not family:
            continue
        ts = row.get("updated_at") or row.get("ledger_time") or row.get("created_at") or ""
        current = latest.get(family)
        if current is None:
            latest[family] = row
            continue
        current_ts = current.get("updated_at") or current.get("ledger_time") or current.get("created_at") or ""
        if ts >= current_ts:
            latest[family] = row

    families = list(latest.values())
    pushed = [row for row in families if row.get("last_event") in {"push", "upgrade"}]
    triggered = [row for row in families if row.get("triggered")]
    wins = [row for row in families if row.get("status") == "目标1达成" and row.get("triggered")]
    losses = [row for row in families if row.get("status") == "失效" and row.get("triggered")]
    expired = [row for row in families if row.get("status") == "过期"]

    closed_r = [float(row.get("final_r", 0.0) or 0.0) for row in families if row.get("status") in FINAL_STATES or row.get("triggered")]
    max_float = [float(row.get("max_floating_r", 0.0) or 0.0) for row in families]
    max_draw = [float(row.get("max_drawdown_r", 0.0) or 0.0) for row in families]

    def grouped(field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in families:
            key = str(row.get(field, "未知"))
            buckets.setdefault(key, []).append(row)
        summary: dict[str, dict[str, Any]] = {}
        for key, rows in buckets.items():
            trig = [r for r in rows if r.get("triggered")]
            win = [r for r in rows if r.get("status") == "目标1达成" and r.get("triggered")]
            rvals = [float(r.get("final_r", 0.0) or 0.0) for r in rows if r.get("status") in FINAL_STATES or r.get("triggered")]
            summary[key] = {
                "families": len(rows),
                "triggered": len(trig),
                "win_rate": round(len(win) / len(trig) if trig else 0.0, 4),
                "avg_r": round(mean(rvals) if rvals else 0.0, 4),
            }
        return summary

    overall = {
        "families": len(families),
        "pushed": len(pushed),
        "triggered": len(triggered),
        "wins": len(wins),
        "losses": len(losses),
        "expired": len(expired),
        "win_rate": round(len(wins) / len(triggered) if triggered else 0.0, 4),
        "effective_rate": round(len(triggered) / len(pushed) if pushed else 0.0, 4),
        "avg_r": round(mean(closed_r) if closed_r else 0.0, 4),
        "max_floating_r": round(max(max_float) if max_float else 0.0, 4),
        "max_drawdown_r": round(min(max_draw) if max_draw else 0.0, 4),
    }

    return {
        "model_name": PORTFOLIO_NAME,
        "updated_at": now_iso(),
        "overall": overall,
        "by_model": grouped("model_name"),
        "by_grade": grouped("grade"),
        "by_direction": grouped("direction"),
        "by_stage": grouped("stage"),
        "by_market_state": grouped("market_state"),
    }


def render_performance_report(perf: dict[str, Any]) -> str:
    overall = perf.get("overall", {})
    lines = [f"# 飞书机会胜率报告", "", f"更新时刻：{perf.get('updated_at', '')}", f"模型：{perf.get('model_name', PORTFOLIO_NAME)}", ""]
    lines.append(
        render_table(
            "总体",
            [
                ("推送链路数", overall.get("families", 0)),
                ("已推送", overall.get("pushed", 0)),
                ("已触发", overall.get("triggered", 0)),
                ("目标1达成", overall.get("wins", 0)),
                ("失效", overall.get("losses", 0)),
                ("过期", overall.get("expired", 0)),
                ("胜率", f"{overall.get('win_rate', 0.0) * 100:.1f}%"),
                ("机会有效率", f"{overall.get('effective_rate', 0.0) * 100:.1f}%"),
                ("平均R", f"{overall.get('avg_r', 0.0):.2f}"),
                ("最大浮盈R", f"{overall.get('max_floating_r', 0.0):.2f}"),
                ("最大浮亏R", f"{overall.get('max_drawdown_r', 0.0):.2f}"),
            ],
        )
    )
    lines.append(render_group("按等级", perf.get("by_grade", {})))
    lines.append(render_group("按模型", perf.get("by_model", {})))
    lines.append(render_group("按方向", perf.get("by_direction", {})))
    lines.append(render_group("按阶段", perf.get("by_stage", {})))
    lines.append(render_group("按大盘环境", perf.get("by_market_state", {})))
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    config = load_config()
    state_path = config["scan"]["state_file"]
    ledger_path = config["scan"]["trade_ledger_file"]
    perf_path = config["scan"]["performance_file"]
    report_path = config["scan"]["performance_report"]

    state = load_state(state_path)
    ledger = load_jsonl(ledger_path)
    bundle_cache: dict[str, dict[str, dict[str, float]]] = {}

    run_full_scan = should_run_full_scan(state, config)
    updates = update_open_signals(state, bundle_cache, config)
    candidate_signals: list[Signal] = []
    market_state = str(state.get("meta", {}).get("last_market_state", "未知"))
    if run_full_scan:
        candidate_signals, market_state = scan_crypto(config, state, bundle_cache)
        state.setdefault("meta", {})["last_full_scan_at"] = now_iso()
        state["meta"]["last_market_state"] = market_state
        state["meta"]["scan_mode"] = "full"
    else:
        state.setdefault("meta", {})["last_open_refresh_at"] = now_iso()
        state["meta"]["scan_mode"] = "open"
    state.setdefault("meta", {})["last_cycle_at"] = now_iso()

    candidate_events: list[dict[str, Any]] = []
    for sig in candidate_signals:
        old = state.setdefault("signals", {}).get(sig.family_key, {})
        event_type = "upgrade" if old and old.get("grade") != sig.grade and old.get("open", True) else "push"
        snapshot = make_snapshot(
            sig,
            event_type,
            previous_status=old.get("status") if old else None,
            open_=True,
            triggered=bool(old.get("triggered")) if old else False,
            notified=bool(old.get("notified")) if old else False,
            origin_signal_id=old.get("signal_id") if old and old.get("grade") != sig.grade else None,
        )
        if old and not snapshot_changed(old, snapshot):
            continue
        state["signals"][sig.family_key] = snapshot
        candidate_events.append(snapshot)

    all_events = updates + candidate_events
    pushed = 0
    for event in sorted(all_events, key=lambda r: (r.get("grade") != "A类", -int(r.get("score", 0) or 0))):
        append_jsonl(ledger_path, ledger_row(event))

    external_events = select_external_events(all_events)
    for event in sorted(
        external_events,
        key=lambda r: (r.get("grade") != "A类", -event_priority(r), -int(r.get("score", 0) or 0)),
    ):
        notify_and_record(config, state, event)
        event["notified"] = True
        state["signals"][event["family_key"]] = event
        pushed += 1

    save_state(state_path, state)

    ledger = load_jsonl(ledger_path)
    perf = compute_performance(ledger)
    write_json(perf_path, perf)
    write_text(report_path, render_performance_report(perf))

    print(
        f"scan done: mode={state.get('meta', {}).get('scan_mode', 'unknown')}, market={market_state}, "
        f"candidates={len(candidate_signals)}, events={len(all_events)}, pushed={pushed}, "
        f"open={sum(1 for v in state['signals'].values() if v.get('open', True))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
