
from fastapi import FastAPI
import uvicorn
import threading
import time
import requests
import hmac
import hashlib
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from ta.trend import EMAIndicator, ADXIndicator
from delta_rest_client import DeltaRestClient
import os
from datetime import datetime, timezone
# === USER CONFIGURATION ===
API_KEY = os.getenv("DELTA_API_KEY") or 'RzC8BXl98EeFh3i1pOwRAgjqQpLLII'
API_SECRET = os.getenv("DELTA_API_SECRET") or 'yP1encFFWbrPkm5u58ak3qhHD3Eupv9fP5Rf9AmPmi60RHTreYuBdNv1a2bo'
BASE_URL = 'https://cdn-ind.testnet.deltaex.org'
USD_ASSET_ID = 3
PRODUCT_ID = 1699

# === TRADE LOG ===
def setup_trade_log():
    try:
        with open("trades_log.txt", "a") as f:
            f.write(f"\n--- New Session Started: {datetime.now()} ---\n")
        print("✅ Trade log file ready.")
    except Exception as e:
        print(f"❌ Failed to setup trade log: {e}")

# === AUTHENTICATION ===
def authenticate():
    try:
        client = DeltaRestClient(base_url=BASE_URL, api_key=API_KEY, api_secret=API_SECRET)
        print("✅ Authentication successful.")
        return client
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return None

# === FETCH USD BALANCE ===
def get_usd_balance(client):
    try:
        wallet = client.get_balances(asset_id=USD_ASSET_ID)
        if wallet:
            balance = float(wallet["available_balance"])
            print(f"💰 USD Balance: {balance:.4f} USD")
            return balance
        else:
            print("❌ USD wallet not found.")
            return None
    except Exception as e:
        print(f"❌ Failed to fetch balance: {e}")
        return None

# === STRATEGY ===
def fetch_eth_candles(symbol="ETH/USDT", timeframe="15m", limit=100):
    try:
        print("📅 Fetching 15m candles from Binance...")
        ohlcv = ccxt.binance().fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"❌ Failed to fetch candles: {e}")
        return None

def apply_strategy(df):
    try:
        df["ema21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
        df["vol_sma30"] = df["volume"].rolling(window=30).mean()
        adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx.adx()
        return df
    except Exception as e:
        print(f"❌ Indicator error: {e}")
        return df

def get_trade_signal(df):
    last = df.iloc[-1]
    print("\n📊 Strategy Check (Latest Candle):")
    print(f"Price: {last['close']:.2f}, EMA21: {last['ema21']:.2f}")
    print(f"Volume: {last['volume']:.2f}, Vol SMA30: {last['vol_sma30']:.2f}")
    print(f"ADX: {last['adx']:.2f} > 20")

    if last["close"] > last["ema21"] and last["volume"] > last["vol_sma30"] and last["adx"] > 20:
        return "buy"
    elif last["close"] < last["ema21"] and last["volume"] > last["vol_sma30"] and last["adx"] > 20:
        return "sell"
    return None

def cancel_unfilled_orders(client, product_id):
    try:
        print("🔍 Checking for unfilled live orders...")
        open_orders = client.get_live_orders(query={"product_id": product_id})
        for order in open_orders:
            client.cancel_order(product_id=product_id, order_id=order['id'])
            print(f"❌ Cancelled unfilled order ID: {order['id']}")
    except Exception as e:
        print(f"❌ Error cancelling orders: {e}")

def has_open_position(client, product_id):
    try:
        pos = client.get_position(product_id=product_id)
        return pos and float(pos.get("size", 0)) > 0
    except Exception as e:
        print(f"❌ Error checking position: {e}")
        return False

def place_order(client, capital, entry_price, side, product_id):
    try:
        RISK_PERCENT = 0.10
        SL_PERCENT = 0.02
        TP_MULTIPLIER = 7
        LEVERAGE = 50

        risk_amount = capital * RISK_PERCENT
        sl_usd = capital * SL_PERCENT
        tp_usd = sl_usd * TP_MULTIPLIER
        lot_size = round(risk_amount / (sl_usd * LEVERAGE), 3)

        if lot_size <= 0:
            print("❌ Lot size too small. Skipping order.")
            return

        sl_price = round(entry_price - sl_usd, 2) if side == "buy" else round(entry_price + sl_usd, 2)
        tp_price = round(entry_price + tp_usd, 2) if side == "buy" else round(entry_price - tp_usd, 2)

        print(f"\n🛒 Placing LIMIT {side.upper()} order: Entry {entry_price}, SL {sl_price}, TP {tp_price}, Lot {lot_size}")

        client.place_order(
            product_id=product_id,
            size=lot_size,
            side=side,
            limit_price=entry_price,
            order_type='limit_order',
            post_only='true'
        )

        with open("trades_log.txt", "a") as f:
            f.write(f"{datetime.now()} | ORDER PLACED | {side.upper()} | Entry: {entry_price} | SL: {sl_price} | TP: {tp_price} | Lot: {lot_size}\n")

        monitor_position_with_trailing_sl(client, product_id, entry_price, side, tp_usd)

    except Exception as e:
        print(f"❌ Failed to place order: {e}")

def monitor_position_with_trailing_sl(client, product_id, entry_price, side, tp_usd):
    try:
        halfway = entry_price + tp_usd / 2 if side == "buy" else entry_price - tp_usd / 2
        trail_distance = tp_usd / 2
        moved_to_be = False

        while True:
            pos = client.get_position(product_id=product_id)
            if not pos or float(pos["size"]) == 0:
                print("🚪 Position closed.")
                break

            current_price = float(pos["mark_price"])
            size = float(pos["size"])

            if not moved_to_be:
                if (side == "buy" and current_price >= halfway) or (side == "sell" and current_price <= halfway):
                    be_sl = entry_price
                    client.place_stop_order(
                        product_id=product_id,
                        size=size,
                        side="sell" if side == "buy" else "buy",
                        stop_price=be_sl,
                        limit_price=be_sl,
                        order_type='limit_order'
                    )
                    print(f"🔄 SL moved to BE at {be_sl}")
                    moved_to_be = True
            else:
                if side == "buy":
                    new_sl = round(current_price - trail_distance, 2)
                    client.place_stop_order(product_id, size, "sell", new_sl, new_sl, 'limit_order')
                else:
                    new_sl = round(current_price + trail_distance, 2)
                    client.place_stop_order(product_id, size, "buy", new_sl, new_sl, 'limit_order')
            time.sleep(15)
    except Exception as e:
        print(f"❌ Error in SL monitor: {e}")

def wait_until_next_15min():
    now = datetime.now()
    wait_seconds = ((15 - now.minute % 15) * 60) - now.second
    print(f"🕒 Waiting {wait_seconds}s until next 15m candle...")
    time.sleep(wait_seconds)

def run_bot():
    print("🤖 Bot loop started...")
    client = authenticate()
    if not client:
        print("❌ Client authentication failed.")
        return

    setup_trade_log()

    while True:
        try:
            balance = get_usd_balance(client)
            if not balance:
                print("⚠️ Balance fetch failed. Retrying...")
                time.sleep(60)
                continue

            wait_until_next_15min()
            cancel_unfilled_orders(client, PRODUCT_ID)

            if has_open_position(client, PRODUCT_ID):
                print("⏸️ Skipping: already in position.")
                continue

            df = fetch_eth_candles()
            df = apply_strategy(df)
            signal = get_trade_signal(df)

            if signal:
                entry_price = float(df.iloc[-1]['close'])
                place_order(client, balance, entry_price, signal, PRODUCT_ID)
            else:
                print("❌ No trade this candle.")
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(30)

# === FASTAPI SERVER ===
app = FastAPI()

@app.get("/")
def root():
    return {
        "status": "Bot is running",
        "time": datetime.now(timezone.utc).isoformat()
    }


# === START ===
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    uvicorn.run(app, host="0.0.0.0", port=10000)
