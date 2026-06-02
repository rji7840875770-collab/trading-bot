# Angel One SmartAPI Scalping Bot
# Strategy: EMA9/EMA21 crossover + RSI14 filter
# Install: pip install smartapi-python pandas ta-lib requests

from SmartApi import SmartConnect
import pyotp, time, pandas as pd
import ta

# ─── CONFIG ────────────────────────────────────
API_KEY    = "UrAUG4p9"     # Angel One dashboard
CLIENT_ID  = "AACI224719"
PASSWORD   = "5270"
TOTP_KEY   = "BQLZUC7GFMEUXSZNJHWTTYXWU4"  # Enable 2FA in Angel app

SYMBOL     = "SBIN"
EXCHANGE   = "NSE"
TOKEN      = "3045"           # Nifty 50 token
QUANTITY   = 1                  # Keep at 1 with ₹1,000
STOP_LOSS  = 0.003              # 0.3% stop loss
TARGET     = 0.006              # 0.6% target (2:1 ratio)
MAX_TRADES = 5                  # Max trades per day
CAPITAL    = 1000               # Starting capital

# ─── LOGIN ──────────────────────────────────────
def login():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_KEY).now()
    data = obj.generateSession(CLIENT_ID, PASSWORD, totp)
    print(f"Logged in: {data['data']['name']}")
    return obj

# ─── FETCH CANDLES ───────────────────────────────
def get_candles(obj, interval="FIVE_MINUTE"):
    from datetime import datetime, timedelta
    now     = datetime.now()
    from_dt = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    to_dt   = now.strftime("%Y-%m-%d %H:%M")
    hist = obj.getCandleData({
        "exchange"    : EXCHANGE,
        "symboltoken" : TOKEN,
        "interval"    : interval,
        "fromdate"    : from_dt,
        "todate"      : to_dt
    })
    print(f"Raw API response: {hist}")
    if not hist or not hist.get('data') or len(hist['data']) == 0:
        print("No candle data returned. Market may be closed.")
        return None
    df = pd.DataFrame(hist['data'],
         columns=['time','open','high','low','close','vol'])
    df['close'] = df['close'].astype(float)
    print(f"Fetched {len(df)} candles. Latest close: {df['close'].iloc[-1]}")
    return df
# ─── STRATEGY ───────────────────────────────────
def get_signal(df):
    if df is None or len(df) < 15:
        print(f"Not enough candles for indicators (need 15, got {len(df) if df is not None else 0})")
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
    order_params = {
        "variety": "NORMAL", "tradingsymbol": SYMBOL,
        "symboltoken": TOKEN, "transactiontype": side,
        "exchange": EXCHANGE, "ordertype": "MARKET",
        "producttype": "INTRADAY", "duration": "DAY",
        "quantity": QUANTITY
    }
    resp = obj.placeOrder(order_params)
    print(f"Order placed: {side} @ {price} | ID: {resp}")
    return resp

# ─── MAIN LOOP ──────────────────────────────────
def run():
    obj = login()
    trades_today = 0
    position = "NONE"
    entry_price = 0
    print("Bot started. Scanning every 5 minutes...")
    while True:
        if trades_today >= MAX_TRADES:
            print("Max trades reached. Stopping for today.")
            break
            time.sleep(2)
        df = get_candles(obj)
        signal, last = get_signal(df)
        if last is None:
            print("Waiting 5 minutes and retrying...")
            time.sleep(300)
            continue
        price = last['close']
        if signal == "BUY" and position == "NONE":
            place_order(obj, "BUY", price)
            position = "LONG"
            entry_price = price
            trades_today += 1
        elif position == "LONG":
            sl  = entry_price * (1 - STOP_LOSS)
            tgt = entry_price * (1 + TARGET)
            if price <= sl or price >= tgt or signal == "SELL":
                place_order(obj, "SELL", price)
                pnl = (price - entry_price) * QUANTITY
                print(f"Exit @ {price} | P&L: ₹{pnl:.2f}")
                position = "NONE"
        time.sleep(300)

if __name__ == "__main__":
    run()