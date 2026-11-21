"""BTC/USDT paper-trading engine. Public Binance data only; no order execution."""
import json, os, math
from datetime import datetime, timezone
from pathlib import Path
import ccxt
import pandas as pd

STATE_PATH = Path(os.getenv("PAPER_STATE_PATH", "paper_state.json"))
START_BALANCE = 1000.0
RISK_PER_TRADE = 0.01
DAILY_LOSS_LIMIT = 0.03
MAX_TRADES_PER_DAY = 3
MAX_CONSECUTIVE_LOSSES = 3
FEE_RATE = 0.001
SLIPPAGE = 0.0005
SYMBOL = "BTC/USDT"

def utc_now():
    return datetime.now(timezone.utc)

def day_key():
    return utc_now().strftime("%Y-%m-%d")

def default_state():
    return {
        "balance": START_BALANCE, "equity": START_BALANCE, "peak_equity": START_BALANCE,
        "open_position": None, "trades": [], "last_candle_ts": None,
        "daily": {"date": day_key(), "realized_pnl": 0.0, "trades": 0},
        "consecutive_losses": 0, "last_update": None, "note": "Paper only; simulated orders."}

def load_state():
    if not STATE_PATH.exists():
        return default_state()
    try:
        state = json.loads(STATE_PATH.read_text())
        # Basic migration/default safety
        base = default_state()
        base.update(state)
        if not base.get("daily"):
            base["daily"] = {"date": day_key(), "realized_pnl": 0.0, "trades": 0}
        return base
    except Exception:
        return default_state()

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))

def reset_state():
    state = default_state()
    save_state(state)
    return state

def fetch_ohlcv(limit=300):
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    rows = exchange.fetch_ohlcv(SYMBOL, timeframe="15m", limit=limit)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df

def add_indicators(df):
    df = df.copy()
    for n in (20, 50, 200):
        df[f"ema{n}"] = df["close"].ewm(span=n, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))
    fast = df["close"].ewm(span=12, adjust=False).mean()
    slow = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = fast - slow
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
    return df

def score_signal(df):
    """Rule-based scoring, not a trained AI model. Returns direction, score and reasons."""
    if len(df) < 210:
        return {"direction": "WAIT", "score": 0, "reasons": ["Waiting for enough candle history"]}
    d = df.iloc[-2]  # last fully closed candle; avoid trading an unfinished candle
    recent = df.iloc[-22:-2]
    prior = df.iloc[-7:-2]
    score_long = score_short = 0
    reasons_long, reasons_short = [], []
    # Trend (25)
    if d.close > d.ema20 > d.ema50:
        score_long += 25; reasons_long.append("Close above EMA20/EMA50 trend stack")
    if d.close < d.ema20 < d.ema50:
        score_short += 25; reasons_short.append("Close below EMA20/EMA50 trend stack")
    # Liquidity sweep / reclaim (20)
    if d.low < recent.low.min() and d.close > recent.low.min():
        score_long += 20; reasons_long.append("Downside sweep with close back above recent low")
    if d.high > recent.high.max() and d.close < recent.high.max():
        score_short += 20; reasons_short.append("Upside sweep with close back below recent high")
    # Volume (15)
    if pd.notna(d.vol_sma20) and d.volume > 1.25 * d.vol_sma20:
        if d.close > d.open:
            score_long += 15; reasons_long.append("Elevated volume on bullish candle")
        elif d.close < d.open:
            score_short += 15; reasons_short.append("Elevated volume on bearish candle")
    # RSI (15)
    if 42 <= d.rsi <= 62 and d.rsi >= prior.iloc[-1].rsi:
        score_long += 15; reasons_long.append("RSI recovery/neutral bullish zone")
    if 38 <= d.rsi <= 58 and d.rsi <= prior.iloc[-1].rsi:
        score_short += 15; reasons_short.append("RSI weakening in bearish zone")
    # Support/resistance context (15)
    if d.close > recent.close.mean() and d.close > recent.high.quantile(0.65):
        score_long += 15; reasons_long.append("Close near recent range upper region")
    if d.close < recent.close.mean() and d.close < recent.low.quantile(0.35):
        score_short += 15; reasons_short.append("Close near recent range lower region")
    # Momentum proxy (10; OI/funding not included in public-data build)
    if d.macd > d.macd_signal:
        score_long += 10; reasons_long.append("MACD momentum positive")
    if d.macd < d.macd_signal:
        score_short += 10; reasons_short.append("MACD momentum negative")
    if score_long >= 75 and score_long > score_short:
        return {"direction": "LONG", "score": score_long, "reasons": reasons_long}
    if score_short >= 75 and score_short > score_long:
        return {"direction": "SHORT", "score": score_short, "reasons": reasons_short}
    return {"direction": "WAIT", "score": max(score_long, score_short), "reasons": ["Setup score below 75", f"Long score {score_long}/100", f"Short score {score_short}/100"]}

def reset_daily_if_needed(state):
    if state["daily"].get("date") != day_key():
        state["daily"] = {"date": day_key(), "realized_pnl": 0.0, "trades": 0}
        state["consecutive_losses"] = 0  # daily lockout resets at UTC day rollover

def blocked(state):
    reset_daily_if_needed(state)
    return (state["daily"]["realized_pnl"] <= -START_BALANCE * DAILY_LOSS_LIMIT or
            state["daily"]["trades"] >= MAX_TRADES_PER_DAY or
            state["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES)

def open_paper_trade(state, direction, price, score, reasons, candle_ts, atr):
    if blocked(state) or state.get("open_position") or direction not in ("LONG", "SHORT"):
        return False
    stop_distance = max(float(atr or 0), price * 0.006)  # minimum 0.6% stop distance
    stop_distance = min(stop_distance, price * 0.025)    # cap at 2.5%
    risk_cash = state["balance"] * RISK_PER_TRADE
    qty = min(risk_cash / stop_distance, state["balance"] / price)  # no simulated leverage; cap notional to balance
    # Simulated market-entry slippage and fee
    entry = price * (1 + SLIPPAGE if direction == "LONG" else 1 - SLIPPAGE)
    stop = entry - stop_distance if direction == "LONG" else entry + stop_distance
    target = entry + stop_distance * 2 if direction == "LONG" else entry - stop_distance * 2
    state["open_position"] = {
        "direction": direction, "entry": entry, "qty": qty, "stop": stop, "target": target,
        "risk_cash": risk_cash, "score": score, "reasons": reasons,
        "opened_at": str(candle_ts), "entry_fee": entry * qty * FEE_RATE,
        "stop_distance": stop_distance, "initial_balance": state["balance"]
    }
    return True

def close_position(state, exit_price, reason, timestamp):
    p = state.get("open_position")
    if not p:
        return None
    direction = p["direction"]
    fill = exit_price * (1 - SLIPPAGE if direction == "LONG" else 1 + SLIPPAGE)
    gross = (fill - p["entry"]) * p["qty"] if direction == "LONG" else (p["entry"] - fill) * p["qty"]
    exit_fee = fill * p["qty"] * FEE_RATE
    net = gross - p["entry_fee"] - exit_fee
    state["balance"] += net
    state["daily"]["realized_pnl"] += net
    state["daily"]["trades"] += 1
    if net < 0: state["consecutive_losses"] += 1
    else: state["consecutive_losses"] = 0
    trade = {"direction": direction, "entry": p["entry"], "exit": fill, "qty": p["qty"],
             "pnl": net, "score": p["score"], "opened_at": p["opened_at"],
             "closed_at": str(timestamp), "exit_reason": reason, "reasons": p["reasons"]}
    state["trades"].append(trade)
    state["open_position"] = None
    return trade

def process_position(state, candle):
    p = state.get("open_position")
    if not p: return None
    # If stop and target are both hit in the same candle, conservatively assume stop first.
    if p["direction"] == "LONG":
        stop_hit = candle.low <= p["stop"]
        target_hit = candle.high >= p["target"]
        if stop_hit: return close_position(state, p["stop"], "Stop-loss", candle.timestamp)
        if target_hit: return close_position(state, p["target"], "Take-profit (2R)", candle.timestamp)
    else:
        stop_hit = candle.high >= p["stop"]
        target_hit = candle.low <= p["target"]
        if stop_hit: return close_position(state, p["stop"], "Stop-loss", candle.timestamp)
        if target_hit: return close_position(state, p["target"], "Take-profit (2R)", candle.timestamp)
    return None

def update_engine(state, df):
    df = add_indicators(df)
    latest = df.iloc[-1]
    state["last_update"] = str(utc_now())
    state["equity"] = state["balance"]
    state["peak_equity"] = max(state.get("peak_equity", START_BALANCE), state["equity"])
    # Update open trade using latest candle high/low, including stop/target.
    closed = process_position(state, latest)
    closed_candle_ts = str(df.iloc[-2].timestamp)
    if state.get("last_candle_ts") != closed_candle_ts:
        state["last_candle_ts"] = closed_candle_ts
        signal = score_signal(df)
        if not state.get("open_position") and not blocked(state) and signal["direction"] in ("LONG", "SHORT"):
            opened = open_paper_trade(state, signal["direction"], float(df.iloc[-2].close), signal["score"], signal["reasons"], df.iloc[-2].timestamp, float(df.iloc[-2].atr))
            if opened: state["last_signal"] = signal
        else:
            state["last_signal"] = signal
    save_state(state)
    return df, state

def unrealized_pnl(state, current_price):
    p = state.get("open_position")
    if not p: return 0.0
    if p["direction"] == "LONG": gross = (current_price - p["entry"]) * p["qty"]
    else: gross = (p["entry"] - current_price) * p["qty"]
    return gross - p["entry_fee"] - current_price * p["qty"] * FEE_RATE
