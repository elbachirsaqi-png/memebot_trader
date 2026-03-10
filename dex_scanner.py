import requests
import time
import os
import random
from dotenv import load_dotenv
load_dotenv()
import websockets
import asyncio
import json
import threading
from sniper_wallets import SNIPER_WALLETS
import re

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")
print("Jupiter key loaded:", JUPITER_API_KEY is not None)

JUPITER_TOKEN_SEARCH = "https://lite-api.jup.ag/tokens/v2/search"
JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_NEW_TOKENS = "https://lite-api.jup.ag/tokens/v2"

PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzk2Y5T7x1YgnSUZXoqBYwygJyBEtQV"
RAYDIUM_POOL_PROGRAM = "RVKd61ztZW9T8GZpRFsQmCFwHRHc2k1nH7E3K4u1E6D"

SOL_ADDRESS = "So11111111111111111111111111111111111111112"

SOLANA_RPC = "https://mainnet.helius-rpc.com/?api-key=51cd6fd8-5960-4710-9dfd-ec3c1d1866fb"

class DexScanner:

    def __init__(self):
        self.seen_addresses = set()
        self.age_cache = {}
        self._last_jup_call = 0.0
        self.dex_cache = {}
        self.dex_cache_max = 500
        self.liquidity_history = {}
        self.ws_token = None
    
    async def pump_ws_listener(self):

        uri = "wss://mainnet.helius-rpc.com/?api-key=51cd6fd8-5960-4710-9dfd-ec3c1d1866fb"

        async with websockets.connect(uri) as ws:

            sub = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [PUMPFUN_PROGRAM]
                    },
                    {
                        "commitment": "confirmed"
                    }
                ]
            }

            await ws.send(json.dumps(sub))

            while True:

                msg = await ws.recv()
                data = json.loads(msg)

                try:

                    logs = data["params"]["result"]["value"]["logs"]

                    for log in logs:

                        if "Program log:" in log:

                            match = re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", log)

                            if not match:
                                continue

                            mint = match.group(0)

                            if len(mint) != 44:
                                continue
                            
                            if mint.startswith("111111"):
                                continue

                            if "ComputeBudget" in mint:
                                continue

                            if mint not in self.seen_addresses:

                                self.seen_addresses.add(mint)

                                print("🚀 Pump mint detected:", mint)

                                return {
                                    "address": mint,
                                    "symbol": "PUMP-WS"
                                }

                except:
                    pass

    async def raydium_ws_listener(self):

        uri = "wss://mainnet.helius-rpc.com/?api-key=51cd6fd8-5960-4710-9dfd-ec3c1d1866fb"

        async with websockets.connect(uri) as ws:

            sub = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [RAYDIUM_POOL_PROGRAM]
                    },
                    {
                        "commitment": "confirmed"
                    }
                ]
            }

            await ws.send(json.dumps(sub))

            while True:

                msg = await ws.recv()
                data = json.loads(msg)

                try:

                    logs = data["params"]["result"]["value"]["logs"]

                    for log in logs:

                        if "initialize" in log.lower():

                            accounts = data["params"]["result"]["value"]["accounts"]

                            mint = accounts[1]

                            if mint not in self.seen_addresses:

                                self.seen_addresses.add(mint)

                                print("🟣 Raydium pool detected:", mint)

                                return {
                                    "address": mint,
                                    "symbol": "RAYDIUM"
                                }

                except:
                    pass

    def get_real_price(self, token_address):

        try:

            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                return None

            data = r.json()

            if "pairs" not in data or not data["pairs"]:
                return None

            pair = self.select_best_pool(data["pairs"])

            if not pair:
                return None

            price = pair.get("priceUsd")

            if not price:
                return None

            return float(price)

        except:
            return None


    def add_sniper_wallet(self, wallet):

        try:

            # charger performance
            try:
                with open("sniper_performance.json", "r") as f:
                    perf = json.load(f)
            except:
                perf = {}

            # augmenter score
            if wallet not in perf:
                perf[wallet] = 1
            else:
                perf[wallet] += 1

            with open("sniper_performance.json", "w") as f:
                json.dump(perf, f, indent=2)

            # charger snipers actifs
            try:
                with open("snipers.json", "r") as f:
                    snipers = json.load(f)
            except:
                snipers = []

            # ajouter seulement si score >=3
            if perf[wallet] >= 3 and wallet not in snipers:

                snipers.append(wallet)

                with open("snipers.json", "w") as f:
                    json.dump(snipers, f, indent=2)

                print("🔥 New verified sniper:", wallet)

        except Exception as e:
            print("Sniper update error:", e)

    def detect_early_buyers(self, token):

        try:

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    token,
                    {"limit": 20}
                ]
            }

            r = requests.post(SOLANA_RPC, json=payload, timeout=5)

            if r.status_code != 200:
                return

            data = r.json()

            for tx in data.get("result", [])[:5]:

                sig = tx["signature"]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        sig,
                        {"encoding": "json"}
                    ]
                }

                tx_data = requests.post(SOLANA_RPC, json=payload, timeout=5).json()

                try:

                    wallet = tx_data["result"]["transaction"]["message"]["accountKeys"][0]

                    self.add_sniper_wallet(wallet)

                except:
                    continue

        except:
            pass    
    
    def start_pump_ws(self):

        def run():

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while True:

                try:

                    token = loop.run_until_complete(self.pump_ws_listener())

                    if token:
                        self.ws_token = token

                except Exception as e:
                    print("Pump WS error:", e)
                    time.sleep(2)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def start_raydium_ws(self):

        def run():

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while True:

                try:

                    token = loop.run_until_complete(self.raydium_ws_listener())

                    if token:
                        self.ws_token = token

                except Exception as e:
                    print("Raydium WS error:", e)
                    time.sleep(2)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
    
    def fetch_sniper_buys(self):

        tokens = []

        wallets = list(SNIPER_WALLETS)

        try:
            with open("snipers.json", "r") as f:
                learned = json.load(f)
                wallets += learned
        except:
            pass

        for wallet in wallets:

            try:

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [
                        wallet,
                        {"limit": 5}
                    ]
                }

                r = requests.post(SOLANA_RPC, json=payload, timeout=5)

                if r.status_code != 200:
                    continue

                data = r.json()

                for tx in data.get("result", []):

                    sig = tx["signature"]

                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTransaction",
                        "params": [
                            sig,
                            {"encoding": "json"}
                        ]
                    }

                    tx_data = requests.post(SOLANA_RPC, json=payload, timeout=5).json()

                    try:

                        accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]

                        mint = accounts[-1]

                        if mint in self.seen_addresses:
                            continue

                        tokens.append({
                            "address": mint,
                            "symbol": "SNIPER"
                        })

                    except:
                        continue

            except:
                continue

        return tokens
    
    
    def fetch_pump_curve_completions(self):

        try:

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    PUMPFUN_PROGRAM,
                    {"limit": 30}
                ]
            }

            r = requests.post(SOLANA_RPC, json=payload)

            if r.status_code != 200:
                return []

            data = r.json()

            tokens = []

            for tx in data.get("result", []):

                sig = tx["signature"]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        sig,
                        {"encoding": "json"}
                    ]
                }

                tx_data = requests.post(SOLANA_RPC, json=payload).json()

                try:

                    logs = tx_data["result"]["meta"]["logMessages"]

                    for log in logs:

                        if "BondingCurveComplete" in log:

                            accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]

                            mint = accounts[1]

                            if mint in self.seen_addresses:
                                continue

                            tokens.append({
                                "address": mint,
                                "symbol": "PUMP-LIVE"
                            })

                except:
                    continue

            return tokens

        except:
            return []
    
    
    def fetch_pump_mints(self):

        try:

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    PUMPFUN_PROGRAM,
                    {"limit": 50}
                ]
            }

            r = requests.post(SOLANA_RPC, json=payload, timeout=10)

            if r.status_code != 200:
                return []

            data = r.json()

            tokens = []

            for tx in data.get("result", []):

                sig = tx["signature"]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        sig,
                        {"encoding": "json"}
                    ]
                }

                tx_data = requests.post(SOLANA_RPC, json=payload, timeout=10).json()

                try:

                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]

                    mint = accounts[1]

                    if mint in self.seen_addresses:
                        continue

                    tokens.append({
                        "address": mint,
                        "symbol": "PUMP-MINT"
                    })

                except:
                    continue

            return tokens

        except:
            return []

    
    def fetch_pumpfun_tokens(self):

        try:

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    PUMPFUN_PROGRAM,
                    {"limit": 30}
                ]
            }

            r = requests.post(SOLANA_RPC, json=payload, timeout=10)

            if r.status_code != 200:
                return []

            data = r.json()

            tokens = []

            for tx in data.get("result", []):

                sig = tx["signature"]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        sig,
                        {"encoding": "json"}
                    ]
                }

                tx_data = requests.post(SOLANA_RPC, json=payload).json()

                try:

                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]

                    mint = accounts[1]

                    if mint in self.seen_addresses:
                        continue

                    tokens.append({
                        "address": mint,
                        "symbol": "PUMP"
                    })

                except:
                    continue

            return tokens

        except:
            return []
        

    def fetch_raydium_pools(self):

        try:

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    RAYDIUM_POOL_PROGRAM,
                    {"limit": 30}
                ]
            }

            r = requests.post(SOLANA_RPC, json=payload)

            if r.status_code != 200:
                return []

            data = r.json()

            tokens = []

            for tx in data.get("result", []):

                sig = tx["signature"]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        sig,
                        {"encoding": "json"}
                    ]
                }

                tx_data = requests.post(SOLANA_RPC, json=payload).json()

                try:

                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]

                    mint = accounts[2]

                    if mint in self.seen_addresses:
                        continue

                    tokens.append({
                        "address": mint,
                        "symbol": "RAY"
                    })

                except:
                    continue

            return tokens

        except:
            return []    
    
    def fetch_new_tokens(self):

        try:

            self._throttle_jupiter()

            r = requests.get(JUPITER_NEW_TOKENS, timeout=10)

            if r.status_code != 200:
                return []

            tokens = r.json()

            new_tokens = []

            for token in tokens[:20]:

                address = token.get("address")

                if not address:
                    continue

                if address in self.seen_addresses:
                    continue

                new_tokens.append({
                    "address": address,
                    "symbol": token.get("symbol", "UNK"),
                    "name": token.get("name", "UNKNOWN")
                })

            return new_tokens

        except:
            return []
    
    def _throttle_jupiter(self):
        # 1 RPS => au moins 1 seconde entre 2 requêtes Jupiter
        now = time.monotonic()
        delta = now - self._last_jup_call
        if delta < 1.0:
            time.sleep(1.0 - delta)
        self._last_jup_call = time.monotonic()

    def quote_price(self, output_mint, amount=1_000_000, slippage_bps=150):

        try:

            self._throttle_jupiter()

            r = requests.get(
                JUPITER_QUOTE,
                params={
                    "inputMint": SOL_ADDRESS,
                    "outputMint": output_mint,
                    "amount": amount,
                    "slippageBps": slippage_bps
                },
                timeout=10
            )

            if r.status_code != 200:
                return None

            data = r.json()

            if "outAmount" not in data or "inAmount" not in data:
                return None

            out_amount = float(data["outAmount"])
            in_amount = float(data["inAmount"])

            if out_amount == 0:
                return None

            # 🔥 récupérer decimals du token
            decimals = data.get("outputMintDecimals", 9)

            # 🔥 corriger units
            out_amount_corrected = out_amount / (10 ** decimals)

            price = (in_amount / 1_000_000) / out_amount_corrected

            return price

        except:
            return None
    
    def detect_liquidity_drain(self, address, liquidity):

        try:

            now = time.time()

            if address not in self.liquidity_history:
                self.liquidity_history[address] = (liquidity, now)
                return False

            old_liq, old_time = self.liquidity_history[address]

            # vérifier seulement si au moins 10 secondes passées
            if now - old_time < 10:
                return False

            if old_liq == 0:
                return False

            drop = (old_liq - liquidity) / old_liq

            # mise à jour historique
            self.liquidity_history[address] = (liquidity, now)

            if drop > 0.25:
                print(f"⚠ Liquidity drain detected {address} drop={round(drop*100,2)}%")
                return True

            return False

        except:
            return False
    
    def fetch_new_pools(self):

        try:

            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                return []

            data = response.json()

            if "pairs" not in data:
                return []

            new_pairs = []

            for pair in data["pairs"][:100]:

                if pair["chainId"] != "solana":
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0)

                if liquidity is None:
                    continue

                liquidity = float(liquidity)

                if liquidity < 3000:
                    continue

                volume = pair.get("volume", {}).get("h24", 0)

                if volume < 2000:
                    continue

                token_address = pair["baseToken"]["address"]

                if token_address in self.seen_addresses:
                    continue

                new_pairs.append(pair)

            return new_pairs

        except Exception as e:
            print("Pool scanner error:", e)
            return []
    
    # =========================
    # MAIN FETCH
    # =========================

    def fetch_pairs(self):

        try:
            # 🔎 On utilise search API officielle
            search_terms = ["SOL", "AI", "DOG", "PEPE", "CAT", "MEME", "INU", "PEPE", "DOG", "INU", "MEME", "SHIB"]
            query = random.choice(search_terms)
            self._throttle_jupiter()
            response = requests.get(
                JUPITER_TOKEN_SEARCH,
                params={"query": query}
            )

            print("Token search status:", response.status_code)
            print("Token search response:", response.text[:500])

            if response.status_code != 200:
                print("Token search status:", response.status_code)
                return [], []

            tokens = response.json()

            if not isinstance(tokens, list):
                print("Unexpected token search format:", tokens)
                return [], []

            pairs = []

            # 🔥 Randomisation pour éviter toujours mêmes coins
            random.shuffle(tokens)

            for token in tokens[:20]:  # Limite raisonnable
                address = token["id"]
                dex_data = self.fetch_dexscreener_data(address)

                if not dex_data:
                    continue

                if self.detect_liquidity_drain(address, dex_data["liquidity"]):
                    continue

                if dex_data["liquidity"] < 30000:
                    continue

                quote_params = {
                    "inputMint": SOL_ADDRESS,
                    "outputMint": address,
                    "amount": 1000000,
                    "slippageBps": 150
                }

                headers = {}

                self._throttle_jupiter()
                quote = requests.get(
                    JUPITER_QUOTE,
                    params=quote_params,
                    headers=headers,
                    timeout=10
                )

                if quote.status_code != 200:
                    continue

                data = quote.json()

                if "routePlan" not in data:
                    continue

                if "outAmount" not in data:
                    continue

                route = data

                # 💰 Estimation prix via quote
                out_amount = float(route["outAmount"])
                in_amount = float(route["inAmount"])

                if in_amount == 0:
                    continue

                if out_amount == 0:
                    continue

                decimals = route.get("outputMintDecimals", 9)

                out_amount = out_amount / (10 ** decimals)

                price = (in_amount / 1_000_000) / out_amount

                # 🧠 Construction structure compatible Dex
                pair = {
                    "baseToken": {
                        "address": address,
                        "symbol": token.get("symbol", "UNK")
                    },
                    "priceUsd": str(price),
                    "liquidity": {
                        "usd": dex_data["liquidity"]
                    },
                    "volume": {
                        "m5": dex_data["volume_5m"]
                    },
                    "txns": {
                        "m5": {
                            "buys": int(dex_data["buy_ratio"] * 100),
                            "sells": int((1 - dex_data["buy_ratio"]) * 100)
                        }
                    },
                    "fdv": dex_data["market_cap"]
                }

                pairs.append(pair)

            new_pairs = [
                p for p in pairs if p["baseToken"]["address"] not in self.seen_addresses
            ]

            for p in new_pairs:
                self.seen_addresses.add(p["baseToken"]["address"])

            return pairs, new_pairs

        except Exception as e:
            import traceback
            print("Jupiter FULL ERROR:")
            traceback.print_exc()
            return [], []

    def fetch_dexscreener_data(self, token_address):

        try:

            if token_address in self.dex_cache:
                return self.dex_cache[token_address]
            
            if len(self.dex_cache) > self.dex_cache_max:
                self.dex_cache.clear()

            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()

            if "pairs" not in data or not data["pairs"]:
                return None

            best_pair = self.select_best_pool(data["pairs"])

            if not best_pair:
                return None

            pair = best_pair

            liquidity = float(pair.get("liquidity", {}).get("usd", 0))
            volume_5m = float(pair.get("volume", {}).get("m5", 0))

            if liquidity < 4000:
                return None

            if volume_5m < 1000:
                return None

            buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
            sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)

            total = buys + sells

            if total == 0:
                return None

            buy_ratio = buys / total

            market_cap = float(pair.get("fdv", 0))

            result = {
                "liquidity": liquidity,
                "volume_5m": volume_5m,
                "buy_ratio": buy_ratio,
                "market_cap": market_cap
            }

            self.dex_cache[token_address] = result

            return result
        
        except Exception as e:
            print("Dexscreener error:", e)
            return None
    
    def select_best_pool(self, pairs):

        """
        Sélectionne le pool Dexscreener avec la plus grosse liquidity
        """

        try:

            best_pair = None
            max_liquidity = 0

            for pair in pairs:

                liquidity = pair.get("liquidity", {}).get("usd", 0)

                if liquidity is None:
                    continue

                liquidity = float(liquidity)

                if liquidity > max_liquidity:
                    max_liquidity = liquidity
                    best_pair = pair

            return best_pair

        except:
            return None
    
    # =========================
    # EXTRACTION COMPATIBLE BOT
    # =========================

    def extract_token_data(self, pair):

        try:
            address = pair["baseToken"]["address"]
            symbol = pair["baseToken"]["symbol"]

            liquidity = float(pair["liquidity"]["usd"])
            volume_5m = float(pair["volume"]["m5"])

            buys = pair["txns"]["m5"]["buys"]
            sells = pair["txns"]["m5"]["sells"]

            total = buys + sells

            if total == 0:
                return None

            buy_ratio = buys / total

            market_cap = float(pair.get("fdv", 0))

            real_age = self.get_token_age_minutes(address)

            if real_age is None:
                real_age = 99999  # fallback

            return {
                "name": symbol,
                "symbol": symbol,
                "address": address,
                "market_cap": market_cap,
                "liquidity": liquidity,
                "volume_5m": volume_5m,
                "buy_ratio": buy_ratio,
                "top_holder_percent": 0,
                "age_minutes": real_age
            }

        except:
            return None

    def get_swap_price(self, token_address):

        try:

            # 1 SOL
            amount = 62_500_000

            price = self.quote_price(token_address, amount)

            if price is None:
                return None

            return float(price)

        except:
            return None


    def get_token_age_minutes(self, mint_address):

        # 🔥 1️⃣ Vérifie si déjà en cache
        if mint_address in self.age_cache:
            return self.age_cache[mint_address]

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    mint_address,
                    {"limit": 50}
                ]
            }

            response = requests.post(SOLANA_RPC, json=payload)
            data = response.json()

            if "result" not in data or not data["result"]:
                return None

            oldest = data["result"][-1]

            if "blockTime" not in oldest or oldest["blockTime"] is None:
                return None

            block_time = oldest["blockTime"]
            current_time = int(time.time())

            age_seconds = current_time - block_time
            age_minutes = round(age_seconds / 60, 2)

            # 🔥 2️⃣ Sauvegarde dans cache
            self.age_cache[mint_address] = age_minutes

            return age_minutes

        except:
            return None


    # =========================
    # SLIPPAGE ESTIMATION
    # =========================

    def estimate_slippage(self, trade_amount, liquidity):

        if liquidity == 0:
            return 100

        impact = (trade_amount / liquidity) * 100

        return round(impact, 2)