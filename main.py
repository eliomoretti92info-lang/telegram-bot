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
    data = yf.download(ticker, period="5d", interval="1h", progress=False)
    if data is None or data.empty:
        return None

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    return float(close.dropna().iloc[-1])

# =========================
# ANALISI BASE
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

    trend = "rialzista" if price > ma50 else "debole"

    return {
        "ticker": ticker,
        "price": price,
        "rsi": rsi,
        "trend": trend,
        "sl": price * 0.96,
        "tp": price * 1.05
    }

# =========================
# ANALYZE TICKER (NUOVO)
# =========================

def analyze_ticker_command(ticker):
    res = analyze(ticker)

    if not res:
        send(f"❌ Impossibile analizzare {ticker}")
        return

    rsi = res["rsi"]

    if rsi < 40:
        status = "interessante"
    elif rsi > 65:
        status = "attenzione (alto)"
    else:
        status = "neutrale"

    msg = f"""
📊 ANALISI {ticker}

Prezzo: {round(res['price'],2)}

👉 Trend: {res['trend']}
👉 RSI: {round(rsi,1)} ({status})

💡 Cosa fare:
✔ possibile valutazione ingresso
⚠️ evita se incerto

SL: {round(res['sl'],2)}
TP: {round(res['tp'],2)}
"""
    send(msg)

# =========================
# ANALYZE PORTFOLIO (NUOVO)
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
# SPECULATIVO
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
    msg = "🔥 TOP ASSET OGGI:\n\n"
    for t in ASSETS[:3]:
        price = get_price(t)
        msg += f"{t}: {round(price,2)}\n"
    send(msg)

# =========================
# MONITOR
# =========================

def monitor():
    positions = load_positions()

    for t in list(positions.keys()):
        price = get_price(t)
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
    send("🚀 Bot aggiornato con ANALYZE attivo")

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
