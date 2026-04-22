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

def send(msg, keyboard=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    if keyboard:
        data["reply_markup"] = json.dumps({
            "keyboard": [
                ["📊 TOP", "📘 MENU"],
                ["📈 ANALYZE", "💼 PORTFOLIO"],
                ["💰 BUY", "❌ SELL"]
            ],
            "resize_keyboard": True
        })

    try:
        requests.post(url, data=data, timeout=20)
    except Exception as e:
        print("Telegram error:", e)

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        return requests.get(url, params={"offset": offset, "timeout": 10}).json()
    except:
        return {}

# =========================
# MENU
# =========================

def show_menu():
    msg = """
📘 COMANDI DISPONIBILI

🟢 OPERATIVI:
BUY TICKER
BUY TICKER prezzo
SELL TICKER

📊 ANALISI:
ANALYZE TICKER
ANALYZE PORTFOLIO

📈 MERCATO:
TOP → migliori opportunità

⚡ SPECULATIVO:
(alert automatici)

📋 ALTRO:
MENU → mostra comandi
"""
    send(msg, keyboard=True)

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
# TIMING + FORZA
# =========================

def get_timing_and_strength(price, ma20, rsi, change):

    if price > ma20 and 40 < rsi < 55 and change > 1:
        return "momento perfetto 🟢", "ENTRA FORTE 💪"

    elif price > ma20 and rsi < 65:
        return "buon momento 🟡", "ENTRA MEDIO ⚖️"

    elif rsi < 40 or change > 3:
        return "speculativo ⚪", "ENTRA LEGGERO 🪶"

    elif rsi > 70 or change > 5:
        return "è già tardi 🔴", "NON ENTRARE ❌"

    else:
        return "incerto", "ATTENDI"

# =========================
# ANALISI
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

        return {
            "ticker": ticker,
            "price": price,
            "rsi": rsi,
            "trend": trend,
            "sl": price * 0.96,
            "tp": price * 1.05
        }
    except:
        return None

def analyze_ticker_command(ticker):
    res = analyze(ticker)

    if not res:
        send(f"❌ Impossibile analizzare {ticker}")
        return

    timing, strength = get_timing_and_strength(
        res['price'], res['price'], res['rsi'], 0
    )

    msg = f"""
📊 ANALISI {ticker}

Prezzo: {round(res['price'],2)}

👉 Trend: {res['trend']}
👉 RSI: {round(res['rsi'],1)}

👉 Timing: {timing}
👉 Azione: {strength}

SL: {round(res['sl'],2)}
TP: {round(res['tp'],2)}
"""
    send(msg)

# =========================
# PORTFOLIO
# =========================

def analyze_portfolio():
    positions = load_positions()

    if not positions:
        send("📭 Nessuna posizione aperta")
        return

    msg = "💼 PORTAFOGLIO\n\n"

    for t in positions:
        price = get_price(t)

        if price is None:
            continue

        entry = positions[t]["entry"]
        pnl = (price - entry) / entry * 100

        msg += f"{t}: {round(pnl,2)}%\n"

    send(msg)

# =========================
# TOP
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
        timing, strength = get_timing_and_strength(
            t['price'], t['price'], t['rsi'], 0
        )

        msg += f"""
{t['ticker']}
Prezzo: {round(t['price'],2)}

👉 {timing}
👉 {strength}

---------
"""

    send(msg)

# =========================
# SPECULATIVO
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

            change = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
            ma20 = close.rolling(20).mean().iloc[-1]
            rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]
            price = close.iloc[-1]

            timing, strength = get_timing_and_strength(price, ma20, rsi, change)

            if abs(change) > 3:
                alerts.append(f"{t} 📊 {round(change,2)}%\n👉 {timing}\n👉 {strength}")

        except:
            continue

    if alerts:
        msg = "⚡ SPECULATIVO LIVE\n\n"
        for a in alerts[:5]:
            msg += a + "\n\n"
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

        if pnl >= 5:
            send(f"💰 {t} +5% → valuta uscita")

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
        parts = text.split()

        print("📩", text)

        # PULSANTI
        if "MENU" in text:
            show_menu()

        elif "TOP" in text:
            run_top()

        elif "PORTFOLIO" in text:
            analyze_portfolio()

        elif "ANALYZE" in text and len(parts) == 2:
            analyze_ticker_command(parts[1])

        elif parts[0] == "BUY":
            ticker = parts[1]
            price = get_price(ticker)

            if price is None:
                send("❌ Prezzo non disponibile")
                continue

            entry = float(parts[2]) if len(parts) == 3 else price

            positions[ticker] = {"entry": entry}
            send(f"✅ {ticker} registrato a {round(entry,2)}")

        elif parts[0] == "SELL":
            ticker = parts[1]

            if ticker in positions:
                del positions[ticker]
                send(f"❌ {ticker} chiuso e rimosso")
            else:
                send(f"⚠️ {ticker} non presente")

        else:
            send("❓ Comando non riconosciuto")
            show_menu()

    save_positions(positions)
    return offset

# =========================
# MAIN
# =========================

def main():
    send("🚀 BOT AVANZATO ATTIVO")
    show_menu()

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