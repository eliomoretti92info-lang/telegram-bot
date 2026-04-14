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

CHECK_INTERVAL = 30  # velocissimo
POSITIONS_FILE = "positions.json"

ASSETS = [
    "AAPL","MSFT","NVDA","AMZN","META",
    "TSLA","GOOGL","AMD","PLTR",
    "BTC-USD","ETH-USD","SOL-USD",
    "SPY","QQQ"
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
    try:
        return requests.get(url, params={"offset": offset, "timeout": 10}).json()
    except:
        return {}

# =========================
# STORAGE
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
    data = yf.download(ticker, period="5d", interval="1h", progress=False)

    if data is None or data.empty:
        return None

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    return float(close.dropna().iloc[-1])

# =========================
# ANALISI
# =========================

def analyze(ticker):
    data = yf.download(ticker, period="3mo", interval="1d", progress=False)
    if data is None or data.empty:
        return None

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.dropna()
    if len(close) < 50:
        return None

    price = float(close.iloc[-1])

    rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]

    score = 0

    if price > ma50:
        score += 30
    if ma20 > ma50:
        score += 20
    if 30 < rsi < 45:
        score += 30

    if score < 40:
        return None

    return {
        "ticker": ticker,
        "price": price,
        "score": score,
        "sl": price * 0.96,
        "tp1": price * 1.05
    }

# =========================
# SPECULATIVO (MOVIMENTI FORTI)
# =========================

def scan_speculative():
    alerts = []

    for t in ASSETS:
        try:
            data = yf.download(t, period="2d", interval="1h", progress=False)
            close = data["Close"].dropna()

            change = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100

            if abs(change) > 3:
                alerts.append((t, round(change,2)))
        except:
            continue

    if alerts:
        msg = "⚡ MOVIMENTI FORTI:\n\n"
        for t, c in alerts:
            direction = "📈" if c > 0 else "📉"
            msg += f"{t} {direction} {c}%\n"
        send(msg)

# =========================
# TOP
# =========================

def run_top():
    candidates = []

    for t in ASSETS:
        try:
            res = analyze(t)
            if res:
                candidates.append(res)
        except:
            continue

    if not candidates:
        send("⚠️ Mercato debole")
        return

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:3]

    msg = "🔥 MIGLIORI ORA:\n\n"

    for t in top:
        msg += f"""
{t['ticker']}
Prezzo: {round(t['price'],2)}
SL: {round(t['sl'],2)}
TP: {round(t['tp1'],2)}

Scrivi:
BUY {t['ticker']}
BUY {t['ticker']} prezzo

---------
"""

    send(msg)

# =========================
# MONITOR
# =========================

def monitor():
    positions = load_positions()

    for t in list(positions.keys()):
        price = get_price(t)
        pos = positions[t]

        pnl = (price - pos["entry"]) / pos["entry"] * 100

        if pnl >= 5 and not pos.get("tp1_hit"):
            send(f"💰 {t} +5% → valuta vendita")
            pos["tp1_hit"] = True

        if pnl <= -4:
            send(f"⚠️ {t} -4% → stop loss")
            del positions[t]
            continue

        positions[t] = pos

    save_positions(positions)

# =========================
# COMMANDS
# =========================

def handle_commands(offset):
    data = get_updates(offset)
    positions = load_positions()

    for u in data.get("result", []):
        offset = u["update_id"] + 1

        msg = u.get("message", {})
        text = msg.get("text", "").upper().strip()

        print("📩", text)

        parts = text.split()

        if text == "TOP":
            run_top()

        elif text == "STATUS":
            if not positions:
                send("📭 Nessuna posizione")
            else:
                msg = "💼 PORTAFOGLIO:\n\n"
                for t in positions:
                    price = get_price(t)
                    entry = positions[t]["entry"]
                    pnl = (price - entry) / entry * 100
                    msg += f"{t}: {round(pnl,2)}%\n"
                send(msg)

        elif text == "AIUTO":
            send("BUY TICKER o BUY TICKER PREZZO\nTOP\nSTATUS")

        elif len(parts) >= 2:

            cmd = parts[0]
            ticker = parts[1]

            price = get_price(ticker)

            if not price:
                send("❌ Ticker non valido")
                continue

            # BUY manuale prezzo
            if cmd == "BUY":

                if len(parts) == 3:
                    try:
                        entry_price = float(parts[2])
                    except:
                        entry_price = price
                else:
                    entry_price = price

                positions[ticker] = {
                    "entry": entry_price,
                    "tp1_hit": False
                }

                send(f"✅ {ticker} registrato a {round(entry_price,2)}")

        save_positions(positions)

    return offset

# =========================
# MAIN
# =========================

def main():
    send("🚀 Bot PRO attivo")

    offset = None
    last_top = 0
    last_spec = 0

    while True:
        try:
            offset = handle_commands(offset)

            if time.time() - last_top > 3600:
                run_top()
                last_top = time.time()

            if time.time() - last_spec > 900:
                scan_speculative()
                last_spec = time.time()

            monitor()

        except Exception as e:
            print("Errore:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
