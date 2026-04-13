import os
import time
import requests
import yfinance as yf
import pandas as pd
import ta

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 86400  # 1 volta al giorno

ASSETS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "AMD",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "SPY", "QQQ"
]

# =========================
# TELEGRAM
# =========================

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram error:", e)

# =========================
# PRICE
# =========================

def get_price(ticker):
    data = yf.download(ticker, period="6mo", interval="1d", progress=False)

    if data is None or data.empty:
        return None

    close = data["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    return float(close.dropna().iloc[-1])

# =========================
# ANALYSIS
# =========================

def analyze(ticker):
    data = yf.download(ticker, period="6mo", interval="1d", progress=False)

    if data is None or data.empty:
        return None

    close = data["Close"].dropna()

    if len(close) < 60:
        return None

    price = float(close.iloc[-1])

    rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]

    score = 0
    reasons = []

    if price > ma50:
        score += 30
        reasons.append("trend positivo")

    if ma20 > ma50:
        score += 20
        reasons.append("momentum positivo")

    if 30 < rsi < 45:
        score += 30
        reasons.append("pullback sano")

    if rsi > 70:
        score -= 20
        reasons.append("ipercomprato")

    if score < 50:
        return None

    sl = price * 0.96
    tp1 = price * 1.05
    tp2 = price * 1.10

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "score": round(score, 2),
        "rsi": round(rsi, 2),
        "sl": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "reasons": reasons
    }

# =========================
# TOP 3 SCANNER
# =========================

def run():
    candidates = []

    for asset in ASSETS:
        try:
            result = analyze(asset)
            if result:
                candidates.append(result)
        except Exception as e:
            print(f"Errore {asset}: {e}")

    if not candidates:
        send("⚠️ Nessuna opportunità interessante oggi")
        return

    candidates.sort(key=lambda x: x["score"], reverse=True)

    top = candidates[:3]

    msg = "🔥 TOP 3 OPPORTUNITÀ DEL GIORNO\n\n"

    for i, t in enumerate(top, 1):
        msg += f"""
{i}) {t['ticker']}
📌 Prezzo: {t['price']}

🛑 Stop Loss: {round(t['sl'],2)}
🎯 TP1: {round(t['tp1'],2)}
🎯 TP2: {round(t['tp2'],2)}

📊 Score: {t['score']}
💡 Motivi: {', '.join(t['reasons'])}

-----------------------
"""

    send(msg)

# =========================
# MAIN
# =========================

def main():
    send("✅ Bot attivo - TOP 3 intelligente")

    while True:
        try:
            run()
        except Exception as e:
            print("Errore generale:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
