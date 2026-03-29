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
import queue  # ✅ CORRECT — pas collections
from sniper_wallets import SNIPER_WALLETS
import re

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")
print("Jupiter key loaded:", JUPITER_API_KEY is not None)

JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_NEW_TOKENS = "https://lite-api.jup.ag/tokens/v2"

PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzk2Y5T7x1YgnSUZXoqBYwygJyBEtQV"
RAYDIUM_POOL_PROGRAM = "RVKd61ztZW9T8GZpRFsQmCFwHRHc2k1nH7E3K4u1E6D"

SOL_ADDRESS = "So11111111111111111111111111111111111111112"

SOLANA_heliusRPC = "https://mainnet.helius-rpc.com/?api-key=51cd6fd8-5960-4710-9dfd-ec3c1d1866fb"

SHYFT_API_KEY = os.getenv("SHYFT_API_KEY")
SOLANA_RPC = f"https://rpc.shyft.to?api_key={SHYFT_API_KEY}"

BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")


class DexScanner:

    def __init__(self):
        self.seen_addresses = set()
        self._seen_addresses_last_clear = time.time()
        self.age_cache = {}
        self._last_jup_call = 0.0
        self.dex_cache = {}
        self.dex_cache_max = 500
        self.liquidity_history = {}
        self.ws_queue = queue.Queue()  # ✅ Queue pour WebSocket
        self.security_cache = {}  
        self.security_pending = set()  

    # =========================
    # WEBSOCKET PUMP.FUN
    # =========================

    async def pump_ws_listener(self):
        """Écoute en continu — met les tokens dans la queue sans jamais retourner."""
        uri = f"wss://rpc.shyft.to?api_key={SHYFT_API_KEY}"

        async with websockets.connect(uri) as ws:

            sub = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [PUMPFUN_PROGRAM]},
                    {"commitment": "confirmed"}
                ]
            }

            await ws.send(json.dumps(sub))

            while True:  # ✅ boucle infinie — ne retourne jamais

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
                                self.ws_queue.put({  # ✅ queue au lieu de return
                                    "address": mint,
                                    "symbol": "PUMP-WS"
                                })
                except:
                    pass

    async def raydium_ws_listener(self):
        """Écoute en continu — met les tokens dans la queue sans jamais retourner."""
        uri = f"wss://rpc.shyft.to?api_key={SHYFT_API_KEY}"

        async with websockets.connect(uri) as ws:

            sub = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [RAYDIUM_POOL_PROGRAM]},
                    {"commitment": "confirmed"}
                ]
            }

            await ws.send(json.dumps(sub))

            while True:  # ✅ boucle infinie

                msg = await ws.recv()
                data = json.loads(msg)

                try:
                    logs = data["params"]["result"]["value"]["logs"]

                    for log in logs:
                        if "initialize" in log.lower():
                            accounts = data["params"]["result"]["value"].get("accounts", [])
                            if len(accounts) < 2:
                                continue
                            mint = accounts[1]
                            if mint not in self.seen_addresses:
                                self.seen_addresses.add(mint)
                                print("🟣 Raydium pool detected:", mint)
                                self.ws_queue.put({  # ✅ queue
                                    "address": mint,
                                    "symbol": "RAYDIUM"
                                })
                except:
                    pass

    def prefetch_security_async(self, address, analyzer):
        """Lance la vérification sécurité en background."""
        if address in self.security_cache:
            return
        if address in self.security_pending:
            return
        
        self.security_pending.add(address)
        
        def _fetch():
            try:
                result = analyzer.check_mint_security(address)
                if result:
                    self.security_cache[address] = result
            except:
                pass
            finally:
                self.security_pending.discard(address)
        
        threading.Thread(target=_fetch, daemon=True).start()
    
    def fetch_dexscreener_new_pairs(self):
        """Nouvelles pools Solana via DexScreener — gratuit et rapide."""
        try:
            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                return []
            data = r.json()
            pairs = data.get("pairs", [])
            result = []
            now_ms = time.time() * 1000
            for pair in pairs:
                addr = pair.get("baseToken", {}).get("address")
                if not addr or addr in self.seen_addresses:
                    continue
                # Seulement les tokens créés il y a moins de 20 minutes
                created_at = pair.get("pairCreatedAt")
                if created_at:
                    age_min = (now_ms - created_at) / 60000
                    if age_min > 20:
                        continue
                result.append({
                    "address": addr,
                    "symbol": pair.get("baseToken", {}).get("symbol", "DEX")
                })
            return result
        except:
            return []
    
    
    def fetch_pumpfun_new(self):
        """API Pump.fun officielle — pas de limite WebSocket."""
        try:
            url = "https://frontend-api.pump.fun/coins?offset=0&limit=50&sort=created_timestamp&order=DESC"
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                return []
            tokens = r.json()
            result = []
            now_ms = int(time.time() * 1000)

            for token in tokens:
                addr = token.get("mint")
                if addr and addr not in self.seen_addresses:
                    continue
                # Seulement si créé il y a moins de 30 minutes
                created = token.get("created_timestamp", 0)
                if created:
                    age_min = (now_ms - created) / 60000
                    if age_min > 30:
                        continue
                # Seulement si raydium_pool existe = token gradué
                if not token.get("raydium_pool"):
                    continue
                result.append({
                    "address": addr,
                    "symbol": token.get("symbol", "PUMP"),
                    "name": token.get("name", ""),
                })
            return result
        except:
            return []
    
    def start_pump_ws(self):
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while True:
                try:
                    loop.run_until_complete(self.pump_ws_listener())
                except Exception as e:
                    print("Pump WS error:", e)
                    time.sleep(5)  # reconnect

        threading.Thread(target=run, daemon=True).start()

    def start_raydium_ws(self):
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while True:
                try:
                    loop.run_until_complete(self.raydium_ws_listener())
                except Exception as e:
                    print("Raydium WS error:", e)
                    time.sleep(5)

        threading.Thread(target=run, daemon=True).start()

    # =========================
    # SNIPER WALLETS
    # =========================

    def add_sniper_wallet(self, wallet):
        try:
            try:
                with open("sniper_performance.json", "r") as f:
                    perf = json.load(f)
            except:
                perf = {}

            perf[wallet] = perf.get(wallet, 0) + 1

            with open("sniper_performance.json", "w") as f:
                json.dump(perf, f, indent=2)

            try:
                with open("snipers.json", "r") as f:
                    snipers = json.load(f)
            except:
                snipers = []

            if perf[wallet] >= 3 and wallet not in snipers:
                snipers.append(wallet)
                with open("snipers.json", "w") as f:
                    json.dump(snipers, f, indent=2)
                print("🔥 New verified sniper:", wallet)

        except Exception as e:
            print("Sniper update error:", e)

    def detect_early_buyers(self, token):
        """Appelé après un gros profit — détecte les wallets qui ont acheté tôt."""
        def _run():
            try:
                payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [token, {"limit": 20}]
                }
                r = requests.post(SOLANA_RPC, json=payload, timeout=5)
                if r.status_code != 200:
                    return
                data = r.json()

                for tx in data.get("result", [])[:5]:
                    sig = tx["signature"]
                    payload2 = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "getTransaction",
                        "params": [sig, {"encoding": "json"}]
                    }
                    tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=5).json()
                    try:
                        wallet = tx_data["result"]["transaction"]["message"]["accountKeys"][0]
                        self.add_sniper_wallet(wallet)
                    except:
                        continue
            except:
                pass

        # ✅ En background pour ne pas bloquer
        threading.Thread(target=_run, daemon=True).start()

    def fetch_sniper_buys(self):
        """
        ✅ Version optimisée : seulement les signatures récentes,
        pas de getTransaction (trop lent).
        On retourne les derniers tokens achetés par les snipers
        en lisant uniquement les signatures.
        """
        tokens = []
        wallets = list(SNIPER_WALLETS)

        try:
            with open("snipers.json", "r") as f:
                learned = json.load(f)
                wallets += learned
        except:
            pass

        # ✅ Limiter à 5 wallets par cycle pour rester rapide
        wallets = wallets[:5]

        for wallet in wallets:
            try:
                payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [wallet, {"limit": 5}]  # ✅ 5 au lieu de 30
                }
                r = requests.post(SOLANA_RPC, json=payload, timeout=3)
                if r.status_code != 200:
                    continue
                data = r.json()

                for tx in data.get("result", []):
                    sig = tx["signature"]
                    payload2 = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "getTransaction",
                        "params": [sig, {"encoding": "json"}]
                    }
                    tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=3).json()
                    try:
                        accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                        mint = accounts[-1]
                        if mint in self.seen_addresses:
                            continue
                        if len(mint) < 32:
                            continue
                        tokens.append({"address": mint, "symbol": "SNIPER", "copied_from": wallet})
                    except:
                        continue
            except:
                continue

        return tokens

    # =========================
    # FETCH TOKENS (RPC)
    # =========================

    def fetch_pump_curve_completions(self):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [PUMPFUN_PROGRAM, {"limit": 20}]
            }
            r = requests.post(SOLANA_RPC, json=payload, timeout=5)
            if r.status_code != 200:
                return []
            data = r.json()
            tokens = []

            for tx in data.get("result", []):
                sig = tx["signature"]
                payload2 = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "json"}]
                }
                tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=5).json()
                try:
                    logs = tx_data["result"]["meta"]["logMessages"]
                    for log in logs:
                        if "BondingCurveComplete" in log:
                            accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                            mint = accounts[1]
                            if mint not in self.seen_addresses:
                                tokens.append({"address": mint, "symbol": "PUMP-LIVE"})
                except:
                    continue
            return tokens
        except:
            return []

    def fetch_pump_mints(self):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [PUMPFUN_PROGRAM, {"limit": 20}]
            }
            r = requests.post(SOLANA_RPC, json=payload, timeout=5)
            if r.status_code != 200:
                return []
            data = r.json()
            tokens = []

            for tx in data.get("result", []):
                sig = tx["signature"]
                payload2 = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "json"}]
                }
                tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=5).json()
                try:
                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                    mint = accounts[1]
                    if mint not in self.seen_addresses:
                        tokens.append({"address": mint, "symbol": "PUMP-MINT"})
                except:
                    continue
            return tokens
        except:
            return []

    def fetch_pumpfun_tokens(self):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [PUMPFUN_PROGRAM, {"limit": 20}]
            }
            r = requests.post(SOLANA_RPC, json=payload, timeout=5)
            if r.status_code != 200:
                return []
            data = r.json()
            tokens = []

            for tx in data.get("result", []):
                sig = tx["signature"]
                payload2 = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "json"}]
                }
                tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=5).json()
                try:
                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                    mint = accounts[1]
                    if mint not in self.seen_addresses:
                        tokens.append({"address": mint, "symbol": "PUMP"})
                except:
                    continue
            return tokens
        except:
            return []

    def fetch_raydium_pools(self):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [RAYDIUM_POOL_PROGRAM, {"limit": 20}]
            }
            r = requests.post(SOLANA_RPC, json=payload, timeout=5)
            if r.status_code != 200:
                return []
            data = r.json()
            tokens = []

            for tx in data.get("result", []):
                sig = tx["signature"]
                payload2 = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "json"}]
                }
                tx_data = requests.post(SOLANA_RPC, json=payload2, timeout=5).json()
                try:
                    accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                    mint = accounts[2]
                    if mint not in self.seen_addresses:
                        tokens.append({"address": mint, "symbol": "RAY"})
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

    # =========================
    # JUPITER
    # =========================

    def _throttle_jupiter(self):
        """1 RPS max sur Jupiter."""
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
            decimals = data.get("outputMintDecimals", 9)
            out_amount_corrected = out_amount / (10 ** decimals)
            if out_amount_corrected <= 0:
                return None
            price = (in_amount / 1_000_000_000) / out_amount_corrected
            if price <= 0 or price > 1_000_000:
                return None
            return price
        except:
            return None

    def get_swap_price(self, token_address, trade_amount_usd=5):
        try:
            sol_price = 88  
            sol_amount = trade_amount_usd / sol_price
            lamports = int(sol_amount * 1_000_000_000)
            price = self.quote_price(token_address, lamports)
            if price is None:
                return None
            return float(price)
        except:
            return None

        
    # =========================
    # BIRDEYE PRIX TEMPS RÉEL
    # =========================

  
    def get_birdeye_price(self, token_address):
        """Prix temps réel via Birdeye — utilisé pour tracker les trades actifs."""
        try:
            if not BIRDEYE_API_KEY:  # ← si clé manquante, fallback direct
                return self.get_real_price(token_address)
            url = f"https://public-api.birdeye.so/defi/price?address={token_address}"
            headers = {"X-API-KEY": BIRDEYE_API_KEY}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code != 200:
                # fallback Dexscreener si Birdeye échoue
                return self.get_real_price(token_address)
            data = r.json()
            price = data.get("data", {}).get("value")
            if price is None:
                return self.get_real_price(token_address)
            return float(price)
        except:
            return self.get_real_price(token_address)

    def get_real_price(self, token_address):
        """Fallback prix via Dexscreener."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                return None
            data = r.json()
            if "pairs" not in data or not data["pairs"]:
                return None
            pair = self.select_best_pool(data["pairs"])
            if not pair:
                return None
            price = pair.get("priceUsd")
            return float(price) if price else None
        except:
            return None
  
    def fetch_dexscreener_data(self, token_address):
        """Avec cache 60s — pour le scan de nouveaux tokens."""
        try:
            if token_address in self.dex_cache:
                cached = self.dex_cache[token_address]
                if time.time() - cached["ts"] < 60:
                    return cached["data"]

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
            liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
            volume_5m = float(pair.get("volume", {}).get("m5", 0) or 0)

            if liquidity < 4000:
                return None
            if volume_5m < 500:
                return None

            buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
            sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)
            total = buys + sells
            if total == 0:
                return None

            buy_ratio = buys / total
            market_cap = float(pair.get("fdv", 0) or 0)

            result = {
                "liquidity": liquidity,
                "volume_5m": volume_5m,
                "buy_ratio": buy_ratio,
                "market_cap": market_cap
            }

            self.dex_cache[token_address] = {"data": result, "ts": time.time()}
            return result

        except Exception as e:
            print("Dexscreener error:", e)
            return None

    def get_trade_dex_data(self, token_address):
        """Sans cache, sans filtres stricts — pour suivre les trades actifs."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None
            data = response.json()
            if "pairs" not in data or not data["pairs"]:
                return None
            pair = self.select_best_pool(data["pairs"])
            if not pair:
                return None
            liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
            if liquidity <= 100:
                return None
            volume_5m = float(pair.get("volume", {}).get("m5", 0) or 0)
            buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
            sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)
            total = buys + sells
            buy_ratio = buys / total if total > 0 else 0.5
            return {
                "liquidity": liquidity,
                "volume_5m": volume_5m,
                "buy_ratio": buy_ratio,
                "market_cap": float(pair.get("fdv", 0) or 0)
            }
        except:
            return None

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
                if pair.get("chainId") != "solana":
                    continue
                liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                if liquidity < 3000:
                    continue
                volume = float(pair.get("volume", {}).get("h24", 0) or 0)
                if volume < 2000:
                    continue

                pair_created_at = pair.get("pairCreatedAt")
                if pair_created_at:
                    age_min = (time.time() * 1000 - pair_created_at) / 60000
                    if age_min > 30:
                        continue

                token_address = pair["baseToken"]["address"]
                if token_address in self.seen_addresses:
                    continue
                new_pairs.append(pair)
            return new_pairs
        except Exception as e:
            print("Pool scanner error:", e)
            return []

    def fetch_trending_tokens(self):
        """Tokens trending sur Dexscreener — nouveaux et actifs."""
        try:
            # Trending sur Solana par volume récent
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                return []
            data = r.json()
            pairs = data.get("pairs", [])
            result = []
            now_ms = time.time() * 1000
            for pair in pairs:
                if pair.get("chainId") != "solana":
                    continue
                addr = pair.get("baseToken", {}).get("address")
                if not addr or addr in self.seen_addresses:
                    continue
                # Seulement les récents
                created = pair.get("pairCreatedAt")
                if created and (now_ms - created) / 60000 > 30:
                    continue
                result.append(pair)
            return result
        except:
            return []
    
    def get_token_symbol(self, token_address):
        """Récupère le symbol réel du token."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return "SNIPER"
            data = r.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return "SNIPER"
            return pairs[0].get("baseToken", {}).get("symbol", "SNIPER")
        except:
            return "SNIPER"
    
    def fetch_pairs(self):
        try:
            urls = [
                # Nouvelles pools Solana — le plus important
                "https://api.dexscreener.com/latest/dex/pairs/solana",
                # Tokens boostés
                "https://api.dexscreener.com/token-boosts/top/v1",
                # Tokens avec profils récents
                "https://api.dexscreener.com/token-profiles/latest/v1",
            ]

            all_raw_pairs = []

            for url in urls:
                try:
                    r = requests.get(url, timeout=8)
                    if r.status_code != 200:
                        continue
                    data = r.json()

                    if isinstance(data, dict) and "pairs" in data:
                        all_raw_pairs += data["pairs"]
                    elif isinstance(data, list):
                        for item in data[:30]:
                            addr = item.get("tokenAddress")
                            if addr:
                                dex_data = self.fetch_dexscreener_data(addr)
                                if dex_data:
                                    all_raw_pairs.append({
                                        "baseToken": {"address": addr, "symbol": item.get("description", "UNK")[:10]},
                                        "liquidity": {"usd": dex_data["liquidity"]},
                                        "volume": {"m5": dex_data["volume_5m"]},
                                        "txns": {"m5": {
                                            "buys": int(dex_data["buy_ratio"] * 100),
                                            "sells": int((1 - dex_data["buy_ratio"]) * 100)
                                        }},
                                        "fdv": dex_data["market_cap"],
                                        "pairCreatedAt": None
                                    })
                except:
                    continue

            # Mélanger pour ne pas toujours traiter dans le même ordre
            random.shuffle(all_raw_pairs)

            pairs = []
            new_pairs = []
            now_ms = time.time() * 1000

            for pair in all_raw_pairs:
                try:
                    if pair.get("chainId") and pair["chainId"] != "solana":
                        continue

                    liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                    if liquidity < 3000:
                        continue

                    volume = float(pair.get("volume", {}).get("m5", 0) or 0)
                    if volume < 500:
                        continue

                    pair_created_at = pair.get("pairCreatedAt")
                    if pair_created_at:
                        age_minutes = (now_ms - pair_created_at) / 60000
                        if age_minutes > 30:
                            continue

                    address = pair["baseToken"]["address"]
                    is_new = address not in self.seen_addresses
                    pairs.append(pair)

                    if is_new:
                        new_pairs.append(pair)
                        self.seen_addresses.add(address)

                    # Vider seen_addresses toutes les 10 minutes
                    if time.time() - self._seen_addresses_last_clear > 600:
                        self.seen_addresses.clear()
                        self._seen_addresses_last_clear = time.time()
                        print("🔄 seen_addresses cleared")

                except:
                    continue

            return pairs, new_pairs

        except Exception as e:
            print("fetch_pairs error:", e)
            return [], []
        # =========================
    # POOL SELECTION
    # =========================

    def select_best_pool(self, pairs):
        """Sélectionne la pool avec la plus grosse liquidité."""
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
    # TOKEN DATA EXTRACTION
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
            market_cap = float(pair.get("fdv", 0) or 0)

            real_age = self.age_cache.get(address)
            if real_age is None:
                self.prefetch_age_async(address)
                real_age = 30  # défaut 30 min, vrai âge calculé en background

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

    def prefetch_age_async(self, address):
        """Calcule l'âge en arrière-plan."""
        if address in self.age_cache:
            return
        def _fetch():
            age = self.get_token_age_minutes(address)
            if age is not None:
                self.age_cache[address] = age
        threading.Thread(target=_fetch, daemon=True).start()

    def get_token_age_minutes(self, mint_address):
        """
        Méthode 1 : pairCreatedAt Dexscreener (le plus fiable)
        Méthode 2 : première signature RPC (fallback)
        """
        if mint_address in self.age_cache:
            return self.age_cache[mint_address]

        # ── Méthode 1 : Dexscreener pairCreatedAt ──
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_address}"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                pairs = data.get("pairs", [])
                if pairs:
                    # Prendre le pair le plus ancien (pairCreatedAt le plus petit)
                    oldest_pair = min(
                        [p for p in pairs if p.get("pairCreatedAt")],
                        key=lambda p: p["pairCreatedAt"],
                        default=None
                    )
                    if oldest_pair:
                        created_at_ms = oldest_pair["pairCreatedAt"]
                        age_minutes = (time.time() * 1000 - created_at_ms) / 60000
                        age_minutes = round(age_minutes, 2)
                        self.age_cache[mint_address] = age_minutes
                        return age_minutes
        except:
            pass

        # ── Méthode 2 : RPC fallback ──
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [mint_address, {"limit": 1000}]
            }
            response = requests.post(SOLANA_RPC, json=payload, timeout=8)
            data = response.json()
            if "result" not in data or not data["result"]:
                return None
            oldest = data["result"][-1]
            if "blockTime" not in oldest or oldest["blockTime"] is None:
                return None
            age_seconds = int(time.time()) - oldest["blockTime"]
            age_minutes = round(age_seconds / 60, 2)
            self.age_cache[mint_address] = age_minutes
            return age_minutes
        except:
            return None

    # =========================
    # LIQUIDITY DRAIN DETECTION
    # =========================

    def detect_liquidity_drain(self, address, liquidity):
        try:
            now = time.time()
            if address not in self.liquidity_history:
                self.liquidity_history[address] = (liquidity, now)
                return False
            old_liq, old_time = self.liquidity_history[address]
            if now - old_time < 10:
                return False
            if old_liq == 0:
                return False
            drop = (old_liq - liquidity) / old_liq
            self.liquidity_history[address] = (liquidity, now)
            if drop > 0.25:
                print(f"⚠ Liquidity drain {address} drop={round(drop*100,2)}%")
                return True
            return False
        except:
            return False

    # =========================
    # SLIPPAGE
    # =========================

    def estimate_slippage(self, trade_amount, liquidity):
        if liquidity == 0:
            return 100
        impact = (trade_amount / liquidity) * 100
        return round(impact, 2)