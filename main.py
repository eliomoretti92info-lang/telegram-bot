import os
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

CHECK_INTERVAL_SECONDS = 86400

ASSETS = [
"AAPL", "MSFT", "NVDA", "AMZN", "META",
"GOOGL", "TSLA", "JPM", "V", "UNH",
"BTC-USD", "ETH-USD", "SOL-USD"
]

# =========================
# TELEGRAM
# =========================

def send(msg: str):
if not TELEGRAM_TOKEN or not CHAT_ID:
print("Token mancanti")
return

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

try:
requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
except Exception as e:
print("Telegram error:", e)

# =========================
# DATA
# =========================

def get_data(ticker):
data = yf.download(ticker, period="6mo", interval="1d", progress=False)

if data is None or data.empty:
return None

close = data["Close"]

if isinstance(close, pd.DataFrame):
close = close.iloc[:, 0]

close = close.dropna()

if len(close) < 60:
return None

return close

# =========================
# ANALISI + ENTRY/EXIT
# =========================

def analyze(ticker, close):
price = float(close.iloc[-1])

rsi = float(ta.momentum.RSIIndicator(close).rsi().iloc[-1])

ma20 = float(close.rolling(20).mean().iloc[-1])
ma50 = float(close.rolling(50).mean().iloc[-1])

score = 0
reasons = []

# TREND
if price > ma50:
score += 30
reasons.append("trend rialzista")

# MOMENTUM
if ma20 > ma50:
score += 20
reasons.append("momentum positivo")

# PULLBACK
if 30 < rsi < 45:
score += 30
reasons.append("pullback sano")

# OVERHEAT
if rsi > 70:
score -= 25
reasons.append("ipercomprato")

if score < 60:
return None

# =========================
# ENTRY / EXIT LOGIC
# =========================

entry = price

stop_loss = ma50 * 0.98 # sotto trend
take_profit_1 = entry * 1.06
take_profit_2 = entry * 1.12

risk = entry - stop_loss
reward = take_profit_2 - entry

rr_ratio = round(reward / risk, 2) if risk > 0 else 0

probability = min(85, max(45, score + 15))

return {
"ticker": ticker,
"price": round(price, 2),
"rsi": round(rsi, 2),
"score": round(score, 2),
"probability": round(probability, 1),
"entry": round(entry, 2),
"sl": round(stop_loss, 2),
"tp1": round(take_profit_1, 2),
"tp2": round(take_profit_2, 2),
"rr": rr_ratio,
"reasons": reasons
}

# =========================
# SCANNER
# =========================

def run_once():
print(f"\n=== SCAN {datetime.now()} ===")

candidates = []

for asset in ASSETS:
try:
close = get_data(asset)
if close is None:
continue

result = analyze(asset, close)

if result:
candidates.append(result)

except Exception as e:
print(f"Errore {asset}: {e}")

if not candidates:
send("⚠️ Nessuna opportunità con rischio/rendimento valido")
return

# ranking per probabilità + qualità rischio
candidates.sort(key=lambda x: (x["probability"], x["rr"]), reverse=True)

top = candidates[:3]

msg = "🔥 TOP 3 TRADE SETUP\n\n"

for i, r in enumerate(top, 1):
msg += (
f"{i}) {r['ticker']}\n"
f"Entry: {r['entry']}\n"
f"SL: {r['sl']}\n"
f"TP1: {r['tp1']} | TP2: {r['tp2']}\n"
f"RR: {r['rr']}\n"
f"Prob: {r['probability']}%\n"
f"{', '.join(r['reasons'])}\n\n"
)

send(msg)

# =========================
# MAIN
# =========================

def main():
print("🔥 SYSTEM READY")

send("✅ Bot attivo - ENTRY/EXIT + RISK MANAGEMENT")

while True:
try:
run_once()
except Exception as e:
print("Errore ciclo:", e)

time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
main()
