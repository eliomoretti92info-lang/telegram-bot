import os
import time
import json
import logging
from pathlib import Path

import requests
import yfinance as yf
import pandas as pd
import ta


#
============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 30
TOP_INTERVAL = 1800          # 30 minuti
SPEC_INTERVAL = 300          # 5 minuti

POSITIONS_FILE = Path("positions.json")
CONFIG_FILE = Path("config.json")

BENCHMARK = "SPY"

ASSETS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "AMD", "PLTR",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "SPY", "QQQ"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# UTILS
# ============================================================

def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(value, maximum))


def pct_change(series, periods):
    if series is None or len(series) <= periods:
        return 0.0

    old = series.iloc[-periods]
    new = series.iloc[-1]

    if old == 0:
        return 0.0

    return float((new - old) / old * 100)


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error("Errore lettura %s: %s", path, e)
        return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")

    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        tmp.replace(path)
    except Exception as e:
        logging.error("Errore salvataggio %s: %s", path, e)


def load_positions():
    return load_json(POSITIONS_FILE, {})


def save_positions(data):
    save_json(POSITIONS_FILE, data)


def load_config():
    return load_json(CONFIG_FILE, {
        "spec_mode": False,
        "top_auto": True
    })


def save_config(data):
    save_json(CONFIG_FILE, data)


def split_message(text, max_len=3900):
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


# ============================================================
# TELEGRAM
# ============================================================

def telegram_api(method, payload=None):
    if not TELEGRAM_TOKEN:
        logging.warning("TELEGRAM_TOKEN mancante")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"

    try:
        response = requests.post(url, json=payload or {}, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error("Errore Telegram %s: %s", method, e)
        return None


def send(msg, reply_markup=None):
    if not CHAT_ID:
        logging.warning("CHAT_ID mancante")
        return

    for part in split_message(msg):
        payload = {
            "chat_id": CHAT_ID,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        telegram_api("sendMessage", payload)


def answer_callback(callback_query_id):
    if not callback_query_id:
        return

    telegram_api("answerCallbackQuery", {
        "callback_query_id": callback_query_id
    })


def get_updates(offset=None):
    if not TELEGRAM_TOKEN:
        return {"result": []}

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    try:
        response = requests.get(
            url,
            params={
                "offset": offset,
                "timeout": 10,
                "allowed_updates": json.dumps(["message", "callback_query", "edited_message"])
            },
            timeout=20
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException as e:
        logging.error("Errore getUpdates: %s", e)
        return {"result": []}


# ============================================================
# MENU TELEGRAM
# ============================================================

def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "👑 TOP Assoluto", "callback_data": "TOP_ABSOLUTE"},
                {"text": "⚡ SPEC Top", "callback_data": "SPEC_TOP"}
            ],
            [
                {"text": "📊 Analizza Asset", "callback_data": "ANALYZE_MENU"},
                {"text": "💼 Portafoglio", "callback_data": "POSITIONS"}
            ],
            [
                {"text": "🟢 SPEC ON", "callback_data": "SPEC_ON"},
                {"text": "🔴 SPEC OFF", "callback_data": "SPEC_OFF"}
            ],
            [
                {"text": "📘 Comandi", "callback_data": "HELP"},
                {"text": "⚙️ Stato Bot", "callback_data": "STATUS"}
            ]
        ]
    }


def assets_keyboard(prefix="ANALYZE"):
    rows = []
    row = []

    for ticker in ASSETS:
        row.append({
            "text": ticker,
            "callback_data": f"{prefix}:{ticker}"
        })

        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        {"text": "⬅️ Menu", "callback_data": "MENU"}
    ])

    return {"inline_keyboard": rows}


def position_keyboard():
    positions = load_positions()
    rows = []

    for ticker in positions.keys():
        rows.append([
            {"text": f"📊 {ticker}", "callback_data": f"ANALYZE:{ticker}"},
            {"text": f"❌ SELL {ticker}", "callback_data": f"SELL:{ticker}"}
        ])

    rows.append([
        {"text": "⬅️ Menu", "callback_data": "MENU"}
    ])

    return {"inline_keyboard": rows}


def show_menu():
    msg = """
<b>📘 BOT TRADING MENU</b>

Scegli una funzione dai pulsanti sotto.

<b>Comandi manuali disponibili:</b>

BUY TICKER
BUY TICKER prezzo
SELL TICKER

ANALYZE TICKER
TOP
TOP ASSOLUTO
SPEC TOP
HOT
POSITIONS

SPEC ON
SPEC OFF
MENU
"""
    send(msg, main_menu_keyboard())


def show_help():
    msg = """
<b>📘 COMANDI DISPONIBILI</b>

<b>🟢 Operativi</b>
BUY AAPL
BUY AAPL 210.50
SELL AAPL

<b>📊 Analisi</b>
ANALYZE NVDA
ANALYZE BTC-USD
POSITIONS

<b>👑 Scanner</b>
TOP
TOP ASSOLUTO
SPEC TOP
HOT

<b>⚡ Modalità automatica</b>
SPEC ON
SPEC OFF

<b>📋 Menu</b>
MENU

<b>Nota</b>
Il bot non vede davvero ordini nascosti o intenzioni degli operatori.
Usa prezzo, volume, momentum, breakout, RSI e forza relativa come proxy.
"""
    send(msg, main_menu_keyboard())


def show_status():
    config = load_config()
    positions = load_positions()

    msg = f"""
<b>⚙️ STATO BOT</b>

Spec mode: {'🟢 ON' if config.get('spec_mode') else '🔴 OFF'}
Top auto: {'🟢 ON' if config.get('top_auto') else '🔴 OFF'}

Asset monitorati: {len(ASSETS)}
Posizioni aperte: {len(positions)}

Intervallo controllo: {CHECK_INTERVAL}s
TOP automatico: ogni {TOP_INTERVAL // 60} min
SPEC automatico: ogni {SPEC_INTERVAL // 60} min
"""
    send(msg, main_menu_keyboard())


# ============================================================
# MARKET DATA
# ============================================================

def normalize_yfinance_columns(data):
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def download_ohlcv(ticker, period="6mo", interval="1d"):
    try:
        data = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            threads=False
        )

        if data is None or data.empty:
            return None

        data = normalize_yfinance_columns(data)

        required = ["Open", "High", "Low", "Close", "Volume"]

        for col in required:
            if col not in data.columns:
                return None

        data = data.dropna()

        if data.empty:
            return None

        return data

    except Exception as e:
        logging.error("Errore download OHLCV %s: %s", ticker, e)
        return None


def download_close(ticker, period="5d", interval="1h"):
    data = download_ohlcv(ticker, period=period, interval=interval)

    if data is None or "Close" not in data:
        return None

    close = data["Close"].dropna()

    if close.empty:
        return None

    return close


def get_price(ticker):
    close = download_close(ticker, period="5d", interval="1h")

    if close is None:
        return None

    return float(close.iloc[-1])


# ============================================================
# ANALISI SMART DAILY
# ============================================================

def analyze_smart(ticker, benchmark_close=None):
    data = download_ohlcv(ticker, period="6mo", interval="1d")

    if data is None or len(data) < 60:
        return None

    try:
        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        price = float(close.iloc[-1])

        rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi().dropna()

        if rsi_series.empty:
            return None

        rsi = float(rsi_series.iloc[-1])

        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()

        sma20_now = float(sma20.iloc[-1])
        sma50_now = float(sma50.iloc[-1])

        trend_20 = price > sma20_now
        trend_50 = price > sma50_now

        momentum_1d = pct_change(close, 1)
        momentum_5d = pct_change(close, 5)
        momentum_20d = pct_change(close, 20)

        avg_volume_20 = volume.rolling(20).mean().iloc[-1]
        current_volume = volume.iloc[-1]

        volume_ratio = float(current_volume / avg_volume_20) if avg_volume_20 > 0 else 1.0

        recent_high_20 = float(high.rolling(20).max().iloc[-2])
        recent_low_20 = float(low.rolling(20).min().iloc[-2])

        breakout = price > recent_high_20

        distance_from_high = (price - recent_high_20) / recent_high_20 * 100
        distance_from_low = (price - recent_low_20) / recent_low_20 * 100

        volatility = float(close.pct_change().rolling(20).std().iloc[-1] * 100)

        relative_strength = 0.0

        if benchmark_close is not None and len(benchmark_close) >= 20:
            asset_20d = pct_change(close, 20)
            bench_20d = pct_change(benchmark_close, 20)
            relative_strength = asset_20d - bench_20d

        score = 0.0

        if momentum_1d > 0:
            score += clamp(momentum_1d * 4, 0, 15)

        if momentum_5d > 0:
            score += clamp(momentum_5d * 2.5, 0, 20)

        if momentum_20d > 0:
            score += clamp(momentum_20d * 1.2, 0, 20)

        if volume_ratio > 1:
            score += clamp((volume_ratio - 1) * 15, 0, 20)

        if trend_20:
            score += 7

        if trend_50:
            score += 7

        if breakout:
            score += 15

        if 50 <= rsi <= 68:
            score += 12
        elif 45 <= rsi < 50:
            score += 6
        elif 68 < rsi <= 75:
            score += 4
        elif rsi > 80:
            score -= 15

        if relative_strength > 0:
            score += clamp(relative_strength * 1.5, 0, 12)

        if volatility > 6:
            score -= 8

        if distance_from_low > 35:
            score -= 6

        score = clamp(score, 0, 100)

        if score >= 80:
            label = "🔥 TOP ASSOLUTO"
            action = "SPECULATIVO FORTE"
        elif score >= 65:
            label = "🟢 MOLTO INTERESSANTE"
            action = "POSSIBILE ENTRATA"
        elif score >= 50:
            label = "🟡 DA MONITORARE"
            action = "ATTENDERE CONFERMA"
        elif score >= 35:
            label = "⚪ NEUTRO"
            action = "NESSUN VANTAGGIO"
        else:
            label = "🔴 DEBOLE"
            action = "EVITARE"

        return {
            "ticker": ticker,
            "price": price,
            "score": score,
            "label": label,
            "action": action,
            "rsi": rsi,
            "momentum_1d": momentum_1d,
            "momentum_5d": momentum_5d,
            "momentum_20d": momentum_20d,
            "volume_ratio": volume_ratio,
            "breakout": breakout,
            "relative_strength": relative_strength,
            "volatility": volatility,
            "trend_20": trend_20,
            "trend_50": trend_50,
            "distance_from_high": distance_from_high,
            "distance_from_low": distance_from_low,
            "sma20": sma20_now,
            "sma50": sma50_now
        }

    except Exception as e:
        logging.error("Errore analyze_smart %s: %s", ticker, e)
        return None


def format_smart_result(res, rank=None):
    breakout_text = "SÌ 🚀" if res["breakout"] else "NO"

    if res["trend_20"] and res["trend_50"]:
        trend_text = "FORTE 📈"
    elif res["trend_20"] or res["trend_50"]:
        trend_text = "PARZIALE"
    else:
        trend_text = "DEBOLE 📉"

    title = f"#{rank} {res['ticker']}" if rank else res["ticker"]

    return f"""
<b>{title}</b>
Prezzo: <b>{res["price"]:.2f}</b>
Score: <b>{res["score"]:.1f}/100</b>
Segnale: {res["label"]}
Azione: <b>{res["action"]}</b>

RSI: {res["rsi"]:.1f}
Momentum 1D: {res["momentum_1d"]:.2f}%
Momentum 5D: {res["momentum_5d"]:.2f}%
Momentum 20D: {res["momentum_20d"]:.2f}%

Volume anomalo: {res["volume_ratio"]:.2f}x
Breakout: {breakout_text}
Trend SMA20/SMA50: {trend_text}
Forza vs {BENCHMARK}: {res["relative_strength"]:.2f}%
Volatilità: {res["volatility"]:.2f}%
"""


def run_top_absolute():
    benchmark_data = download_ohlcv(BENCHMARK, period="6mo", interval="1d")
    benchmark_close = benchmark_data["Close"] if benchmark_data is not None else None

    results = []

    for ticker in ASSETS:
        res = analyze_smart(ticker, benchmark_close)

        if res:
            results.append(res)

    if not results:
        send("❌ Nessun dato disponibile per il TOP ASSOLUTO", main_menu_keyboard())
        return

    results.sort(key=lambda x: x["score"], reverse=True)

    msg = """
<b>👑 TOP ASSOLUTO SPECULATIVO</b>
Radar: momentum + volumi + breakout + RSI + trend + forza relativa

"""

    for i, res in enumerate(results[:7], start=1):
        msg += format_smart_result(res, rank=i)
        msg += "\n---------\n"

    send(msg, main_menu_keyboard())


# ============================================================
# SPECULATIVO INTRADAY
# ============================================================

def analyze_intraday_spec(ticker):
    data = download_ohlcv(ticker, period="5d", interval="15m")

    if data is None or len(data) < 50:
        return None

    try:
        close = data["Close"]
        volume = data["Volume"]
        high = data["High"]

        price = float(close.iloc[-1])

        change_15m = pct_change(close, 1)
        change_45m = pct_change(close, 3)
        change_2h = pct_change(close, 8)

        avg_volume_30 = volume.rolling(30).mean().iloc[-1]
        current_volume = volume.iloc[-1]

        volume_ratio = float(current_volume / avg_volume_30) if avg_volume_30 > 0 else 1.0

        high_20 = float(high.rolling(20).max().iloc[-2])
        breakout = price > high_20

        rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi().dropna()

        if rsi_series.empty:
            return None

        rsi = float(rsi_series.iloc[-1])

        score = 0.0

        if change_15m > 0:
            score += clamp(change_15m * 10, 0, 20)

        if change_45m > 0:
            score += clamp(change_45m * 7, 0, 25)

        if change_2h > 0:
            score += clamp(change_2h * 4, 0, 25)

        if volume_ratio > 1:
            score += clamp((volume_ratio - 1) * 20, 0, 25)

        if breakout:
            score += 20

        if 50 <= rsi <= 72:
            score += 10
        elif rsi > 80:
            score -= 20

        score = clamp(score, 0, 100)

        if score >= 80:
            label = "🚀 ESPLOSIVO"
        elif score >= 65:
            label = "🔥 MOLTO CALDO"
        elif score >= 50:
            label = "🟡 INTERESSANTE"
        else:
            label = "⚪ NORMALE"

        return {
            "ticker": ticker,
            "price": price,
            "score": score,
            "label": label,
            "change_15m": change_15m,
            "change_45m": change_45m,
            "change_2h": change_2h,
            "volume_ratio": volume_ratio,
            "breakout": breakout,
            "rsi": rsi
        }

    except Exception as e:
        logging.error("Errore analyze_intraday_spec %s: %s", ticker, e)
        return None


def run_speculative_top():
    results = []

    for ticker in ASSETS:
        res = analyze_intraday_spec(ticker)

        if res:
            results.append(res)

    if not results:
        send("⚡ SPEC TOP\n\nNessun dato disponibile.", main_menu_keyboard())
        return

    results.sort(key=lambda x: x["score"], reverse=True)

    hot = [r for r in results if r["score"] >= 50]

    if not hot:
        send("⚡ SPEC TOP\n\nNessun setup speculativo forte adesso.", main_menu_keyboard())
        return

    msg = """
<b>⚡ SPEC TOP LIVE</b>
Scanner 15m: momentum + volume + breakout

"""

    for i, r in enumerate(hot[:7], start=1):
        breakout = "SÌ 🚀" if r["breakout"] else "NO"

        msg += f"""
<b>#{i} {r["ticker"]}</b>
Prezzo: <b>{r["price"]:.2f}</b>
Score: <b>{r["score"]:.1f}/100</b>
Segnale: {r["label"]}

15m: {r["change_15m"]:.2f}%
45m: {r["change_45m"]:.2f}%
2h: {r["change_2h"]:.2f}%

Volume: {r["volume_ratio"]:.2f}x
RSI: {r["rsi"]:.1f}
Breakout: {breakout}

---------
"""

    send(msg, main_menu_keyboard())


# ============================================================
# ANALISI MANUALE
# ============================================================

def analyze_manual(ticker):
    benchmark_data = download_ohlcv(BENCHMARK, period="6mo", interval="1d")
    benchmark_close = benchmark_data["Close"] if benchmark_data is not None else None

    res = analyze_smart(ticker, benchmark_close)

    if not res:
        send(f"❌ Analisi non disponibile per {ticker}", main_menu_keyboard())
        return

    msg = "<b>📊 ANALISI MANUALE</b>\n"
    msg += format_smart_result(res)

    if res["score"] >= 80:
        comment = "Setup molto forte, ma attenzione a non inseguire candele già troppo estese."
    elif res["score"] >= 65:
        comment = "Setup interessante. Meglio cercare conferma su breakout o pullback controllato."
    elif res["score"] >= 50:
        comment = "Asset da monitorare. Non c'è ancora vantaggio netto."
    else:
        comment = "Setup debole. Meglio aspettare condizioni migliori."

    msg += f"\n<b>Lettura:</b> {comment}"

    send(msg, main_menu_keyboard())


# ============================================================
# PORTFOLIO
# ============================================================

def buy_position(ticker, entry=None):
    positions = load_positions()

    market_price = get_price(ticker)

    if market_price is None:
        send(f"❌ Prezzo non disponibile per {ticker}", main_menu_keyboard())
        return

    final_entry = entry if entry is not None else market_price

    if final_entry <= 0:
        send("❌ Prezzo non valido", main_menu_keyboard())
        return

    positions[ticker] = {
        "entry": final_entry,
        "alert_down": False,
        "alert_up": False,
        "created_at": int(time.time()),
        "last_price": market_price,
        "pnl": 0
    }

    save_positions(positions)

    send(
        f"✅ <b>{ticker}</b> registrato a <b>{final_entry:.2f}</b>",
        main_menu_keyboard()
    )


def sell_position(ticker):
    positions = load_positions()

    if ticker in positions:
        del positions[ticker]
        save_positions(positions)
        send(f"❌ <b>{ticker}</b> rimosso dal portafoglio", main_menu_keyboard())
    else:
        send(f"⚠️ {ticker} non è presente nel portafoglio", main_menu_keyboard())


def monitor():
    positions = load_positions()
    changed = False

    for ticker, pos in list(positions.items()):
        price = get_price(ticker)

        if price is None:
            continue

        entry = pos.get("entry")

        if not entry:
            continue

        pnl = (price - entry) / entry * 100

        positions[ticker]["last_price"] = price
        positions[ticker]["pnl"] = pnl

        if pnl <= -1 and not pos.get("alert_down"):
            send(f"🔻 <b>{ticker}</b> {pnl:.2f}% → attenzione")
            positions[ticker]["alert_down"] = True
            changed = True

        if pnl >= 2 and not pos.get("alert_up"):
            send(f"🔺 <b>{ticker}</b> {pnl:.2f}% → profitto")
            positions[ticker]["alert_up"] = True
            changed = True

    if changed:
        save_positions(positions)


def show_positions():
    positions = load_positions()

    if not positions:
        send("📭 Nessuna posizione aperta", main_menu_keyboard())
        return

    msg = "<b>💼 POSIZIONI APERTE</b>\n\n"

    total_count = 0

    for ticker, pos in positions.items():
        total_count += 1

        entry = pos.get("entry")
        last_price = get_price(ticker)

        if last_price is not None and entry:
            pnl = (last_price - entry) / entry * 100
            pos["last_price"] = last_price
            pos["pnl"] = pnl

            emoji = "🟢" if pnl >= 0 else "🔴"

            msg += f"""
<b>{ticker}</b>
Entry: {entry:.2f}
Prezzo: {last_price:.2f}
PnL: {emoji} {pnl:.2f}%

---------
"""
        else:
            msg += f"""
<b>{ticker}</b>
Entry: {entry}
Prezzo non disponibile

---------
"""

    save_positions(positions)

    msg += f"\nTotale posizioni: {total_count}"

    send(msg, position_keyboard())


# ============================================================
# CALLBACK MENU
# ============================================================

def handle_callback(callback):
    if not isinstance(callback, dict):
        return

    callback_id = callback.get("id")
    data = callback.get("data", "")

    if callback_id:
        answer_callback(callback_id)

    if not data:
        return

    logging.info("Callback ricevuta: %s", data)

    if data == "MENU":
        show_menu()

    elif data == "HELP":
        show_help()

    elif data == "STATUS":
        show_status()

    elif data == "TOP_ABSOLUTE":
        run_top_absolute()

    elif data == "SPEC_TOP":
        run_speculative_top()

    elif data == "ANALYZE_MENU":
        send("📊 Scegli asset da analizzare:", assets_keyboard("ANALYZE"))

    elif data == "POSITIONS":
        show_positions()

    elif data == "SPEC_ON":
        config = load_config()
        config["spec_mode"] = True
        save_config(config)
        send("⚡ SPEC MODE ATTIVO", main_menu_keyboard())

    elif data == "SPEC_OFF":
        config = load_config()
        config["spec_mode"] = False
        save_config(config)
        send("⛔ SPEC MODE DISATTIVO", main_menu_keyboard())

    elif data.startswith("ANALYZE:"):
        ticker = data.split(":", 1)[1]
        analyze_manual(ticker)

    elif data.startswith("SELL:"):
        ticker = data.split(":", 1)[1]
        sell_position(ticker)

    else:
        send("Comando pulsante non riconosciuto.", main_menu_keyboard())


# ============================================================
# COMANDI TESTUALI
# ============================================================

def handle_text_command(text):
    if not isinstance(text, str):
        return

    text = text.strip()

    if not text:
        return

    upper = text.upper()
    parts = upper.split()

    if not parts:
        return

    cmd = parts[0]

    logging.info("Comando ricevuto: %s", upper)

    if upper == "MENU":
        show_menu()

    elif upper in ["HELP", "COMANDI"]:
        show_help()

    elif upper in ["STATUS", "STATO"]:
        show_status()

    elif upper in ["TOP", "TOP ASSOLUTO", "BEST", "SCAN"]:
        run_top_absolute()

    elif upper in ["SPEC TOP", "HOT", "SCALP"]:
        run_speculative_top()

    elif upper == "POSITIONS":
        show_positions()

    elif upper == "SPEC ON":
        config = load_config()
        config["spec_mode"] = True
        save_config(config)
        send("⚡ SPEC MODE ATTIVO", main_menu_keyboard())

    elif upper == "SPEC OFF":
        config = load_config()
        config["spec_mode"] = False
        save_config(config)
        send("⛔ SPEC MODE DISATTIVO", main_menu_keyboard())

    elif cmd == "ANALYZE":
        if len(parts) < 2:
            send("Formato corretto: ANALYZE TICKER", main_menu_keyboard())
            return

        ticker = parts[1]
        analyze_manual(ticker)

    elif cmd == "BUY":
        if len(parts) < 2:
            send("Formato corretto: BUY TICKER oppure BUY TICKER prezzo", main_menu_keyboard())
            return

        ticker = parts[1]
        entry = None

        if len(parts) >= 3:
            entry = safe_float(parts[2])

            if entry is None:
                send("❌ Prezzo non valido", main_menu_keyboard())
                return

        buy_position(ticker, entry)

    elif cmd == "SELL":
        if len(parts) < 2:
            send("Formato corretto: SELL TICKER", main_menu_keyboard())
            return

        ticker = parts[1]
        sell_position(ticker)

    else:
        send("Comando non riconosciuto. Scrivi MENU.", main_menu_keyboard())


def handle_updates(offset):
    data = get_updates(offset)

    if not isinstance(data, dict):
        logging.error("Risposta Telegram non valida: %s", data)
        return offset

    updates = data.get("result", [])

    if not isinstance(updates, list):
        logging.error("Campo result Telegram non valido: %s", updates)
        return offset

    for update in updates:
        try:
            if "update_id" in update:
                offset = update["update_id"] + 1

            if "callback_query" in update:
                handle_callback(update.get("callback_query", {}))
                continue

            message = update.get("message") or update.get("edited_message") or {}

            if not isinstance(message, dict):
                continue

            text = message.get("text")

            if not text:
                continue

            handle_text_command(text)

        except Exception as e:
            logging.exception("Errore gestione singolo update Telegram: %s", e)
            continue

    return offset


# ============================================================
# MAIN
# ============================================================

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Imposta TELEGRAM_TOKEN nelle variabili ambiente")

    if not CHAT_ID:
        raise RuntimeError("Imposta CHAT_ID nelle variabili ambiente")

    send("🚀 <b>BOT TRADING ATTIVO</b>", main_menu_keyboard())

    offset = None
    last_top = 0
    last_spec = 0

    while True:
        try:
            offset = handle_updates(offset)

        except Exception as e:
            logging.exception("Errore handle_updates: %s", e)

        try:
            monitor()

        except Exception as e:
            logging.exception("Errore monitor: %s", e)

        try:
            now = time.time()
            config = load_config()

            if config.get("top_auto", True) and now - last_top >= TOP_INTERVAL:
                run_top_absolute()
                last_top = now

            if config.get("spec_mode", False) and now - last_spec >= SPEC_INTERVAL:
                run_speculative_top()
                last_spec = now

        except Exception as e:
            logging.exception("Errore scanner automatici: %s", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
    