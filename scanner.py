from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


USER_AGENT = "tianji-trend-scanner/1.0"


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
    status: str
    price: float
    entry_low: float
    entry_high: float
    invalid: float
    target1: float
    reason: str
    action: str
    score: int

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}:{self.direction}"


def http_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def load_config() -> dict[str, Any]:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"signals": {}}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


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
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
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
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]
    dif, dea, hist = macd(closes)
    return {
        "close": closes[-1],
        "ema10": ema(closes, 10)[-1],
        "ema20": ema(closes, 20)[-1],
        "ema24": ema(closes, 24)[-1],
        "ema52": ema(closes, 52)[-1],
        "ema144": ema(closes, 144)[-1],
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


def binance_klines(symbol: str, interval: str, limit: int = 220) -> list[Candle]:
    qs = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = f"https://fapi.binance.com/fapi/v1/markPriceKlines?{qs}"
    rows = http_json(url)
    return [
        Candle(
            ts=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=0.0,
        )
        for r in rows
    ]


def yahoo_chart(symbol: str, interval: str, range_: str) -> list[Candle]:
    qs = urllib.parse.urlencode(
        {"interval": interval, "range": range_, "includePrePost": "false", "events": "div,splits"}
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{qs}"
    data = http_json(url)
    result = data["chart"]["result"][0]
    ts = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        vals = [q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals[:4]):
            continue
        out.append(Candle(int(t) * 1000, float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]), float(vals[4] or 0)))
    return out


def eastmoney_klines(secid: str, klt: int, limit: int = 220) -> list[Candle]:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,
        "fqt": 1,
        "end": "20500101",
        "lmt": limit,
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    data = http_json(url)
    rows = (data.get("data") or {}).get("klines") or []
    out = []
    for row in rows:
        parts = row.split(",")
        out.append(Candle(0, float(parts[1]), float(parts[3]), float(parts[4]), float(parts[2]), float(parts[5])))
    return out


def market_state(summaries: list[dict[str, float]]) -> str:
    if not summaries:
        return "震荡"
    strong = 0
    weak = 0
    acute = 0
    for s in summaries:
        c = s["close"]
        if c > s["ema20"] > s["ema52"]:
            strong += 1
        if c < s["ema20"] < s["ema52"]:
            weak += 1
        if pct(c, s["ema20"]) < -3 and s["rsi"] < 35:
            acute += 1
    if acute >= max(1, len(summaries) // 2):
        return "急跌"
    if strong >= max(1, len(summaries) // 2):
        return "强"
    if weak >= max(1, len(summaries) // 2):
        return "弱"
    return "震荡"


def recent_pullback_quality(candles: list[Candle]) -> tuple[int, bool]:
    if len(candles) < 30:
        return 0, False
    lows = [c.low for c in candles[-30:]]
    pivots = []
    for i in range(2, len(lows) - 2):
        if lows[i] == min(lows[i - 2 : i + 3]):
            pivots.append(lows[i])
    if len(pivots) < 2:
        return len(pivots), False
    return min(len(pivots), 3), pivots[-1] >= pivots[-2] * 0.985


def evaluate_long(
    market: str,
    symbol: str,
    daily: list[Candle],
    h60: list[Candle],
    h30: list[Candle],
    battlefield: str,
    strict_leader: bool = False,
) -> Signal | None:
    if len(daily) < 80 or len(h60) < 80 or len(h30) < 50:
        return None
    d = summarize(daily)
    h = summarize(h60)
    m = summarize(h30)
    price = h["close"]

    if battlefield in ("弱", "急跌"):
        return None
    if h["rsi"] > 75:
        return None
    if price < h["low20"] * 1.01:
        return None

    pullbacks, higher_low = recent_pullback_quality(h60)
    near_ema = min(abs(pct(price, h["ema20"])), abs(pct(price, h["ema52"]))) <= 2.5
    daily_ok = d["close"] > d["ema20"] or d["close"] > d["ema52"]
    hourly_ok = h["close"] > h["ema20"] and h["hist"] >= h["hist_prev"]
    trigger_ok = m["close"] > m["ema20"] and m["hist"] > m["hist_prev"] and m["rsi"] >= 45
    volume_ok = m["vol"] >= m["vol_ma10"] * 0.8

    if not daily_ok or not near_ema:
        return None
    if pullbacks < 1 or not higher_low:
        return None

    entry_low = min(h["ema20"], h["ema52"]) * 0.995
    entry_high = max(h["ema20"], h["ema52"]) * 1.012
    if price > entry_high * 1.025:
        return None
    invalid = min(h["low20"], entry_low * 0.975)
    target1 = min(h["high20"], price + (price - invalid) * 2.2)
    risk = price - invalid
    reward = target1 - price
    if risk <= 0 or reward / risk < 2:
        return None

    score = 0
    score += {"强": 20, "震荡": 12}.get(battlefield, 0)
    score += 18 if daily_ok else 0
    score += 7 if price > d["ema20"] else 0
    score += 15 if pullbacks >= 2 else 8
    score += 5 if higher_low else 0
    score += 10 if trigger_ok else 3
    score += 5 if volume_ok else 0
    score += 10 if reward / risk >= 2 else 0
    if strict_leader and battlefield != "强":
        score -= 10

    if score >= 85 and trigger_ok and volume_ok and hourly_ok and pullbacks >= 2:
        grade = "A类"
        status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    elif score >= 70 and entry_low * 0.995 <= price <= entry_high * 1.015:
        grade = "B类观察"
        status = "入场区内" if entry_low <= price <= entry_high else "接近入场"
    else:
        return None

    return Signal(
        market=market,
        symbol=symbol,
        direction="做多",
        grade=grade,
        status=status,
        price=price,
        entry_low=entry_low,
        entry_high=entry_high,
        invalid=invalid,
        target1=target1,
        reason=f"{battlefield}环境；日线不冲突；{pullbacks}段回踩；30M动能{'确认' if trigger_ok else '待确认'}",
        action="观察，不追单" if grade.startswith("B") else "等待触发后按失效位管理",
        score=int(score),
    )


def render_signal(sig: Signal) -> str:
    return (
        f"股票趋势机会｜{sig.market}｜{sig.symbol}｜{sig.direction}｜{sig.grade}\n\n"
        f"现价：{fmt_price(sig.price)}\n"
        f"状态：{sig.status}\n"
        f"入场区：{fmt_price(sig.entry_low)}-{fmt_price(sig.entry_high)}\n"
        f"失效位：{fmt_price(sig.invalid)}\n"
        f"目标1：{fmt_price(sig.target1)}\n"
        f"指数：按模型过滤通过\n"
        f"板块：强势/不冲突\n"
        f"原因：{sig.reason}\n"
        f"处理：{sig.action}"
    )


def feishu_send(config: dict[str, Any], text: str) -> None:
    feishu = config.get("feishu", {})
    if not feishu.get("enabled", True):
        print(text)
        return
    webhook = os.environ.get(feishu.get("webhook_env", "FEISHU_WEBHOOK"), "")
    dry_run = os.environ.get(feishu.get("dry_run_env", "DRY_RUN"), "").lower() in ("1", "true", "yes")
    if dry_run or not webhook:
        print("DRY_RUN or missing FEISHU_WEBHOOK; message:")
        print(text)
        return
    http_post_json(webhook, {"msg_type": "text", "content": {"text": text}})


def should_notify(sig: Signal, state: dict[str, Any]) -> bool:
    old = state.setdefault("signals", {}).get(sig.key)
    snapshot = {
        "grade": sig.grade,
        "status": sig.status,
        "entry_low": round(sig.entry_low, 6),
        "entry_high": round(sig.entry_high, 6),
        "invalid": round(sig.invalid, 6),
        "target1": round(sig.target1, 6),
    }
    if old != snapshot:
        state["signals"][sig.key] = snapshot
        return True
    return False


def scan_crypto(config: dict[str, Any]) -> list[Signal]:
    section = config.get("crypto", {})
    if not section.get("enabled", False):
        return []
    mapping = section.get("symbol_map", {})
    btc = summarize(binance_klines("BTCUSDT", "4h"))
    eth = summarize(binance_klines("ETHUSDT", "4h"))
    battlefield = market_state([btc, eth])
    signals: list[Signal] = []
    for display in section.get("symbols", []):
        actual = mapping.get(display, display)
        try:
            daily = binance_klines(actual, "1d")
            h60 = binance_klines(actual, "1h")
            h30 = binance_klines(actual, "15m")
            sig = evaluate_long("币圈", display, daily, h60, h30, battlefield)
            if sig:
                signals.append(sig)
        except Exception as exc:
            print(f"skip crypto {display}: {exc}", file=sys.stderr)
    return signals


def scan_us(config: dict[str, Any]) -> list[Signal]:
    section = config.get("us_stocks", {})
    if not section.get("enabled", False):
        return []
    index_summaries = []
    for idx in section.get("index_symbols", []):
        try:
            index_summaries.append(summarize(yahoo_chart(idx, "60m", "3mo")))
        except Exception as exc:
            print(f"skip us index {idx}: {exc}", file=sys.stderr)
    battlefield = market_state(index_summaries)
    signals: list[Signal] = []
    for symbol in section.get("symbols", []):
        try:
            daily = yahoo_chart(symbol, "1d", "1y")
            h60 = yahoo_chart(symbol, "60m", "3mo")
            h30 = yahoo_chart(symbol, "30m", "1mo")
            sig = evaluate_long("美股", symbol, daily, h60, h30, battlefield, strict_leader=True)
            if sig:
                signals.append(sig)
        except Exception as exc:
            print(f"skip us {symbol}: {exc}", file=sys.stderr)
    return signals


def scan_cn(config: dict[str, Any]) -> list[Signal]:
    section = config.get("cn_stocks", {})
    if not section.get("enabled", False):
        return []
    index_summaries = []
    for name, secid in section.get("indexes", {}).items():
        try:
            index_summaries.append(summarize(eastmoney_klines(secid, 60)))
        except Exception as exc:
            print(f"skip cn index {name}: {exc}", file=sys.stderr)
    battlefield = market_state(index_summaries)
    signals: list[Signal] = []
    for name, secid in section.get("symbols", {}).items():
        try:
            daily = eastmoney_klines(secid, 101)
            h60 = eastmoney_klines(secid, 60)
            h30 = eastmoney_klines(secid, 30)
            sig = evaluate_long("A股", name, daily, h60, h30, battlefield, strict_leader=True)
            if sig:
                signals.append(sig)
        except Exception as exc:
            print(f"skip cn {name}: {exc}", file=sys.stderr)
    return signals


def main() -> int:
    config = load_config()
    state_path = config["scan"]["state_file"]
    state = load_state(state_path)
    all_signals: list[Signal] = []
    for fn in (scan_crypto, scan_us, scan_cn):
        try:
            all_signals.extend(fn(config))
        except Exception as exc:
            print(f"scan module failed {fn.__name__}: {exc}", file=sys.stderr)

    pushed = 0
    for sig in sorted(all_signals, key=lambda s: (s.grade != "A类", -s.score)):
        if should_notify(sig, state):
            feishu_send(config, render_signal(sig))
            pushed += 1
            time.sleep(0.5)
    save_state(state_path, state)
    print(f"scan done: candidates={len(all_signals)}, pushed={pushed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
