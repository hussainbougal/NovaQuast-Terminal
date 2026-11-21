import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from engine import fetch_ohlcv, update_engine, load_state, reset_state, unrealized_pnl, START_BALANCE, blocked


st.set_page_config(page_title="BTC AI Paper Trader", page_icon="📊", layout="wide")
st.title("📊 BTC AI Paper Trader — V1")
st.caption("Paper trading only • Public Binance market data • No real orders or API keys")
refresh_seconds = st.sidebar.selectbox("Refresh interval", [30, 60, 120], index=1)
st_autorefresh(interval=refresh_seconds * 1000, key="paper_refresh")
if st.sidebar.button("Reset paper account", type="secondary"):
    reset_state()
    st.rerun()

try:
    df = fetch_ohlcv()
    df, state = update_engine(load_state(), df)
    price = float(df.iloc[-1].close)
    sig = state.get("last_signal", {"direction":"WAIT", "score":0, "reasons":["No signal yet"]})
except Exception as e:
    st.error(f"Market data refresh failed: {e}")
    st.info("Try again later. The dashboard needs access to Binance public market data.")
    st.stop()

open_p = state.get("open_position")
unrealized = unrealized_pnl(state, price)
net_equity = state["balance"] + unrealized
trades = pd.DataFrame(state.get("trades", []))

cols = st.columns(4)
cols[0].metric("BTC/USDT", f"${price:,.2f}")
cols[1].metric("Paper balance", f"${state['balance']:,.2f}", f"{state['balance']-START_BALANCE:+.2f} vs start")
cols[2].metric("Equity incl. unrealized", f"${net_equity:,.2f}", f"{unrealized:+.2f} unrealized")
cols[3].metric("Signal", f"{sig.get('direction','WAIT')} · {sig.get('score',0)}/100")

st.subheader("Strategy snapshot")
cols = st.columns(3)
cols[0].metric("EMA 20", f"${df.iloc[-1].ema20:,.2f}")
cols[1].metric("EMA 50", f"${df.iloc[-1].ema50:,.2f}")
cols[2].metric("RSI (14)", f"{df.iloc[-1].rsi:.1f}")

with st.expander("Signal reasons", expanded=True):
    for r in sig.get("reasons", []): st.write("•", r)
    st.caption("Signals are rule-based heuristics, not a trained AI model. Open Interest, funding, and liquidation heatmap data are not included in V1.")

st.subheader("Open paper position")
if open_p:
    st.success(f"{open_p['direction']} position is open")
    pcols = st.columns(5)
    pcols[0].metric("Entry", f"${open_p['entry']:,.2f}")
    pcols[1].metric("Stop-loss", f"${open_p['stop']:,.2f}")
    pcols[2].metric("Take-profit (2R)", f"${open_p['target']:,.2f}")
    pcols[3].metric("Quantity", f"{open_p['qty']:.6f} BTC")
    pcols[4].metric("Unrealized P&L", f"${unrealized:+,.2f}")
    st.write("Entry rationale:")
    for r in open_p.get("reasons", []): st.write("•", r)
else:
    st.info("No open position. The strategy waits for a score of 75/100 or higher and valid risk limits.")

st.subheader("Risk controls")
daily = state.get("daily", {})
loss_cap = START_BALANCE * 0.03
riskcols = st.columns(4)
riskcols[0].metric("Trades today", f"{daily.get('trades',0)}/3")
riskcols[1].metric("Today's realized P&L", f"${daily.get('realized_pnl',0):+.2f}")
riskcols[2].metric("Consecutive losses", f"{state.get('consecutive_losses',0)}/3")
riskcols[3].metric("Daily loss cap", f"-${loss_cap:.2f}")
if blocked(state): st.warning("Risk lock active: new entries are disabled until the lock condition clears (daily reset or consecutive-loss reset after a winning trade).")

st.subheader("Recent closed trades")
if trades.empty:
    st.write("No completed trades yet. The system will wait for qualifying signals and exits.")
else:
    show = trades.iloc[::-1].head(30).copy()
    show["pnl"] = show["pnl"].map(lambda x: round(float(x), 2))
    st.dataframe(show[[c for c in ["direction", "entry", "exit", "pnl", "score", "exit_reason", "opened_at", "closed_at"] if c in show.columns]], use_container_width=True, hide_index=True)
    wins = (trades["pnl"] > 0).sum()
    st.write(f"Win rate: **{wins/len(trades)*100:.1f}%** · Closed trades: **{len(trades)}** · Total net P&L: **${trades['pnl'].sum():+.2f}**")
    gross_wins = trades.loc[trades.pnl > 0, "pnl"].sum()
    gross_losses = abs(trades.loc[trades.pnl < 0, "pnl"].sum())
    pf = gross_wins / gross_losses if gross_losses else float("inf")
    st.write(f"Profit factor: **{pf:.2f}**")

st.subheader("BTC price (15-minute candles)")
chart = df.tail(100).set_index("timestamp")[["close", "ema20", "ema50"]]
st.line_chart(chart, height=350)
st.caption(f"Last update: {state.get('last_update','—')} UTC • Simulation assumptions: 0.10% fee per side, 0.05% slippage each side. Stops are simulated from candle highs/lows; if stop and target are both hit in one candle, stop is assumed first.")
