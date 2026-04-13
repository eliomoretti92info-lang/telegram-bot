import os
import json
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

CHECK_INTERVAL_SECONDS = 3600
STATE_FILE = "signals_state.json"

ASSETS = ["AAPL", "TSLA", "NVDA", "BTC-USD", "ETH-USD"]


# =========================
# TELEGRAM
# =========================

def send(msg: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM_TOKEN o CHAT_ID mancanti")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=20,
        )
        print("Telegram:", response.status_code)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


# =========================
# STATE MANAGEMENT
# =========================

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Errore salvataggio stato: {e}")


# =========================
# ANALYSIS ENGINE (FIXED)
# =========================

def analyze(ticker: str) -> dict:
    data = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        progress=False,
        auto_adjust=True
    )

    if data is None or data.empty:
        return {
            "ticker": ticker,
            "signal": "HOLD",
            "price": 0,
            "rsi": 0,
            "ma50": 0,
            "score": 0,
            "reasons": ["NO DATA"]
        }

    close = data["Close"]

    # 🔥 FIX CRITICO: forza Series 1D
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.dropna()

    if len(close) < 60:
        return {
            "ticker": ticker,
            "signal": "HOLD",
            "price": 0,
            "rsi": 0,
            "ma50": 0,
            "score": 0,
            "reasons": ["INSUFFICIENT DATA"]
        }

    rsi_series = ta.momentum.RSIIndicator(close).rsi()
    rsi = float(rsi_series.iloc[-1])

    ma50 = float(close.rolling(50).mean().iloc[-1])
    price = float(close.iloc[-1])

    score = 0
    reasons = []

    # scoring più stabile
    if rsi < 35:
        score += (50 - rsi) * 1.5
        reasons.append("RSI basso")
    elif rsi > 65:
        reasons.append("RSI alto")

    if price > ma50:
        score += 30
        reasons.append("sopra MA50")
    else:
        reasons.append("sotto MA50")

    # decisione
    if score >= 60:
        signal = "BUY"
    elif rsi > 70:
        signal = "SELL_PARTIAL"
    else:
        signal = "HOLD"

    return {
        "ticker": ticker,
        "signal": signal,
        "price": round(price, 2),
        "rsi": round(rsi, 2),
        "ma50": round(ma50, 2),
        "score": round(score, 2),
        "reasons": reasons,
    }


# =========================
# FORMAT MESSAGE
# =========================

def format_message(result: dict) -> str:
    emoji = "🟢" if result["signal"] == "BUY" else "🟠" if result["signal"] == "SELL_PARTIAL" else "⚪"

    return (
        f"{emoji} {result['ticker']} - {result['signal']}\n"
        f"Prezzo: {result['price']}\n"
        f"RSI: {result['rsi']}\n"
        f"MA50: {result['ma50']}\n"
        f"Score: {result['score']}\n"
        f"Note: {', '.join(result['reasons'])}"
    )


# =========================
# CORE LOOP
# =========================

def run_once() -> None:
    print(f"\n=== Controllo {datetime.now()} ===")

    state = load_state()
    updated = False

    for asset in ASSETS:
        try:
            result = analyze(asset)

            print(f"{asset} -> {result}")

            signal = result["signal"]
            last_signal = state.get(asset, {}).get("last_signal")

            if signal != "HOLD" and signal != last_signal:
                send(format_message(result))

                state[asset] = {
                    "last_signal": signal,
                    "last_sent_at": datetime.now().isoformat(),
                }

                updated = True

        except Exception as e:
            print(f"Errore su {asset}: {e}")

    if updated:
        save_state(state)


# =========================
# MAIN
# =========================

def main() -> None:
    print("🔥 BOT AVVIATO")

    send("✅ Bot avviato correttamente su Railway")

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"Errore ciclo: {e}")

        print(f"Attendo {CHECK_INTERVAL_SECONDS} secondi...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
