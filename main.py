import os
import time
import json
import html
import logging
from pathlib import Path

import requests
import yfinance as yf
import pandas as pd
import ta


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 30

SCAN_INTERVAL = 300          # Scanner ogni 5 minuti
SIGNAL_COOLDOWN = 1800       # Non ripete stesso segnale per 30 minuti

POSITIONS_FILE = Path("positions.json")
STATE_FILE = Path("state.json")

MIN_SIGNAL_SCORE = 78        # Più alto = meno messaggi, più qualità
MAX_SIGNALS_PER_SCAN = 3     # Meno messaggi

PROFIT_STEP = 1.0
LOSS_STEP = 1.0

POSITION_SNOOZE_SECONDS = 900

ASSETS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "TSLA", "GOOGL", "AMD", "PLTR",
    "SPY", "QQQ",
    "BTC-USD", "ETH-USD", "SOL-USD"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# UTILS
# ============================================================

def now_ts():
    return int(time.time())


def e(value):
    return html.escape(str(value))


def clean_ticker(ticker):
    return str(ticker).upper().strip()


def safe_float(value):
    try:
        return float(value)
    except Exception:
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
    except Exception as err:
        logging.error("Errore lettura %s: %s", path, err)
        return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")

    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        tmp.replace(path)
    except Exception as err:
        logging.error("Errore salvataggio %s: %s", path, err)


def load_positions():
    return load_json(POSITIONS_FILE, {})


def save_positions(data):
    save_json(POSITIONS_FILE, data)


def load_state():
    return load_json(STATE_FILE, {
        "auto_scan": True,
        "last_signals": {}
    })


def save_state(data):
    save_json(STATE_FILE, data)


def split_message(text, max_len=3900):
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


def pnl_percent(price, entry):
    if not entry or entry <= 0:
        return 0.0

    return float((price - entry) / entry * 100)


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
    except requests.RequestException as err:
        logging.error("Errore Telegram %s: %s", method, err)
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


def answer_callback(callback_id, text=None):
    if not callback_id:
        return

    payload = {"callback_query_id": callback_id}

    if text:
        payload["text"] = text

    telegram_api("answerCallbackQuery", payload)


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
                "allowed_updates": json.dumps([
                    "message",
                    "callback_query",
                    "edited_message"
                ])
            },
            timeout=20
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException as err:
        logging.error("Errore getUpdates: %s", err)
        return {"result": []}


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🎯 Miglior segnale ora", "callback_data": "BEST_NOW"},
                {"text": "🔎 Scan completo", "callback_data": "SCAN_NOW"}
            ],
            [
                {"text": "📊 Analizza asset", "callback_data": "ANALYZE_MENU"},
                {"text": "💼 Portafoglio", "callback_data": "POSITIONS"}
            ],
            [
                {"text": "🟢 Auto Scan ON", "callback_data": "SCAN_ON"},
                {"text": "🔴 Auto Scan OFF", "callback_data": "SCAN_OFF"}
            ],
            [
                {"text": "📘 Comandi", "callback_data": "HELP"},
                {"text": "⚙️ Stato", "callback_data": "STATUS"}
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
            {"text": f"🚪 Esci {ticker}", "callback_data": f"EXIT:{ticker}"}
        ])

    rows.append([
        {"text": "⬅️ Menu", "callback_data": "MENU"}
    ])

    return {"inline_keyboard": rows}


def position_alert_keyboard(ticker):
    ticker = clean_ticker(ticker)

    return {
        "inline_keyboard": [
            [
                {"text": "🚪 Esci", "callback_data": f"EXIT:{ticker}"},
                {"text": "🛡 Resto dentro", "callback_data": f"STAY:{ticker}"}
            ],
            [
                {"text": "📊 Analizza", "callback_data": f"ANALYZE:{ticker}"},
                {"text": "💼 Portafoglio", "callback_data": "POSITIONS"}
            ]
        ]
    }


# ============================================================
# MENU
# ============================================================

def show_menu():
    msg = """
<b>🤖 BOT TREND ANTICIPATORE</b>

Questo bot cerca segnali più precoci e manda pochi alert.

<b>Obiettivo:</b>
- direzione chiara: LONG o RIBASSO
- evitare ingressi troppo tardi
- segnalare solo setup forti
- proteggere le posizioni aperte

Usa i pulsanti sotto.
"""
    send(msg, main_keyboard())


def show_help():
    msg = """
<b>📘 COMANDI</b>

<b>Scanner</b>
BEST
SCAN
AUTO ON
AUTO OFF

<b>Analisi</b>
ANALYZE NVDA
ANALYZE BTC-USD

<b>Portafoglio</b>
BUY AAPL
BUY AAPL 210.50
SELL AAPL
POSITIONS

<b>Gestione posizione</b>
STAY AAPL
EXIT AAPL

<b>Menu</b>
MENU

<b>Nota importante</b>
Il bot non può prevedere con certezza il mercato.
Cerca setup anticipati usando trend multi-timeframe, EMA, MACD, volume, RSI, distanza dal prezzo medio e rischio di movimento già esteso.
"""
    send(msg, main_keyboard())


def show_status():
    state = load_state()
    positions = load_positions()

    msg = f"""
<b>⚙️ STATO BOT</b>

Auto scan: {'🟢 ON' if state.get('auto_scan') else '🔴 OFF'}
Asset monitorati: {len(ASSETS)}
Posizioni aperte: {len(positions)}

Scan ogni: {SCAN_INTERVAL // 60} min
Score minimo segnale: {MIN_SIGNAL_SCORE}/100
Max segnali per scan: {MAX_SIGNALS_PER_SCAN}

Monitor posizione:
+1%, +2%, +3%...
-1%, -2%, -3%...
"""
    send(msg, main_keyboard())


# ============================================================
# MARKET DATA
# ============================================================

def normalize_columns(data):
    if data is None:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data


def download_ohlcv(ticker, period="30d", interval="15m"):
    ticker = clean_ticker(ticker)

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

        data = normalize_columns(data)

        required = ["Open", "High", "Low", "Close", "Volume"]

        for col in required:
            if col not in data.columns:
                return None

        data = data.dropna()

        if len(data) < 60:
            return None

        return data

    except Exception as err:
        logging.error("Errore download %s: %s", ticker, err)
        return None


def get_price(ticker):
    data = download_ohlcv(ticker, period="5d", interval="15m")

    if data is None:
        return None

    return float(data["Close"].iloc[-1])


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(data):
    df = data.copy()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    df["ema9"] = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df["ema21"] = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(close, window=50).ema_indicator()

    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    atr = ta.volatility.AverageTrueRange(
        high=high,
        low=low,
        close=close,
        window=14
    )
    df["atr"] = atr.average_true_range()
    df["atr_pct"] = df["atr"] / close * 100

    df["vol_avg20"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["vol_avg20"]

    df["high20_prev"] = high.rolling(20).max().shift(1)
    df["low20_prev"] = low.rolling(20).min().shift(1)

    df["ema21_slope"] = df["ema21"].diff(3)
    df["ema50_slope"] = df["ema50"].diff(5)

    df = df.dropna()

    return df


# ============================================================
# TREND ENGINE
# ============================================================

def score_long(df15, df60):
    last = df15.iloc[-1]
    prev = df15.iloc[-2]
    htf = df60.iloc[-1]

    price = float(last["Close"])
    ema9 = float(last["ema9"])
    ema21 = float(last["ema21"])
    ema50 = float(last["ema50"])

    rsi = float(last["rsi"])
    volume_ratio = float(last["volume_ratio"])
    macd_hist = float(last["macd_hist"])
    macd_hist_prev = float(prev["macd_hist"])

    momentum_15m = pct_change(df15["Close"], 1)
    momentum_45m = pct_change(df15["Close"], 3)
    momentum_2h = pct_change(df15["Close"], 8)

    htf_price = float(htf["Close"])
    htf_ema21 = float(htf["ema21"])
    htf_ema50 = float(htf["ema50"])

    atr_pct = float(last["atr_pct"])
    distance_from_ema21 = (price - ema21) / ema21 * 100

    score = 0
    reasons = []
    late_penalty = 0

    if price > ema9 > ema21:
        score += 18
        reasons.append("prezzo sopra EMA9/EMA21")

    if ema21 > ema50:
        score += 12
        reasons.append("trend breve sopra EMA50")

    if htf_price > htf_ema21 > htf_ema50:
        score += 18
        reasons.append("trend 1H rialzista")

    if macd_hist > 0 and macd_hist > macd_hist_prev:
        score += 14
        reasons.append("MACD in accelerazione")

    if 48 <= rsi <= 66:
        score += 12
        reasons.append("RSI in zona ingresso")
    elif 66 < rsi <= 72:
        score += 4
        reasons.append("RSI forte ma già alto")
    elif rsi > 75:
        late_penalty += 18
        reasons.append("RSI troppo tirato")

    if volume_ratio >= 1.2:
        score += clamp((volume_ratio - 1) * 18, 0, 16)
        reasons.append("volume sopra media")

    if momentum_15m > 0 and momentum_45m > 0:
        score += 10
        reasons.append("momentum intraday positivo")

    if momentum_2h > 0:
        score += 6
        reasons.append("spinta 2H positiva")

    if price > float(last["high20_prev"]):
        score += 8
        reasons.append("rottura massimi recenti")

    # Filtro anti-ritardo: evita quando ha già corso troppo
    if distance_from_ema21 > max(2.5, atr_pct * 1.3):
        late_penalty += 16
        reasons.append("prezzo già lontano da EMA21")

    if momentum_2h > 4:
        late_penalty += 14
        reasons.append("movimento 2H già esteso")

    final_score = clamp(score - late_penalty, 0, 100)

    return {
        "direction": "LONG",
        "score": final_score,
        "price": price,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "momentum_15m": momentum_15m,
        "momentum_45m": momentum_45m,
        "momentum_2h": momentum_2h,
        "distance_ema21": distance_from_ema21,
        "atr_pct": atr_pct,
        "reasons": reasons
    }


def score_short(df15, df60):
    last = df15.iloc[-1]
    prev = df15.iloc[-2]
    htf = df60.iloc[-1]

    price = float(last["Close"])
    ema9 = float(last["ema9"])
    ema21 = float(last["ema21"])
    ema50 = float(last["ema50"])

    rsi = float(last["rsi"])
    volume_ratio = float(last["volume_ratio"])
    macd_hist = float(last["macd_hist"])
    macd_hist_prev = float(prev["macd_hist"])

    momentum_15m = pct_change(df15["Close"], 1)
    momentum_45m = pct_change(df15["Close"], 3)
    momentum_2h = pct_change(df15["Close"], 8)

    htf_price = float(htf["Close"])
    htf_ema21 = float(htf["ema21"])
    htf_ema50 = float(htf["ema50"])

    atr_pct = float(last["atr_pct"])
    distance_from_ema21 = (price - ema21) / ema21 * 100

    score = 0
    reasons = []
    late_penalty = 0

    if price < ema9 < ema21:
        score += 18
        reasons.append("prezzo sotto EMA9/EMA21")

    if ema21 < ema50:
        score += 12
        reasons.append("trend breve sotto EMA50")

    if htf_price < htf_ema21 < htf_ema50:
        score += 18
        reasons.append("trend 1H ribassista")

    if macd_hist < 0 and macd_hist < macd_hist_prev:
        score += 14
        reasons.append("MACD ribassista in accelerazione")

    if 34 <= rsi <= 52:
        score += 12
        reasons.append("RSI in zona short")
    elif 28 <= rsi < 34:
        score += 4
        reasons.append("RSI debole ma già basso")
    elif rsi < 25:
        late_penalty += 18
        reasons.append("RSI troppo scarico")

    if volume_ratio >= 1.2:
        score += clamp((volume_ratio - 1) * 18, 0, 16)
        reasons.append("volume sopra media")

    if momentum_15m < 0 and momentum_45m < 0:
        score += 10
        reasons.append("momentum intraday negativo")

    if momentum_2h < 0:
        score += 6
        reasons.append("spinta 2H negativa")

    if price < float(last["low20_prev"]):
        score += 8
        reasons.append("rottura minimi recenti")

    # Filtro anti-ritardo
    if abs(distance_from_ema21) > max(2.5, atr_pct * 1.3):
        late_penalty += 16
        reasons.append("prezzo già lontano da EMA21")

    if momentum_2h < -4:
        late_penalty += 14
        reasons.append("movimento 2H già esteso")

    final_score = clamp(score - late_penalty, 0, 100)

    return {
        "direction": "RIBASSO",
        "score": final_score,
        "price": price,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "momentum_15m": momentum_15m,
        "momentum_45m": momentum_45m,
        "momentum_2h": momentum_2h,
        "distance_ema21": distance_from_ema21,
        "atr_pct": atr_pct,
        "reasons": reasons
    }


def analyze_trend_signal(ticker):
    ticker = clean_ticker(ticker)

    data15 = download_ohlcv(ticker, period="30d", interval="15m")
    data60 = download_ohlcv(ticker, period="60d", interval="1h")

    if data15 is None or data60 is None:
        return None

    try:
        df15 = add_indicators(data15)
        df60 = add_indicators(data60)

        if len(df15) < 80 or len(df60) < 80:
            return None

        long_result = score_long(df15, df60)
        short_result = score_short(df15, df60)

        best = long_result if long_result["score"] >= short_result["score"] else short_result
        best["ticker"] = ticker

        if best["score"] >= 88:
            best["quality"] = "FORTISSIMO"
        elif best["score"] >= 78:
            best["quality"] = "FORTE"
        elif best["score"] >= 68:
            best["quality"] = "INTERESSANTE"
        else:
            best["quality"] = "DEBOLE"

        return best

    except Exception as err:
        logging.error("Errore analisi segnale %s: %s", ticker, err)
        return None


def format_signal(signal, rank=None):
    direction_icon = "🟢" if signal["direction"] == "LONG" else "🔴"
    rank_text = f"#{rank} " if rank else ""

    reasons = signal.get("reasons", [])
    reasons_text = "\n".join([f"- {e(r)}" for r in reasons[:5]])

    msg = f"""
{direction_icon} <b>{rank_text}{e(signal["ticker"])} — {e(signal["direction"])}</b>

Qualità: <b>{e(signal["quality"])}</b>
Score: <b>{signal["score"]:.1f}/100</b>
Prezzo: <b>{signal["price"]:.2f}</b>

Momentum 15m: {signal["momentum_15m"]:.2f}%
Momentum 45m: {signal["momentum_45m"]:.2f}%
Momentum 2H: {signal["momentum_2h"]:.2f}%

RSI: {signal["rsi"]:.1f}
Volume: {signal["volume_ratio"]:.2f}x
Distanza EMA21: {signal["distance_ema21"]:.2f}%
ATR: {signal["atr_pct"]:.2f}%

<b>Perché:</b>
{reasons_text}
"""
    return msg


def scan_market(send_only_best=False, manual=True):
    results = []

    for ticker in ASSETS:
        signal = analyze_trend_signal(ticker)

        if signal:
            results.append(signal)

    results.sort(key=lambda x: x["score"], reverse=True)

    valid = [x for x in results if x["score"] >= MIN_SIGNAL_SCORE]

    if not valid:
        if manual:
            send("Nessun segnale abbastanza forte adesso. Meglio aspettare.", main_keyboard())
        return []

    if send_only_best:
        selected = valid[:1]
    else:
        selected = valid[:MAX_SIGNALS_PER_SCAN]

    msg = "<b>🎯 SEGNALI DIREZIONALI AD ALTA QUALITÀ</b>\n"
    msg += "Pochi alert, solo setup forti.\n\n"

    for i, signal in enumerate(selected, start=1):
        msg += format_signal(signal, rank=i)
        msg += "\n---------\n"

    send(msg, main_keyboard())
    return selected


def auto_scan_market():
    state = load_state()

    if not state.get("auto_scan", True):
        return

    results = []

    for ticker in ASSETS:
        signal = analyze_trend_signal(ticker)

        if not signal:
            continue

        if signal["score"] < MIN_SIGNAL_SCORE:
            continue

        results.append(signal)

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:MAX_SIGNALS_PER_SCAN]

    if not results:
        return

    current_time = now_ts()
    last_signals = state.get("last_signals", {})

    fresh = []

    for signal in results:
        key = f'{signal["ticker"]}:{signal["direction"]}'
        last_time = int(last_signals.get(key, 0))

        if current_time - last_time >= SIGNAL_COOLDOWN:
            fresh.append(signal)
            last_signals[key] = current_time

    if not fresh:
        return

    state["last_signals"] = last_signals
    save_state(state)

    msg = "<b>🚨 NUOVO SEGNALE FORTE</b>\n\n"

    for i, signal in enumerate(fresh, start=1):
        msg += format_signal(signal, rank=i)
        msg += "\n---------\n"

    send(msg, main_keyboard())


def analyze_manual(ticker):
    signal = analyze_trend_signal(ticker)

    if not signal:
        send(f"Analisi non disponibile per {e(ticker)}.", main_keyboard())
        return

    msg = "<b>📊 ANALISI DIREZIONALE</b>\n"
    msg += format_signal(signal)

    if signal["score"] >= MIN_SIGNAL_SCORE:
        msg += "\n<b>Lettura:</b> segnale operativo valido, ma attendi sempre conferma del tuo piano."
    elif signal["score"] >= 65:
        msg += "\n<b>Lettura:</b> interessante, ma non ancora abbastanza forte."
    else:
        msg += "\n<b>Lettura:</b> debole. Meglio non forzare."

    send(msg, main_keyboard())


# ============================================================
# PORTFOLIO MONITOR
# ============================================================

def init_position(ticker, entry, market_price):
    return {
        "ticker": ticker,
        "entry": float(entry),
        "created_at": now_ts(),
        "last_price": float(market_price),
        "pnl": pnl_percent(market_price, entry),
        "last_profit_band": 0,
        "last_loss_band": 0,
        "snooze_until": 0
    }


def buy_position(ticker, entry=None):
    ticker = clean_ticker(ticker)

    price = get_price(ticker)

    if price is None:
        send(f"Prezzo non disponibile per {e(ticker)}.", main_keyboard())
        return

    final_entry = entry if entry is not None else price

    if final_entry <= 0:
        send("Prezzo non valido.", main_keyboard())
        return

    positions = load_positions()
    positions[ticker] = init_position(ticker, final_entry, price)
    save_positions(positions)

    msg = f"""
✅ <b>{e(ticker)} acquistato/registrato</b>

Entry: <b>{final_entry:.2f}</b>
Prezzo attuale: <b>{price:.2f}</b>

Da ora ti avviso ogni:
+1%, +2%, +3%...
-1%, -2%, -3%...

Se scende ti chiedo se vuoi uscire o restare.
"""
    send(msg, main_keyboard())


def exit_position(ticker):
    ticker = clean_ticker(ticker)
    positions = load_positions()

    if ticker not in positions:
        send(f"{e(ticker)} non è nel portafoglio.", main_keyboard())
        return

    pos = positions[ticker]
    entry = safe_float(pos.get("entry"))
    price = get_price(ticker)

    if price is not None and entry:
        pnl = pnl_percent(price, entry)
    else:
        pnl = safe_float(pos.get("pnl")) or 0.0

    del positions[ticker]
    save_positions(positions)

    msg = f"""
🚪 <b>{e(ticker)} rimosso dal monitoraggio</b>

Ultimo PnL stimato: <b>{pnl:.2f}%</b>

Nota: il bot non vende realmente sul broker.
"""
    send(msg, main_keyboard())


def stay_position(ticker):
    ticker = clean_ticker(ticker)
    positions = load_positions()

    if ticker not in positions:
        send(f"{e(ticker)} non è nel portafoglio.", main_keyboard())
        return

    positions[ticker]["snooze_until"] = now_ts() + POSITION_SNOOZE_SECONDS
    save_positions(positions)

    send(
        f"🛡 Ok, resto dentro su <b>{e(ticker)}</b>.\n"
        f"Sospendo gli avvisi di rischio per {POSITION_SNOOZE_SECONDS // 60} minuti.",
        main_keyboard()
    )


def monitor_positions():
    positions = load_positions()

    if not positions:
        return

    current_time = now_ts()
    changed = False

    for ticker, pos in list(positions.items()):
        ticker = clean_ticker(ticker)

        entry = safe_float(pos.get("entry"))

        if entry is None or entry <= 0:
            continue

        price = get_price(ticker)

        if price is None:
            continue

        current_pnl = pnl_percent(price, entry)

        pos["last_price"] = price
        pos["pnl"] = current_pnl
        pos["last_checked_at"] = current_time

        profit_band = int(current_pnl // PROFIT_STEP) if current_pnl >= PROFIT_STEP else 0
        loss_band = int(abs(current_pnl) // LOSS_STEP) if current_pnl <= -LOSS_STEP else 0

        last_profit_band = int(pos.get("last_profit_band", 0))
        last_loss_band = int(pos.get("last_loss_band", 0))

        if profit_band > last_profit_band:
            pos["last_profit_band"] = profit_band
            changed = True

            msg = f"""
🟢 <b>{e(ticker)} sale</b>

Entry: <b>{entry:.2f}</b>
Prezzo: <b>{price:.2f}</b>
PnL: <b>+{current_pnl:.2f}%</b>

Hai superato la soglia +{profit_band}%.
"""
            send(msg, position_alert_keyboard(ticker))

        if loss_band > last_loss_band:
            pos["last_loss_band"] = loss_band
            changed = True

            snooze_until = int(pos.get("snooze_until", 0))

            if current_time >= snooze_until:
                msg = f"""
🔴 <b>{e(ticker)} scende</b>

Entry: <b>{entry:.2f}</b>
Prezzo: <b>{price:.2f}</b>
PnL: <b>{current_pnl:.2f}%</b>

Hai superato la soglia -{loss_band}%.
Vuoi uscire o restare dentro?
"""
                send(msg, position_alert_keyboard(ticker))

        positions[ticker] = pos

    if changed:
        save_positions(positions)


def show_positions():
    positions = load_positions()

    if not positions:
        send("Nessuna posizione aperta.", main_keyboard())
        return

    msg = "<b>💼 PORTAFOGLIO</b>\n\n"

    for ticker, pos in positions.items():
        ticker = clean_ticker(ticker)
        entry = safe_float(pos.get("entry"))
        price = get_price(ticker)

        if price is not None and entry:
            current_pnl = pnl_percent(price, entry)
            pos["last_price"] = price
            pos["pnl"] = current_pnl

            icon = "🟢" if current_pnl >= 0 else "🔴"

            msg += f"""
<b>{e(ticker)}</b>
Entry: {entry:.2f}
Prezzo: {price:.2f}
PnL: {icon} {current_pnl:.2f}%

---------
"""
        else:
            msg += f"""
<b>{e(ticker)}</b>
Entry: {entry}
Prezzo non disponibile

---------
"""

    save_positions(positions)
    send(msg, position_keyboard())


# ============================================================
# CALLBACKS
# ============================================================

def handle_callback(callback):
    if not isinstance(callback, dict):
        return

    callback_id = callback.get("id")
    data = callback.get("data", "")

    answer_callback(callback_id)

    if not data:
        return

    if data == "MENU":
        show_menu()

    elif data == "HELP":
        show_help()

    elif data == "STATUS":
        show_status()

    elif data == "BEST_NOW":
        scan_market(send_only_best=True, manual=True)

    elif data == "SCAN_NOW":
        scan_market(send_only_best=False, manual=True)

    elif data == "ANALYZE_MENU":
        send("Scegli asset da analizzare:", assets_keyboard("ANALYZE"))

    elif data == "POSITIONS":
        show_positions()

    elif data == "SCAN_ON":
        state = load_state()
        state["auto_scan"] = True
        save_state(state)
        send("🟢 Auto scan attivo.", main_keyboard())

    elif data == "SCAN_OFF":
        state = load_state()
        state["auto_scan"] = False
        save_state(state)
        send("🔴 Auto scan disattivato.", main_keyboard())

    elif data.startswith("ANALYZE:"):
        ticker = data.split(":", 1)[1]
        analyze_manual(ticker)

    elif data.startswith("EXIT:"):
        ticker = data.split(":", 1)[1]
        exit_position(ticker)

    elif data.startswith("STAY:"):
        ticker = data.split(":", 1)[1]
        stay_position(ticker)

    else:
        send("Comando non riconosciuto.", main_keyboard())


# ============================================================
# TEXT COMMANDS
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

    if upper == "MENU":
        show_menu()

    elif upper in ["HELP", "COMANDI"]:
        show_help()

    elif upper in ["STATUS", "STATO"]:
        show_status()

    elif upper == "BEST":
        scan_market(send_only_best=True, manual=True)

    elif upper == "SCAN":
        scan_market(send_only_best=False, manual=True)

    elif upper == "AUTO ON":
        state = load_state()
        state["auto_scan"] = True
        save_state(state)
        send("🟢 Auto scan attivo.", main_keyboard())

    elif upper == "AUTO OFF":
        state = load_state()
        state["auto_scan"] = False
        save_state(state)
        send("🔴 Auto scan disattivato.", main_keyboard())

    elif upper == "POSITIONS":
        show_positions()

    elif cmd == "ANALYZE":
        if len(parts) < 2:
            send("Formato corretto: ANALYZE TICKER", main_keyboard())
            return

        analyze_manual(parts[1])

    elif cmd == "BUY":
        if len(parts) < 2:
            send("Formato corretto: BUY TICKER oppure BUY TICKER prezzo", main_keyboard())
            return

        ticker = parts[1]
        entry = None

        if len(parts) >= 3:
            entry = safe_float(parts[2])

            if entry is None:
                send("Prezzo non valido.", main_keyboard())
                return

        buy_position(ticker, entry)

    elif cmd in ["SELL", "EXIT", "ESCI"]:
        if len(parts) < 2:
            send("Formato corretto: SELL TICKER", main_keyboard())
            return

        exit_position(parts[1])

    elif cmd in ["STAY", "RESTO"]:
        if len(parts) < 2:
            send("Formato corretto: STAY TICKER", main_keyboard())
            return

        stay_position(parts[1])

    else:
        send("Comando non riconosciuto. Scrivi MENU.", main_keyboard())


def handle_updates(offset):
    data = get_updates(offset)

    if not isinstance(data, dict):
        return offset

    updates = data.get("result", [])

    if not isinstance(updates, list):
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

            if text:
                handle_text_command(text)

        except Exception as err:
            logging.exception("Errore update Telegram: %s", err)

    return offset


# ============================================================
# MAIN
# ============================================================

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Manca TELEGRAM_TOKEN")

    if not CHAT_ID:
        raise RuntimeError("Manca CHAT_ID")

    send("🤖 <b>BOT TREND ANTICIPATORE ATTIVO</b>", main_keyboard())

    offset = None
    last_scan = 0

    while True:
        try:
            offset = handle_updates(offset)
        except Exception as err:
            logging.exception("Errore handle_updates: %s", err)

        try:
            monitor_positions()
        except Exception as err:
            logging.exception("Errore monitor_positions: %s", err)

        try:
            current_time = time.time()

            if current_time - last_scan >= SCAN_INTERVAL:
                auto_scan_market()
                last_scan = current_time

        except Exception as err:
            logging.exception("Errore auto_scan_market: %s", err)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()