
# === ETHUSD Futures Trading Bot (Delta Exchange Demo) ===

from datetime import datetime
import ccxt
import pandas as pd
import numpy as np
import requests
import time
import hmac
import hashlib
import os
from ta.trend import EMAIndicator, ADXIndicator

# === USER CONFIGURATION ===
API_KEY = os.getenv("DELTA_API_KEY") or "replace_this_key"
API_SECRET = os.getenv("DELTA_API_SECRET") or "replace_this_secret"
BASE_URL = 'https://api.india.delta.exchange/'
USD_ASSET_ID = 14

# === FETCH USD BALANCE ===
def get_usd_balance(api_key, api_secret):
    try:
        path = "/v2/wallet/balances"
        url = BASE_URL.rstrip("/") + path
        request_time = str(int(time.time() * 1000))
        payload = request_time + "GET" + path
        signature = hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

        headers = {
            "api-key": api_key,
            "request-time": request_time,
            "signature": signature
        }

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ HTTP Error {response.status_code}: {response.text}")
            return None

        wallets = response.json().get("result", [])
        for wallet in wallets:
            if wallet["asset_symbol"] == "USD":
                balance = float(wallet["available_balance"])
                print(f"💰 USD Balance: {balance:.4f} USD")
                return balance

        print("❌ USD wallet not found.")
        return None
    except Exception as e:
        print(f"❌ Exception during balance fetch: {e}")
        return None

# === SETUP TRADE LOG FILE ===
def setup_trade_log():
    try:
        with open("trades_log.txt", "a") as f:
            f.write(f"\n--- New Session Started: {datetime.now()} ---\n")
        print("✅ Trade log file ready.")
    except Exception as e:
        print(f"❌ Failed to setup trade log: {e}")

# === FETCH ETH/USDT 15M CANDLES ===
def fetch_eth_candles(symbol="ETH/USDT", timeframe="15m", limit=100):
    exchange = ccxt.binance()
    try:
        print("📅 Fetching 15m candles from Binance...")
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"❌ Failed to fetch candle data: {e}")
        return None

# === APPLY STRATEGY INDICATORS ===
def apply_strategy(df):
    try:
        df["ema21"] = EMAIndicator(close=df["close"], window=21).ema_indicator()
        df["vol_sma30"] = df["volume"].rolling(window=30).mean()
        adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx.adx()
        return df
    except Exception as e:
        print(f"❌ Error while applying indicators: {e}")
        return None

# === DETERMINE TRADE DIRECTION ===
def get_trade_signal(df):
    last = df.iloc[-1]
    print("\n📊 Strategy Check (Latest Candle):")
    print(f"Price: {last['close']:.2f}, EMA21: {last['ema21']:.2f}")
    print(f"Volume: {last['volume']:.2f}, Vol SMA30: {last['vol_sma30']:.2f}")
    print(f"ADX: {last['adx']:.2f} > 20")

    if last["close"] > last["ema21"] and last["volume"] > last["vol_sma30"] and last["adx"] > 20:
        print("✅ Long Signal Detected")
        return "buy"
    elif last["close"] < last["ema21"] and last["volume"] > last["vol_sma30"] and last["adx"] > 20:
        print("✅ Short Signal Detected")
        return "sell"
    else:
        print("❌ No signal this candle.")
        return None

# === WAIT FOR NEXT 15M CANDLE ===
def wait_until_next_15min():
    now = datetime.now()
    wait_seconds = ((15 - now.minute % 15) * 60) - now.second
    print(f"🕒 Waiting {wait_seconds}s until next 15m candle...")
    time.sleep(wait_seconds)

# === MAIN LOOP ===
if __name__ == "__main__":
    balance = get_usd_balance(API_KEY, API_SECRET)
    if balance:
        setup_trade_log()
        print("\n🔁 Starting 15m Strategy Loop...")
        while True:
            try:
                wait_until_next_15min()
                df = fetch_eth_candles()
                df = apply_strategy(df)
                signal = get_trade_signal(df)
                print("✅ Cycle complete. Awaiting next 15m candle.")
            except KeyboardInterrupt:
                print("\n🚪 Bot stopped manually.")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(30)
    else:
        print("⚠️ USD balance fetch failed.")
