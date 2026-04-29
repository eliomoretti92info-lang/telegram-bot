import os
import time
import json
import logging
from pathlib import Path

import requests
import yfinance as yf
import pandas as pd
import ta

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 30
ENTRY_INTERVAL = 300  # 5 min

POSITIONS_FILE = Path("positions.json")

BENCHMARK = "SPY"

ASSETS = [
    "AAPL","MSFT","NVDA","AMZN","META",
    "TSLA","GOOGL","AMD","PLTR",
    "BTC-USD","ETH-USD","SOL-USD"
]

logging.basicConfig(level=logging.INFO)

# ============================================================
# TELEGRAM
# ============================================================

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

# ============================================================
# DATA
# ============================================================

def download(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        return df.dropna()
    except:
        return None

# ============================================================
# ENTRY LOGIC
# ============================================================

def evaluate_entry(ticker):
    df = download(ticker)
    if df is None or len(df) < 60:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    price = float(close.iloc[-1])

    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]

    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    high_20 = float(high.rolling(20).max().iloc[-2])
    low_20 = float(low.rolling(20).min().iloc[-2])

    trend = price > sma20 > sma50

    dist_sma20 = (price - sma20) / sma20 * 100

    # ========================
    # ANTI FOMO
    # ========================
    if rsi > 72 or dist_sma20 > 5:
        return None

    # ========================
    # PULLBACK
    # ========================
    if trend and abs(dist_sma20) < 2.5 and rsi < 60:
        stop = low_20
        risk = (price - stop) / price * 100

        if risk > 5:
            return None

        return {
            "ticker": ticker,
            "type": "PULLBACK",
            "price": price,
            "stop": stop,
            "risk": risk
        }

    # ========================
    # BREAKOUT
    # ========================
    if price > high_20 and dist_sma20 < 4 and rsi < 70:
        stop = sma20
        risk = (price - stop) / price * 100

        if risk > 5:
            return None

        return {
            "ticker": ticker,
            "type": "BREAKOUT",
            "price": price,
            "stop": stop,
            "risk": risk
        }

    return None

# ============================================================
# SCANNER
# ============================================================

def scan_entries():
    signals = []

    for ticker in ASSETS:
        res = evaluate_entry(ticker)
        if res:
            signals.append(res)

    return signals

# ============================================================
# PORTFOLIO
# ============================================================

def load_positions():
    if not POSITIONS_FILE.exists():
        return {}
    return json.loads(POSITIONS_FILE.read_text())

def save_positions(p):
    POSITIONS_FILE.write_text(json.dumps(p, indent=2))

def open_position(signal):
    positions = load_positions()

    ticker = signal["ticker"]

    if ticker in positions:
        return

    positions[ticker] = {
        "entry": signal["price"],
        "stop": signal["stop"]
    }

    save_positions(positions)

    send(f"""🟢 ENTRY {ticker}
Tipo: {signal["type"]}
Prezzo: {signal["price"]:.2f}
Stop: {signal["stop"]:.2f}
""")

def check_positions():
    positions = load_positions()
    changed = False

    for ticker, pos in positions.items():
        df = download(ticker)
        if df is None:
            continue

        price = float(df["Close"].iloc[-1])

        # STOP LOSS
        if price <= pos["stop"]:
            send(f"🔴 STOP HIT {ticker} @ {price:.2f}")
            del positions[ticker]
            changed = True
            break

        # TRAILING STOP
        if price > pos["entry"] * 1.03:
            pos["stop"] = max(pos["stop"], pos["entry"])
            changed = True

    if changed:
        save_positions(positions)

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    send("🚀 BOT TRADING AVVIATO (NO FOMO MODE)")

    last_scan = 0

    while True:
        try:
            now = time.time()

            if now - last_scan > ENTRY_INTERVAL:
                signals = scan_entries()

                if signals:
                    msg = "<b>🎯 SETUP VALIDI</b>\n\n"

                    for s in signals:
                        msg += f"""{s["ticker"]}
Tipo: {s["type"]}
Prezzo: {s["price"]:.2f}
Stop: {s["stop"]:.2f}
Rischio: {s["risk"]:.2f}%

---------
"""
                        open_position(s)

                    send(msg)
                else:
                    send("⛔ Nessun setup valido")

                last_scan = now

            check_positions()

        except Exception as e:
            logging.error(e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()