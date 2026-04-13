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

# ⏰ 1 volta al giorno (test: metti 60)
CHECK_INTERVAL_SECONDS = 86400

ASSETS = [
    # 📊 AZIONI BIG
    "AAPL", "TSLA", "NVDA",

    # 📈 ETF
    "SPY", "QQQ",

    # 🪙 CRYPTO
    "BTC-USD", "ETH-USD", "SOL-USD",

    # 🛢️ MATERIE PRIME
    "GC=F",   # oro
    "CL=F",   # petrolio

    # 🚀 SPECULATIVE
    "PLTR", "COIN", "RIOT"
]

# =========================
# TELEGRAM
# =========================

def send(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Token o Chat ID mancanti")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=20
        )
        print("Telegram:", response.status_code)
    except Exception as e:
        print("Errore Telegram:", e)

# =========================
# ANALISI
# =========================

def analyze(ticker: str):
    data = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        progress=False,
        auto_adjust=True
    )

    if data is None or data.empty:
        return None

    close = data["Close"]

    # 🔥 FIX CRITICO (yfinance bug)
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.dropna()

    if len(close) < 60:
        return None

    rsi_series = ta.momentum.RSIIndicator(close).rsi()
    rsi = float(rsi_series.iloc[-1])

    ma50 = float(close.rolling(50).mean().iloc[-1])
    price = float(close.iloc[-1])

    score = 0

    # 📊 scoring migliorato
    if rsi < 35:
        score += (50 - rsi) * 1.5

    if price > ma50:
        score += 30

    # 🎯 decisione
    if score >= 60:
        signal = "BUY"
    else:
        signal = "HOLD"

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "rsi": round(rsi, 2),
        "score": round(score, 2),
        "signal": signal
    }

# =========================
# SCAN GIORNALIERO
# =========================

def run_once():
    print(f"\n=== SCAN {datetime.now()} ===")

    results = []

    for asset in ASSETS:
        try:
            result = analyze(asset)

            if result:
                print(asset, result)

                if result["signal"] == "BUY":
                    results.append(result)

        except Exception as e:
            print(f"Errore su {asset}: {e}")

    if not results:
        send("⚠️ Nessuna opportunità forte oggi")
        return

    # 🔥 ordina per punteggio
    results.sort(key=lambda x: x["score"], reverse=True)

    top = results[:3]

    # 📲 messaggio finale
    message = "🔥 TOP 3 OPPORTUNITÀ OGGI\n\n"

    for i, r in enumerate(top, 1):
        message += (
            f"{i}) {r['ticker']} → BUY\n"
            f"Prezzo: {r['price']}\n"
            f"RSI: {r['rsi']}\n"
            f"Score: {r['score']}\n\n"
        )

    message += "⚠️ Solo segnali ad alta probabilità"

    send(message)

# =========================
# MAIN
# =========================

def main():
    print("🔥 BOT AVVIATO")

    send("✅ Bot attivo - modalità TOP 3 giornaliero")

    while True:
        try:
            run_once()
        except Exception as e:
            print("Errore ciclo:", e)

        print(f"Attendo {CHECK_INTERVAL_SECONDS} secondi...")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
