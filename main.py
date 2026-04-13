import time
import requests
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

print("🔥 FILE PARTITO")

send("🧪 TEST ASSOLUTO")

while True:
    print("🔄 vivo")
    time.sleep(10)
