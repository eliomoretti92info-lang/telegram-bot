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
# STATO
# =========================
SPEC_MODE = False

# =========================
# TELEGRAM
# =========================

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    except:
        pass

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
        price = float(close.iloc[-1])
        rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]

        return price, rsi
    except:
        return None

# =========================
# TOP 30 MIN
# =========================

def run_top():
    msg = "🔥 MIGLIORI ORA (30 min)\n\n"

    for t in ASSETS[:5]:
        res = analyze(t)
        if not res:
            continue

        price, rsi = res
        msg += f"{t} | {round(price,2)} | RSI {round(rsi,1)}\n"

    send(msg)

# =========================
# SPECULATIVO 5 MIN
# =========================

def run_speculative():
    msg = "⚡ SPECULATIVO LIVE (5 min)\n\n"

    for t in ASSETS:
        try:
            data = yf.download(t, period="1d", interval="15m", progress=False)

            if data is None or data.empty:
                continue

            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

            close = close.dropna()
            if len(close) < 10:
                continue

            change = (close.iloc[-1] - close.iloc[-3]) / close.iloc[-3] * 100

            if abs(change) > 2:
                msg += f"{t} → {round(change,2)}%\n"

        except:
            continue

    send(msg)

# =========================
# MONITOR POSIZIONI
# =========================

def monitor():
    positions = load_positions()

    for t in list(positions.keys()):
        price = get_price(t)
        if price is None:
            continue

        entry = positions[t]["entry"]
        pnl = (price - entry) / entry * 100

        if pnl <= -1 and not positions[t].get("alert_down"):
            send(f"🔻 {t} -1% → Vuoi uscire?")
            positions[t]["alert_down"] = True

        if pnl >= 2 and not positions[t].get("alert_up"):
            send(f"🔺 {t} +2% → Vuoi prendere profitto?")
            positions[t]["alert_up"] = True

        if pnl <= -4:
            send(f"⚠️ {t} stop loss")
            del positions[t]

    save_positions(positions)

# =========================
# COMANDI
# =========================

def handle_commands(offset):
    global SPEC_MODE

    data = get_updates(offset)
    positions = load_positions()

    for u in data.get("result", []):
        offset = u["update_id"] + 1
        text = u.get("message", {}).get("text", "").upper().strip()
        parts = text.split()

        print("📩", text)

        if text == "SPEC ON":
            SPEC_MODE = True
            send("⚡ Modalità SPECULATIVA ATTIVA (5 min)")

        elif text == "SPEC OFF":
            SPEC_MODE = False
            send("⛔ Modalità SPECULATIVA DISATTIVATA")

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

    save_positions(positions)
    return offset

# =========================
# MAIN
# =========================

def main():
    send("🚀 BOT ATTIVO (30min + Spec OFF)")

    offset = None
    last_top = 0
    last_spec = 0

    while True:
        try:
            offset = handle_commands(offset)
            monitor()

            # 🔥 ogni 30 min
            if time.time() - last_top > 1800:
                run_top()
                last_top = time.time()

            # ⚡ spec attiva ogni 5 min
            if SPEC_MODE and time.time() - last_spec > 300:
                run_speculative()
                last_spec = time.time()

        except Exception as e:
            print("Errore:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()