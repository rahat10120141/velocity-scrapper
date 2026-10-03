"""
VELOCITY SCALPER: High-Performance Binance Client
Supports Futures REST API (Live & Testnet) and Spot REST API
Optimized for 1-minute high-frequency data fetching and low-latency orders.
"""
import os
import time
import json
import hmac
import hashlib
import urllib.request
import urllib.parse
import pandas as pd
from config import (
    FUTURES_LIVE_URL, FUTURES_TESTNET_URL,
    SPOT_LIVE_URL, SPOT_TESTNET_URL,
    BINANCE_API_KEY, BINANCE_API_SECRET,
    BINANCE_FUTURES_API_KEY, BINANCE_FUTURES_API_SECRET
)

class BinanceClient:
    def __init__(self, mode="FUTURES", is_testnet=False):
        self.mode = mode
        self.is_testnet = is_testnet
        
        if mode == "FUTURES":
            self.base_url = FUTURES_TESTNET_URL if is_testnet else FUTURES_LIVE_URL
            self.api_key = BINANCE_FUTURES_API_KEY or BINANCE_API_KEY
            self.api_secret = BINANCE_FUTURES_API_SECRET or BINANCE_API_SECRET
        else:
            self.base_url = SPOT_TESTNET_URL if is_testnet else SPOT_LIVE_URL
            self.api_key = BINANCE_API_KEY
            self.api_secret = BINANCE_API_SECRET
            
        self.headers = {
            "User-Agent": "VelocityScalper/1.0",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self.symbol_info_cache = {}

    def _request(self, method, endpoint, params=None, signed=False):
        if params is None:
            params = {}
            
        headers = self.headers.copy()
        
        if signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("API Key and Secret required for signed requests.")
            headers["X-MBX-APIKEY"] = self.api_key
            params["timestamp"] = int(time.time() * 1000)
            query = urllib.parse.urlencode(params)
            sig = hmac.new(self.api_secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha256).hexdigest()
            full_url = f"{self.base_url}{endpoint}?{query}&signature={sig}"
            req_data = None
        else:
            if params:
                query = urllib.parse.urlencode(params)
                full_url = f"{self.base_url}{endpoint}?{query}"
            else:
                full_url = f"{self.base_url}{endpoint}"
            req_data = None

        req = urllib.request.Request(full_url, headers=headers, method=method, data=req_data)
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=7) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                err_msg = e.read().decode('utf-8')
                try:
                    err_json = json.loads(err_msg)
                    raise RuntimeError(f"Binance Error {e.code}: {err_json.get('msg', err_msg)}")
                except Exception:
                    raise RuntimeError(f"Binance HTTP {e.code}: {err_msg}")
            except Exception as e:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise RuntimeError(f"Network error connecting to {full_url}: {str(e)}")

    def ping(self):
        """Test server latency."""
        t0 = time.time()
        path = "/fapi/v1/ping" if self.mode == "FUTURES" else "/api/v3/ping"
        self._request("GET", path)
        return int((time.time() - t0) * 1000)

    def get_ticker_price(self, symbol="SOLUSDT"):
        """Fetch real-time single ticker price."""
        path = "/fapi/v1/ticker/price" if self.mode == "FUTURES" else "/api/v3/ticker/price"
        data = self._request("GET", path, {"symbol": symbol})
        return float(data["price"])

    def fetch_klines(self, symbol="SOLUSDT", interval="1m", limit=120):
        """Fetch recent candlestick bars as Pandas DataFrame with automatic pagination if limit > 1000."""
        path = "/fapi/v1/klines" if self.mode == "FUTURES" else "/api/v3/klines"
        
        if limit <= 1000:
            data = self._request("GET", path, {"symbol": symbol, "interval": interval, "limit": limit})
        else:
            data = []
            remaining = limit
            end_time = None
            while remaining > 0:
                fetch_len = min(remaining, 1000)
                p = {"symbol": symbol, "interval": interval, "limit": fetch_len}
                if end_time:
                    p["endTime"] = end_time
                batch = self._request("GET", path, p)
                if not batch:
                    break
                data = batch + data
                remaining -= len(batch)
                end_time = batch[0][0] - 1
                if len(batch) < fetch_len:
                    break
                time.sleep(0.04)

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_vol", "taker_buy_quote", "ignore"
        ])
        df.drop_duplicates(subset=["open_time"], inplace=True)
        df.sort_values("open_time", inplace=True)
        df["time"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)
            
        df.set_index("time", inplace=True)
        return df

    def get_symbol_rules(self, symbol="SOLUSDT"):
        """Fetch lot size, tick size, and minimum notional filter rules."""
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]
            
        path = "/fapi/v1/exchangeInfo" if self.mode == "FUTURES" else "/api/v3/exchangeInfo"
        info = self._request("GET", path)
        
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                step_size = 0.001
                tick_size = 0.01
                min_notional = 5.0
                
                for f in s.get("filters", []):
                    if f["filterType"] in ["LOT_SIZE", "MARKET_LOT_SIZE"]:
                        step_size = float(f.get("stepSize", step_size))
                    elif f["filterType"] == "PRICE_FILTER":
                        tick_size = float(f.get("tickSize", tick_size))
                    elif f["filterType"] in ["MIN_NOTIONAL", "NOTIONAL"]:
                        min_notional = float(f.get("notional", f.get("minNotional", min_notional)))
                        
                res = {
                    "step_size": step_size,
                    "tick_size": tick_size,
                    "min_notional": min_notional,
                    "base_asset": s.get("baseAsset", ""),
                    "quote_asset": s.get("quoteAsset", "USDT")
                }
                self.symbol_info_cache[symbol] = res
                return res
                
        return {"step_size": 0.001, "tick_size": 0.01, "min_notional": 5.0}

    def format_quantity(self, symbol, quantity):
        """Format quantity strictly to exchange stepSize."""
        rules = self.get_symbol_rules(symbol)
        step = rules["step_size"]
        precision = 0
        if "." in str(step):
            precision = len(str(step).rstrip('0').split(".")[1])
        return round(float(quantity) - (float(quantity) % step), precision)

    def set_leverage(self, symbol="SOLUSDT", leverage=5):
        """Set futures position leverage."""
        if self.mode != "FUTURES":
            return
        try:
            return self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)
        except Exception as e:
            return {"error": str(e)}

    def place_order(self, symbol, side, order_type="MARKET", quantity=None, price=None, reduce_only=False):
        """Place live order with safety formatting."""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": self.format_quantity(symbol, quantity)
        }
        
        if order_type.upper() == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
            
        if self.mode == "FUTURES":
            if reduce_only:
                params["reduceOnly"] = "true"
            return self._request("POST", "/fapi/v1/order", params, signed=True)
        else:
            return self._request("POST", "/api/v3/order", params, signed=True)
