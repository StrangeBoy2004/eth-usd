import requests
import time
import hmac
import hashlib

class DeltaRestClient:
    def __init__(self, base_url, api_key, api_secret):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, method, path):
        request_time = str(int(time.time() * 1000))
        payload = request_time + method + path
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "api-key": self.api_key,
            "request-time": request_time,
            "signature": signature,
            "Content-Type": "application/json"
        }
        return headers
    def _request(self, method, path, params=None, json_data=None):
        url = self.base_url + path
        headers = self._sign(method, path)

        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, params=params)
        else:
            raise ValueError("Unsupported HTTP method")

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        return response.json()

    def place_order(self, product_id, size, side, limit_price, order_type, post_only):
        path = "/v2/orders"
        data = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "limit_price": limit_price,
            "order_type": order_type,
            "post_only": post_only
        }
        return self._request("POST", path, json_data=data)

    def place_stop_order(self, product_id, size, side, stop_price, limit_price, order_type):
        path = "/v2/orders"
        data = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "stop_order_type": "stop_limit_order"
        }
        return self._request("POST", path, json_data=data)

    def get_live_orders(self, query):
        path = "/v2/orders/live"
        return self._request("GET", path, params=query).get("result", [])

    def cancel_order(self, product_id, order_id):
        path = f"/v2/orders/{order_id}"
        return self._request("DELETE", path, params={"product_id": product_id})

    def get_position(self, product_id):
        path = "/v2/positions/margined"
        positions = self._request("GET", path).get("result", [])
        for pos in positions:
            if pos["product_id"] == product_id:
                return pos
        return None
