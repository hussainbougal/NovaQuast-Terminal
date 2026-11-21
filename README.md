# BTC AI Paper Trader V1

A local Streamlit dashboard that simulates BTC/USDT spot trades using public Binance OHLCV data. **It does not place real orders and needs no Binance API keys.**

## Setup (Windows, macOS, Linux)
1. Install Python 3.10+.
2. Extract this folder.
3. Open a terminal in the folder and run:
   ```bash
   python -m venv .venv
   ```
4. Activate the environment:
   - Windows: `.venv\Scripts\activate`
   - macOS/Linux: `source .venv/bin/activate`
5. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
6. Launch:
   ```bash
   streamlit run app.py
   ```
7. Open the local dashboard URL shown in the terminal (usually `http://localhost:8501`).

## Defaults
- Virtual starting balance: $1,000
- Pair: BTC/USDT spot candles
- Signal timeframe: 15-minute candles; uses the last completed candle for new signals
- Maximum 3 closed trades/day
- Risk budget per trade: 1% of paper balance
- Daily realized-loss lock: 3% of starting balance
- Lock after 3 consecutive losses
- Entry threshold: score >= 75/100
- Stop distance: ATR-based, minimum 0.6% and maximum 2.5%
- Target: 2R
- Simulated fees: 0.10% per side; slippage: 0.05% per side
- If stop and target both appear hit in the same candle, stop-loss is assumed first (conservative)

## Strategy scoring
Rule-based heuristic (not a trained machine-learning model): trend stack, liquidity sweep/reclaim, volume, RSI, recent range context, and MACD momentum. It does not currently use open interest, funding rate, or an external liquidation heatmap.

## Important limitations
- Paper trading only; simulation may differ from real execution and fills.
- Binance public market data availability/rate limits may interrupt refreshes.
- The dashboard is local and only runs while your computer and process are on.
- Trade state is saved to `paper_state.json` in the current working directory. Keep backups if you want to preserve the log.
- This is an experimental strategy, not financial advice or a guarantee of profitability.
- Do not add real exchange credentials. No order-execution code is present.
