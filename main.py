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

def send(msg, keyboard=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)

    try:
        requests.post(url, data=data, timeout=20)
    except Exception as e:
        print("Telegram error:", e)

def keyboard_menu():
    return {
        "keyboard": [
            ["📊 TOP", "📘 MENU"],
            ["📈 ANALYZE", "💼 PORTFOLIO"],
            ["💰 BUY", "❌ SELL"]
        ],
        "resize_keyboard": True
    }

def keyboard_trade(ticker):
    return {
        "keyboard": [
            [f"❌ SELL {ticker}", f"🟢 HOLD {ticker}"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

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

BUY TICKER
SELL TICKER

ANALYZE TICKER
ANALYZE PORTFOLIO

TOP → opportunità

Scrivi oppure usa i pulsanti 👇
"""
    send(msg, keyboard_menu())

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
# MONITOR (INTERATTIVO)
# =========================

def monitor():
    positions = load_positions()

    for t in list(positions.keys()):
        price = get_price(t)
        if price is None:
            continue

        entry = positions[t]["entry"]
        pnl = (price - entry) / entry * 100

        # 🔻 -1%
        if pnl <= -1 and not positions[t].get("alert_down"):
            send(
                f"🔻 {t} -1%\nVuoi uscire?",
                keyboard_trade(t)
            )
            positions[t]["alert_down"] = True

        # 🔺 +2%
        if pnl >= 2 and not positions[t].get("alert_up"):
            send(
                f"🔺 {t} +2%\nVuoi prendere profitto?",
                keyboard_trade(t)
            )
            positions[t]["alert_up"] = True

        # 💰 +5%
        if pnl >= 5:
            send(f"💰 {t} +5% → valuta uscita")

        # ⚠️ STOP LOSS
        if pnl <= -4:
            send(f"⚠️ {t} stop loss automatico")
            del positions[t]

    save_positions(positions)

# =========================
# ANALYZE BASE
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
        price = float(close.iloc[-1])
        rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]

        return price, rsi
    except:
        return None

# =========================
# TOP
# =========================

def run_top():
    msg = "🔥 MIGLIORI ORA\n\n"

    for t in ASSETS[:3]:
        res = analyze(t)
        if not res:
            continue

        price, rsi = res

        msg += f"{t}\nPrezzo: {round(price,2)}\nRSI: {round(rsi,1)}\n\n"

    send(msg)

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

        if "MENU" in text:
            show_menu()

        elif "TOP" in text:
            run_top()

        elif "PORTFOLIO" in text:
            send(str(positions))

        elif parts[0] == "BUY":
            ticker = parts[1]
            price = get_price(ticker)

            if price is None:
                send("❌ Prezzo non disponibile")
                continue

            entry = float(parts[2]) if len(parts) == 3 else price

            positions[ticker] = {
                "entry": entry,
                "alert_down": False,
                "alert_up": False
            }

            send(f"✅ {ticker} registrato a {round(entry,2)}")

        elif parts[0] == "SELL":
            ticker = parts[1]

            if ticker in positions:
                del positions[ticker]
                send(f"❌ {ticker} venduto")
            else:
                send("⚠️ Non presente")

        elif "HOLD" in text:
            send("👍 Mantieni posizione")

        else:
            send("❓ Comando non riconosciuto")
            show_menu()

    save_positions(positions)
    return offset

# =========================
# MAIN
# =========================

def main():
    send("🚀 BOT INTERATTIVO ATTIVO")
    show_menu()

    offset = None

    while True:
        try:
            offset = handle_commands(offset)
            monitor()
        except Exception as e:
            print("Errore:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()