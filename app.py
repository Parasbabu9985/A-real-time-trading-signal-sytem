import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from streamlit_autorefresh import st_autorefresh
from SmartApi import SmartConnect
import pyotp
import requests
import plotly.graph_objects as go

# ===================== PAGE CONFIG =====================
st.set_page_config(page_title="Trading Dashboard", layout="wide")

# ===================== AUTO REFRESH =====================
st_autorefresh(interval=120000, key="refresh")

# ===================== SECRETS (IMPORTANT) =====================
try:
    API_KEY = st.secrets["api_key"]
    CLIENT_ID = st.secrets["client_id"]
    CLIENT_PASSWORD = st.secrets["password"]
    TOTP_SECRET = st.secrets["totp_secret"]


    BOT_TOKEN = st.secrets.get("BOT_TOKEN", "")
    CHAT_ID = st.secrets.get("CHAT_ID", "")

except Exception:
    st.error("❌ Secrets not configured properly")
    st.stop()

# ===================== TITLE =====================
st.title("📊 Smart Trading Dashboard")

# ===================== SIDEBAR =====================
st.sidebar.header("⚙️ Settings")

symbol = st.sidebar.selectbox("Select Index", ["NIFTY", "BANKNIFTY"])
interval_label = st.sidebar.selectbox(
    "Interval",
    ["1 Minute", "5 Minute", "15 Minute"],
    index=1
)

INTERVAL_MAP = {
    "1 Minute": "ONE_MINUTE",
    "5 Minute": "FIVE_MINUTE",
    "15 Minute": "FIFTEEN_MINUTE",
}

interval = INTERVAL_MAP[interval_label]

st.sidebar.info("EMA + RSI Strategy")

# ===================== DATE =====================
default_start = (datetime.now() - timedelta(days=1)).date()
default_end = datetime.now().date()

start_date = st.sidebar.date_input("From", default_start)
end_date = st.sidebar.date_input("To", default_end)

market_open = time(9, 15)
market_close = time(15, 30)

from_dt = datetime.combine(start_date, market_open)
to_dt = datetime.combine(end_date, market_close)

fromdate = from_dt.strftime("%Y-%m-%d %H:%M")
todate = to_dt.strftime("%Y-%m-%d %H:%M")

# ===================== LOGIN =====================
try:
    obj = SmartConnect(api_key=API_KEY)

    totp = pyotp.TOTP(TOTP_SECRET.strip()).now()

    data = obj.generateSession(CLIENT_ID, CLIENT_PASSWORD, totp)

    if not data or "data" not in data:
        st.error(f"Login failed: {data}")
        st.stop()

    st.sidebar.success("✅ Logged in")

except Exception as e:
    st.error(f"Login failed: {e}")
    st.stop()

# ===================== SYMBOL =====================
SYMBOL_TOKENS = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009",
}
symbol_token = SYMBOL_TOKENS[symbol]

# ===================== FETCH DATA =====================
def fetch_candles():
    payload = {
        "exchange": "NSE",
        "symboltoken": symbol_token,
        "interval": interval,
        "fromdate": fromdate,
        "todate": todate,
    }

    resp = obj.getCandleData(payload)

    # 🔍 DEBUG (very important)
    st.write("API Response:", resp)

    # ❌ No response
    if not resp:
        st.error("❌ No response from API")
        return pd.DataFrame()

    # ❌ data key missing
    if "data" not in resp:
        st.error(f"❌ 'data' key missing: {resp}")
        return pd.DataFrame()

    data = resp["data"]

    # ❌ data is None
    if data is None:
        st.error("❌ Data is None (login/session issue)")
        return pd.DataFrame()

    # ❌ data is not list
    if not isinstance(data, list):
        st.error(f"❌ Data not list: {data}")
        return pd.DataFrame()

    # ❌ empty data
    if len(data) == 0:
        st.warning("⚠️ No candle data (market closed or invalid time)")
        return pd.DataFrame()

    # ✅ Safe DataFrame
    try:
        df = pd.DataFrame(
            data,
            columns=["datetime", "open", "high", "low", "close", "volume"]
        )
    except Exception as e:
        st.error(f"❌ DataFrame error: {e}")
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df.dropna(inplace=True)
    return df

# ===================== INDICATORS =====================
df["EMA20"] = df["close"].ewm(span=20).mean()
df["EMA50"] = df["close"].ewm(span=50).mean()

delta = df["close"].diff()
gain = (delta.where(delta > 0, 0)).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss
df["RSI"] = 100 - (100 / (1 + rs))

last = df.iloc[-1]

price = last["close"]
ema20 = last["EMA20"]
ema50 = last["EMA50"]
rsi = last["RSI"]

# ===================== SIGNAL =====================
signal = "HOLD"

if ema20 > ema50 and rsi > 50:
    signal = "BUY"
elif ema20 < ema50 and rsi < 50:
    signal = "SELL"

# ===================== TRADE =====================
entry = price

if signal == "BUY":
    sl = entry * 0.98
    target = entry * 1.03
elif signal == "SELL":
    sl = entry * 1.02
    target = entry * 0.97
else:
    sl, target = None, None

# ===================== SIGNAL DISPLAY =====================
if signal == "BUY":
    st.success(f"🟢 BUY SIGNAL at {round(price,2)}")
elif signal == "SELL":
    st.error(f"🔴 SELL SIGNAL at {round(price,2)}")
else:
    st.warning("🟡 HOLD")

# ===================== METRICS =====================
col1, col2, col3, col4 = st.columns(4)

col1.metric("Signal", signal)
col2.metric("Price", round(price,2))
col3.metric("RSI", round(rsi,2))
col4.metric("Trend", "Bullish" if ema20 > ema50 else "Bearish")

# ===================== TRADE PANEL =====================
st.subheader("📌 Trade Setup")

c1, c2, c3 = st.columns(3)

c1.metric("Entry", round(entry,2))

if sl:
    c2.metric("Stop Loss", round(sl,2))
    c3.metric("Target", round(target,2))
else:
    c2.write("-")
    c3.write("-")

# ===================== CHART =====================
st.subheader("📈 Price Chart")

fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df.index,
    open=df['open'],
    high=df['high'],
    low=df['low'],
    close=df['close']
))

fig.add_trace(go.Scatter(x=df.index, y=df["EMA20"], name="EMA20"))
fig.add_trace(go.Scatter(x=df.index, y=df["EMA50"], name="EMA50"))

fig.update_layout(template="plotly_dark")

st.plotly_chart(fig, use_container_width=True)

# ===================== RSI =====================
st.subheader("📉 RSI")
st.line_chart(df["RSI"])

# ===================== VOLUME =====================
st.subheader("📊 Volume")
st.bar_chart(df["volume"])

# ===================== TELEGRAM =====================
def send_telegram(msg):
    if BOT_TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.get(url, params={"chat_id": CHAT_ID, "text": msg})

if st.button("📲 Send Signal"):
    send_telegram(f"{symbol} {signal} @ {price}")
