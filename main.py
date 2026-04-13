import os
import time
from datetime import datetime

import requests
import yfinance as yf
import ta
import pandas as pd

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL_SECONDS = 86400

CAPITAL = 10000
RISK_PER_TRADE = 0.02  # 2%

ASSETS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "TSLA",
    "BTC-USD", "ETH-USD", "SOL-USD"
]

# =========================
# TELEGRAM
# =========================

def send(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Token mancanti")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    except Exception as e:
        print("Telegram error:", e)

# =========================
# DATA
# =========================

def get_data(ticker):
    data = yf.download(ticker, period="6mo", interval="1d", progress=False)

    if data is None or data.empty:
        return None

    close = data["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.dropna()

    if len(close) < 60:
        return None

    return close

# =========================
# ANALISI + RISK MANAGEMENT
# =========================

def analyze(ticker, close):
    price = float(close.iloc[-1])

    rsi = float(ta.momentum.RSIIndicator(close).rsi().iloc[-1])

    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])

    score = 0
    reasons = []

    if price > ma50:
        score += 30
        reasons.append("trend")

    if ma20 > ma50:
        score += 20
        reasons.append("momentum")

    if 30 < rsi < 45:
        score += 30
        reasons.append("pullback")

    if score < 60:
        return None

    # ENTRY / EXIT
    entry = price
    stop_loss = ma50 * 0.98
    tp1 = entry * 1.06
    tp2 = entry * 1.12

    risk_per_unit = entry - stop_loss

    if risk_per_unit <= 0:
        return None

    # 💰 POSITION SIZE
    capital_risk = CAPITAL * RISK_PER_TRADE
    size = capital_risk / risk_per_unit

    investment = size * entry

    probability = min(85, score + 15)

    return {
        "ticker": ticker,
        "entry": round(entry, 2),
        "sl": round(stop_loss, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "size": int(size),
        "investment": round(investment, 2),
        "risk": round(capital_risk, 2),
        "prob": round(probability, 1),
        "reasons": reasons
    }

# =========================
# SCAN
# =========================

def run_once():
    print(f"\n=== SCAN {datetime.now()} ===")

    setups = []

    for asset in ASSETS:
        try:
            close = get_data(asset)
            if close is None:
                continue

            result = analyze(asset, close)

            if result:
                setups.append(result)

        except Exception as e:
            print("Errore:", e)

    if not setups:
        send("⚠️ Nessun trade valido oggi")
        return

    setups.sort(key=lambda x: x["prob"], reverse=True)

    top = setups[:3]

    msg = "💰 TRADE PLAN (10.000€)\n\n"

    for i, t in enumerate(top, 1):
        msg += (
            f"{i}) {t['ticker']}\n"
            f"Entry: {t['entry']}\n"
            f"SL: {t['sl']}\n"
            f"TP1: {t['tp1']} | TP2: {t['tp2']}\n"
            f"Size: {t['size']} unità\n"
            f"Investimento: {t['investment']}€\n"
            f"Rischio: {t['risk']}€\n"
            f"Prob: {t['prob']}%\n\n"
        )

    send(msg)

# =========================
# MAIN
# =========================

def main():
    send("✅ Bot attivo - gestione capitale")

    while True:
        run_once()
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
