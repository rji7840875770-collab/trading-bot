import os
import time
import pyotp
import pandas as pd
import ta
import requests as req
from SmartApi import SmartConnect
from datetime import datetime, timedelta

# ─── CREDENTIALS ────────────────────────────────
API_KEY          = os.environ.get("API_KEY")
CLIENT_ID        = os.environ.get("CLIENT_ID")
PASSWORD         = os.environ.get("PASSWORD")
TOTP_KEY         = os.environ.get("TOTP_KEY")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ─── CONFIG ─────────────────────────────────────
SYMBOL     = "SBIN"
EXCHANGE   = "NSE"
TOKEN      = "3045"
QUANTITY   = 1
STOP_LOSS  = 0.003
TARGET     = 0.006
MAX_TRADES = 5
CAPITAL    = 1000

# ─── TELEGRAM ───────────────────────────────────
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        req.post(url, data={
            "chat_id"    : TELEGRAM_CHAT_ID,
            "text"       : message,
            "parse_mode" : "HTML"
        })
        print(f"Telegram sent: {message}")
    except Exception as e:
        print(f"Telegram error: {e}")

# ─── LOGIN ──────────────────────────────────────
def login():
    obj  = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_KEY).now()
    data = obj.generateSession(CLIENT_ID, PASSWORD, totp)
    print(f"Logged in: {data['data']['name']}")
    return obj

# ─── FETCH CANDLES ───────────────────────────────
def get_candles(obj, interval="FIVE_MINUTE"):
    time.sleep(2)
    now     = datetime.now()
    from_dt = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    to_dt   = now.strftime("%Y-%m-%d %H:%M")
    try:
        hist = obj.getCandleData({
            "exchange"    : EXCHANGE,
            "symboltoken" : TOKEN,
            "interval"    : interval,
            "fromdate"    : from_dt,
            "todate"      : to_dt
        })
        if not hist or not hist.get('data') or len(hist['data']) == 0:
            print("No candle data returned. Market may be closed.")
            return None
        df = pd.DataFrame(hist['data'],
             columns=['time','open','high','low','close','vol'])
        df['close'] = df['close'].astype(float)
        print(f"Fetched {len(df)} candles. Latest close: {df['close'].iloc[-1]}")
        return df
    except Exception as e:
        print(f"API error: {e}")
        print("Waiting 60 seconds before retry...")
        time.sleep(60)
        return None

# ─── STRATEGY ───────────────────────────────────
def get_signal(df):
    if df is None or len(df) < 15:
        print(f"Not enough candles (got {len(df) if df is not None else 0})")
        return "WAIT", None
    df['ema9']  = ta.trend.ema_indicator(df['close'], window=9)
    df['ema21'] = ta.trend.ema_indicator(df['close'], window=21)
    df['rsi']   = ta.momentum.rsi(df['close'], window=14)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    cross_up   = prev['ema9'] <= prev['ema21'] and last['ema9'] > last['ema21']
    cross_down = prev['ema9'] >= prev['ema21'] and last['ema9'] < last['ema21']
    print(f"EMA9: {last['ema9']:.2f} | EMA21: {last['ema21']:.2f} | RSI: {last['rsi']:.2f}")
    if cross_up   and last['rsi'] > 50: return "BUY",  last
    if cross_down and last['rsi'] < 50: return "SELL", last
    return "WAIT", last

# ─── PLACE ORDER ────────────────────────────────
def place_order(obj, side, price):
    try:
        order_params = {
            "variety"         : "NORMAL",
            "tradingsymbol"   : SYMBOL,
            "symboltoken"     : TOKEN,
            "transactiontype" : side,
            "exchange"        : EXCHANGE,
            "ordertype"       : "MARKET",
            "producttype"     : "INTRADAY",
            "duration"        : "DAY",
            "quantity"        : QUANTITY
        }
        resp = obj.placeOrder(order_params)
        print(f"Order placed: {side} @ {price} | ID: {resp}")
        return resp
    except Exception as e:
        print(f"Order error: {e}")
        send_telegram(f"⚠️ <b>Order Failed</b>\n{side} @ ₹{price}\nError: {e}")
        return None

# ─── MAIN LOOP ──────────────────────────────────
def run():
    obj          = login()
    trades_today = 0
    position     = "NONE"
    entry_price  = 0
    send_telegram("🤖 <b>Trading Bot Started</b>\nStock: SBIN\nScanning every 5 minutes...\nMarket opens at 9:15 AM IST")
    print("Bot started. Scanning every 5 minutes...")
    time.sleep(10)
    while True:
        try:
            now          = datetime.now()
            market_open  = now.replace(hour=9,  minute=15, second=0)
            market_close = now.replace(hour=15, minute=30, second=0)
            if not (market_open <= now <= market_close) or now.weekday() > 4:
                print("Market closed. Waiting 15 minutes...")
                time.sleep(900)
                continue
            if trades_today >= MAX_TRADES:
                print("Max trades reached. Stopping for today.")
                send_telegram(f"⛔ <b>Bot Stopped</b>\nMax {MAX_TRADES} trades reached for today.")
                time.sleep(900)
                continue
            df             = get_candles(obj)
            signal, last   = get_signal(df)
            if last is None:
                print("Waiting 5 minutes and retrying...")
                time.sleep(300)
                continue
            price = last['close']
            if signal == "BUY" and position == "NONE":
                place_order(obj, "BUY", price)
                position    = "LONG"
                entry_price = price
                trades_today += 1
                send_telegram(f"🟢 <b>BUY Signal</b>\nStock: {SYMBOL}\nPrice: ₹{price}\nTarget: ₹{round(price*(1+TARGET),2)}\nStop Loss: ₹{round(price*(1-STOP_LOSS),2)}")
            elif position == "LONG":
                sl  = entry_price * (1 - STOP_LOSS)
                tgt = entry_price * (1 + TARGET)
                if price <= sl or price >= tgt or signal == "SELL":
                    place_order(obj, "SELL", price)
                    pnl = (price - entry_price) * QUANTITY
                    print(f"Exit @ {price} | P&L: ₹{pnl:.2f}")
                    send_telegram(f"🔴 <b>SELL Signal</b>\nStock: {SYMBOL}\nExit Price: ₹{price}\nP&L: ₹{round(pnl,2)}")
                    position = "NONE"
            time.sleep(300)
        except Exception as e:
            print(f"Error in main loop: {e}")
            print("Waiting 60 seconds before retrying...")
            time.sleep(60)
            continue

if __name__ == "__main__":
    run()
