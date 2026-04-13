import os
import time
import json
import requests
import yfinance as yf
import pandas as pd
import ta

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 600  # 10 minuti

POSITIONS_FILE = "positions.json"

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
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    except Exception as e:
        print("Telegram error:", e)

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 10, "offset": offset}
    return requests.get(url, params=params).json()

# =========================
# MEMORY
# =========================

def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return {}
    with open(POSITIONS_FILE, "r") as f:
        return json.load(f)

def save_positions(data):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

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
# SIGNAL GENERATOR
# =========================

def generate_signal(ticker):
    price = get_price(ticker)

    data = yf.download(ticker, period="6mo", interval="1d", progress=False)
    close = data["Close"].dropna()

    if len(close) < 60:
        return None

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
        reasons.append("momentum")

    if 30 < rsi < 45:
        score += 30
        reasons.append("pullback")

    if score < 50:
        return None

    return {
        "ticker": ticker,
        "price": price,
        "score": score,
        "sl": price * 0.96,
        "tp1": price * 1.05,
        "tp2": price * 1.10,
        "reasons": reasons
    }

# =========================
# TOP 3 DAILY
# =========================

def run_daily():
    candidates = []

    for asset in ASSETS:
        try:
            res = generate_signal(asset)
            if res:
                candidates.append(res)
        except:
            continue

    if not candidates:
        send("⚠️ Nessuna opportunità oggi")
        return

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:3]

    msg = "🔥 TOP 3 OPPORTUNITÀ\n\n"

    for t in top:
        msg += f"""
💰 {t['ticker']}
📌 Prezzo: {round(t['price'],2)}

🛑 SL: {round(t['sl'],2)}
🎯 TP1: {round(t['tp1'],2)}
🎯 TP2: {round(t['tp2'],2)}

👉 Scrivi:
BUY {t['ticker']} oppure SKIP {t['ticker']}

-------------------
"""

    send(msg)

# =========================
# COMMAND HANDLER
# =========================

def handle_commands(offset):
    updates = get_updates(offset)
    positions = load_positions()

    for u in updates.get("result", []):
        offset = u["update_id"] + 1

        try:
            text = u["message"]["text"].upper()
        except:
            continue

        parts = text.split()

        if len(parts) != 2:
            continue

        cmd, ticker = parts

        price = get_price(ticker)

        if cmd == "BUY":
            positions[ticker] = {
                "entry": price,
                "sl": price * 0.96,
                "tp1": price * 1.05,
                "tp2": price * 1.10,
                "tp1_hit": False
            }

            send(f"✅ BUY registrato su {ticker} a {round(price,2)}")

        elif cmd == "SKIP":
            send(f"⏭️ {ticker} ignorato")

    save_positions(positions)
    return offset

# =========================
# MONITOR POSITIONS
# =========================

def monitor():
    positions = load_positions()

    for ticker in list(positions.keys()):
        price = get_price(ticker)
        pos = positions[ticker]

        if price >= pos["tp1"] and not pos["tp1_hit"]:
            send(f"🔔 {ticker} +5% → valuta vendita parziale")
            pos["tp1_hit"] = True

        elif price >= pos["tp2"]:
            send(f"🚀 {ticker} target raggiunto → chiudi posizione")
            del positions[ticker]
            continue

        elif price <= pos["sl"]:
            send(f"⚠️ {ticker} stop loss → esci")
            del positions[ticker]
            continue

        positions[ticker] = pos

    save_positions(positions)

# =========================
# MAIN LOOP
# =========================

def main():
    send("✅ Bot interattivo attivo")

    offset = None
    last_daily = 0

    while True:
        try:
            offset = handle_commands(offset)

            # TOP 3 1 volta al giorno
            if time.time() - last_daily > 86400:
                run_daily()
                last_daily = time.time()

            monitor()

        except Exception as e:
            print("Errore:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
