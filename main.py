import os
import time
import json
import requests
import yfinance as yf
import pandas as pd
import ta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 30
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
    try:
        data = yf.download(ticker, period="5d", interval="1h", progress=False)
        if data is None or data.empty:
            return None

        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        return float(close.dropna().iloc[-1])
    except:
        return None

# =========================
# ANALISI BASE
# =========================

def analyze(ticker):
    try:
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
        ma50 = close.rolling(50).mean().iloc[-1]

        trend = "rialzista" if price > ma50 else "debole"

        if rsi < 40 and trend == "rialzista":
            advice = "entra ora"
        elif rsi > 65 or trend == "debole":
            advice = "situazione rischiosa"
        else:
            advice = "meglio aspettare"

        return {
            "ticker": ticker,
            "price": price,
            "rsi": rsi,
            "trend": trend,
            "sl": price * 0.96,
            "tp": price * 1.05,
            "advice": advice
        }
    except:
        return None

# =========================
# ANALYZE TICKER
# =========================

def analyze_ticker_command(ticker):
    res = analyze(ticker)

    if not res:
        send(f"❌ Impossibile analizzare {ticker}")
        return

    msg = f"""
📊 ANALISI {ticker}

Prezzo: {round(res['price'],2)}

👉 Trend: {res['trend']}
👉 RSI: {round(res['rsi'],1)}

👉 Consiglio: {res['advice']}

SL: {round(res['sl'],2)}
TP: {round(res['tp'],2)}
"""
    send(msg)

# =========================
# ANALYZE PORTFOLIO
# =========================

def analyze_portfolio():
    positions = load_positions()

    if not positions:
        send("📭 Nessuna posizione aperta")
        return

    msg = "💼 ANALISI PORTAFOGLIO\n\n"
    total = 0
    count = 0

    for t in positions:
        price = get_price(t)

        if price is None:
            msg += f"{t}: ❌ dati non disponibili\n"
            continue

        entry = positions[t]["entry"]
        pnl = (price - entry) / entry * 100

        total += pnl
        count += 1

        if pnl > 2:
            comment = "mantieni 👍"
        elif pnl < -2:
            comment = "attenzione ⚠️"
        else:
            comment = "neutrale"

        msg += f"{t}: {round(pnl,2)}% → {comment}\n"

    avg = total / count if count else 0
    msg += f"\n📊 Media portafoglio: {round(avg,2)}%"

    send(msg)

# =========================
# TOP + GUIDA
# =========================

def run_top():
    candidates = []

    for t in ASSETS:
        res = analyze(t)
        if res:
            candidates.append(res)

    if not candidates:
        send("⚠️ Nessuna opportunità oggi")
        return

    candidates.sort(key=lambda x: x["rsi"])
    top = candidates[:3]

    msg = "🔥 MIGLIORI ORA:\n\n"

    for t in top:
        msg += f"""
{t['ticker']}
Prezzo: {round(t['price'],2)}
SL: {round(t['sl'],2)}
TP: {round(t['tp'],2)}

👉 Consiglio: {t['advice']}

Scrivi:
BUY {t['ticker']}
BUY {t['ticker']} prezzo

---------
"""

    msg += """
📘 COMANDI:

BUY TICKER
BUY TICKER prezzo

ANALYZE TICKER
ANALYZE PORTFOLIO

STATUS
TOP
"""

    send(msg)

# =========================
# SPECULATIVO FILTRATO
# =========================

def scan_speculative():
    alerts = []

    for t in ASSETS:
        try:
            data = yf.download(t, period="2d", interval="15m", progress=False)

            if data is None or data.empty:
                continue

            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

            close = close.dropna()

            if len(close) < 30:
                continue

            change_now = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
            change_prev = (close.iloc[-5] - close.iloc[-10]) / close.iloc[-10] * 100

            ma20 = close.rolling(20).mean().iloc[-1]
            rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]
            price = close.iloc[-1]

            if change_now > 3 and change_prev > 1 and price > ma20 and rsi < 65:
                alerts.append(f"{t} 📈 movimento confermato → entra ora 🔥")

            elif change_now < -3 and rsi < 35:
                alerts.append(f"{t} ⚡ possibile rimbalzo → rischio alto")

            elif change_now < -2 and price < ma20 and rsi > 50:
                alerts.append(f"{t} 🚨 perdita forza → situazione rischiosa")

        except:
            continue

    if alerts:
        msg = "⚡ SPECULATIVO LIVE\n\n"
        for a in alerts[:5]:
            msg += a + "\n"
        send(msg)

# =========================
# MONITOR
# =========================

def monitor():
    positions = load_positions()

    for t in list(positions.keys()):
        price = get_price(t)

        if price is None:
            continue

        entry = positions[t]["entry"]
        pnl = (price - entry) / entry * 100

        if pnl >= 5 and not positions[t].get("tp1_hit"):
            send(f"💰 {t} +5% → valuta vendita")
            positions[t]["tp1_hit"] = True

        if pnl <= -4:
            send(f"⚠️ {t} stop loss")
            del positions[t]

    save_positions(positions)

# =========================
# COMMANDS
# =========================

def handle_commands(offset):
    data = get_updates(offset)
    positions = load_positions()

    for u in data.get("result", []):
        offset = u["update_id"] + 1
        text = u.get("message", {}).get("text", "").upper().strip()

        print("📩", text)
        parts = text.split()

        if text == "TOP":
            run_top()

        elif text == "STATUS":
            analyze_portfolio()

        elif text == "ANALYZE PORTFOLIO":
            analyze_portfolio()

        elif len(parts) == 2 and parts[0] == "ANALYZE":
            analyze_ticker_command(parts[1])

        elif parts[0] == "BUY":
            ticker = parts[1]
            price = get_price(ticker)

            if price is None:
                send("❌ Prezzo non disponibile")
                continue

            entry = float(parts[2]) if len(parts) == 3 else price

            positions[ticker] = {
                "entry": entry,
                "tp1_hit": False
            }

            send(f"✅ {ticker} registrato a {round(entry,2)}")

    save_positions(positions)
    return offset

# =========================
# MAIN
# =========================

def main():
    send("🚀 Bot SPECULATIVO ATTIVO")

    offset = None
    last_top = 0
    last_spec = 0

    while True:
        try:
            offset = handle_commands(offset)

            if time.time() - last_top > 3600:
                run_top()
                last_top = time.time()

            if time.time() - last_spec > 300:
                scan_speculative()
                last_spec = time.time()

            monitor()

        except Exception as e:
            print("Errore:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()