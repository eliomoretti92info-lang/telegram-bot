import yfinance as yf
import ta
import requests

TELEGRAM_TOKEN = "8682232337:AAFWTFSFzm45g8C_1N7909xoSQ66a-NsHww"
CHAT_ID = "8680513276"

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    print(r.status_code, r.text)

def analyze(ticker):
    data = yf.download(ticker, period="6mo", progress=False)

    close = data["Close"].dropna()
    if len(close) < 50:
        return "HOLD"

    rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    price = close.iloc[-1]

    score = 0
    if rsi < 35:
        score += 40
    if price > ma50:
        score += 30

    if score >= 70:
        return "BUY"
    elif rsi > 65:
        return "SELL_PARTIAL"
    return "HOLD"

def run():
    send("Test Railway OK")

    assets = ["AAPL", "TSLA", "NVDA", "BTC-USD", "ETH-USD"]

    for a in assets:
        try:
            signal = analyze(a)
            print(a, signal)

            if signal != "HOLD":
                send(f"{a} -> {signal}")
        except Exception as e:
            print(f"Errore su {a}: {e}")

if __name__ == "__main__":
    run()
