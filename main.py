import os
import json
import time
from datetime import datetime

import requests
import yfinance as yf
import ta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL_SECONDS = 3600
STATE_FILE = "signals_state.json"

ASSETS = ["AAPL", "TSLA", "NVDA", "BTC-USD", "ETH-USD"]


def send(msg: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Mancano TELEGRAM_TOKEN o CHAT_ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=20,
        )
        print("Telegram:", response.status_code, response.text)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Errore lettura stato: {e}")
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Errore salvataggio stato: {e}")


def analyze(ticker: str) -> dict:
    data = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)

    if data.empty:
        raise ValueError("Nessun dato scaricato")

    close = data["Close"].dropna()
    if len(close) < 60:
        raise ValueError("Dati insufficienti per calcolare RSI e MA50")

    rsi = float(ta.momentum.RSIIndicator(close).rsi().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    price = float(close.iloc[-1])

    score = 0
    reasons = []

    if rsi < 35:
        score += 40
        reasons.append("RSI basso")
    elif rsi > 65:
        reasons.append("RSI alto")

    if price > ma50:
        score += 30
        reasons.append("sopra MA50")
    else:
        reasons.append("sotto MA50")

    if score >= 70:
        signal = "BUY"
    elif rsi > 65:
        signal = "SELL_PARTIAL"
    else:
        signal = "HOLD"

    return {
        "ticker": ticker,
        "signal": signal,
        "price": round(price, 2),
        "rsi": round(rsi, 2),
        "ma50": round(ma50, 2),
        "score": score,
        "reasons": reasons,
    }


def format_message(result: dict) -> str:
    ticker = result["ticker"]
    signal = result["signal"]
    price = result["price"]
    rsi = result["rsi"]
    ma50 = result["ma50"]
    reasons = ", ".join(result["reasons"])

    if signal == "BUY":
        emoji = "🟢"
    elif signal == "SELL_PARTIAL":
        emoji = "🟠"
    else:
        emoji = "⚪"

    return (
        f"{emoji} {ticker} - {signal}\n"
        f"Prezzo: {price}\n"
        f"RSI: {rsi}\n"
        f"MA50: {ma50}\n"
        f"Note: {reasons}"
    )


def run_once() -> None:
    print(f"\n=== Controllo {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    state = load_state()
    updated = False

    for asset in ASSETS:
        try:
            result = analyze(asset)
            signal = result["signal"]

            print(
                f"{asset}: signal={signal}, "
                f"price={result['price']}, rsi={result['rsi']}, ma50={result['ma50']}"
            )

            last_signal = state.get(asset, {}).get("last_signal")

            if signal != "HOLD" and signal != last_signal:
                send(format_message(result))
                state[asset] = {
                    "last_signal": signal,
                    "last_sent_at": datetime.now().isoformat(),
                }
                updated = True
                print(f"Messaggio inviato per {asset}: {signal}")
            elif signal == "HOLD":
                if last_signal != "HOLD":
                    state[asset] = {
                        "last_signal": "HOLD",
                        "last_sent_at": state.get(asset, {}).get("last_sent_at"),
                    }
                    updated = True
                print(f"Nessun invio per {asset}: HOLD")
            else:
                print(f"Nessun invio per {asset}: segnale invariato ({signal})")

        except Exception as e:
            print(f"Errore su {asset}: {e}")

    if updated:
        save_state(state)


def main() -> None:
    send("✅ Bot avviato correttamente su Railway")

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"Errore generale ciclo: {e}")

        print(f"Attendo {CHECK_INTERVAL_SECONDS} secondi...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
