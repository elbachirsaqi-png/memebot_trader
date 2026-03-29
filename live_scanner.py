import time
import json
import threading
import queue
from dex_scanner import DexScanner
from scanner_engine import ScannerEngine
from grok_engine import GrokEngine
from trade_manager import TradeManager
from onchain_analyzer import OnChainAnalyzer
from curve_analyzer import CurveAnalyzer
import random


_early_tokens_buffer = []
_early_tokens_lock = threading.Lock()

def secondary_scan_loop(dex):
    """Thread dédié aux scans secondaires lents — ne bloque pas le scan principal."""
    global _early_tokens_buffer
    offset = 0
    
    while True:
        try:
            tokens = []
            tokens += dex.fetch_pumpfun_new()
            tokens += dex.fetch_dexscreener_new_pairs()
            tokens += dex.fetch_new_tokens()
            tokens += dex.fetch_pump_mints()
            tokens += dex.fetch_pumpfun_tokens()
            tokens += dex.fetch_raydium_pools()
            tokens += dex.fetch_pump_curve_completions()
            tokens += dex.fetch_sniper_buys()
            
            seen = set()
            unique_tokens = []
            for t in tokens:
                if t["address"] not in seen:
                    seen.add(t["address"])
                    unique_tokens.append(t)

            random.shuffle(tokens)
            
            with _early_tokens_lock:
                _early_tokens_buffer = unique_tokens

            print(f"Secondary scan: {len(unique_tokens)} unique tokens")

        except Exception as e:
            print("Secondary scan error:", e)
            
        time.sleep(5)


# =============================
# THREAD 1 : SCAN (toutes les 1s)
# =============================
def scan_loop(dex, scanner, grok, analyzer, trader, trade_queue):

    global _early_tokens_buffer

    last_secondary_scan = 0
    last_deep_scan = 0
    waiting_tokens = {}
    all_pairs_cache = []
    processed_this_session = set()
    last_session_clear = time.time() 

    while trader.bot_running:

        scan_start = time.time()

        early_tokens = []

        # ── WebSocket queue (instantané) ──
        while not dex.ws_queue.empty():
            try:
                early_tokens.append(dex.ws_queue.get_nowait())
            except:
                break
        
        with _early_tokens_lock:
            now = time.time()
            _early_tokens_buffer = [
                t for t in _early_tokens_buffer
                if now - t.get("_ts", now) < 60
            ]
            early_tokens += list(_early_tokens_buffer)
        

        # ── Deep scan toutes les 30s ──
        if time.time() - last_deep_scan > 30:
            all_pairs_cache, _ = dex.fetch_pairs()
            # ← AJOUTER : trending tokens
            trending = dex.fetch_trending_tokens()
            all_pairs_cache += trending
            
            # Mélanger pour varier
            random.shuffle(all_pairs_cache)

            last_deep_scan = time.time()
            print(f"Deep scan: {len(all_pairs_cache)} pairs total")

        all_pairs = list(all_pairs_cache)

        # ── New pools toutes les secondes ──
        new_pools = dex.fetch_new_pools()

        # Vérifier si un token en attente a maintenant une pool
        for pair in new_pools:
            address = pair["baseToken"]["address"]
            if address in waiting_tokens:
                try:
                    price = dex.get_real_price(address)
                    if price is None:
                        price = dex.get_birdeye_price(address)
                    if price:
                        symbol = waiting_tokens[address]["symbol"]
                        print("🚀 POOL DETECTED:", symbol)
                        trade_queue.put({
                            "mode": "X10",
                            "address": address,
                            "price": price,
                            "symbol": symbol,
                            "fast": True
                        })
                except:
                    pass
                del waiting_tokens[address]

        for pair in new_pools:
            address = pair["baseToken"]["address"]
            if address not in dex.seen_addresses:
                dex.seen_addresses.add(address)
                all_pairs.append(pair)

        # Nettoyer waiting_tokens trop vieux (> 30 min)
        for address in list(waiting_tokens):
            if time.time() - waiting_tokens[address]["detected_time"] > 1800:
                print("❌ Pool never appeared:", address)
                del waiting_tokens[address]

        print("Waiting tokens:", len(waiting_tokens))

        # ── Traitement early tokens ──
        for token in early_tokens[:50]:

            address = token["address"]
            source = token.get("symbol", "UNK")

            if address in dex.seen_addresses:
                continue
            if trader.traded_today(address):
                continue
            if trader.is_in_cooldown(address):
                continue

            # SNIPER : entrée directe sans analyse
            if source == "SNIPER":
                price = dex.get_real_price(address)
                if price is None:
                    price = dex.get_birdeye_price(address)
                if price is None:
                    continue

                real_symbol = dex.get_token_symbol(address)
                copied_from = token.get("copied_from", None)

                print("🔥 DIRECT SNIPER ENTRY:", address)
                trade_queue.put({
                    "mode": "X5",
                    "address": address,
                    "price": price,
                    "symbol": real_symbol,
                    "fast": True,
                    "copied_from": copied_from
                })
                dex.seen_addresses.add(address)
                continue

            # Préfiltre rapide
            dex_data = dex.fetch_dexscreener_data(address)

            if not dex_data:
                # Pas encore de pool — mettre en attente
                price = dex.get_real_price(address)
                if price is None:
                    price = dex.get_birdeye_price(address)
                if price is None:
                    if address not in waiting_tokens:
                        waiting_tokens[address] = {
                            "symbol": source,
                            "detected_time": time.time()
                        }
                        print("⏳ Waiting pool:", address)
                continue

            if dex_data["liquidity"] < 3000:
                continue
            if dex_data["buy_ratio"] < 0.50:
                continue
            if dex_data["volume_5m"] < 2000:
                continue

            slippage = dex.estimate_slippage(trader.trade_amount, dex_data["liquidity"])
            if slippage > 13:
                continue

            price = dex.get_real_price(address)
            if price is None:
                price = dex.get_birdeye_price(address)
            

            # FAST ENTRY pour sources rapides
            if source in ["PUMP-WS", "RAYDIUM", "PUMP-MINT", "PUMP-LIVE", "RAY", "PUMP"]:
                print(f"⚡ FAST ENTRY {source}:", address)
                trade_queue.put({
                    "mode": "X2",
                    "address": address,
                    "price": price,
                    "symbol": token.get("symbol", "FAST"),
                    "fast": True
                })
                dex.seen_addresses.add(address)
                continue

            # Sinon ajouter au pipeline normal
            pair = {
                "baseToken": {"address": address, "symbol": token.get("symbol", "UNK")},
                "priceUsd": str(price),
                "liquidity": {"usd": dex_data["liquidity"]},
                "volume": {"m5": dex_data["volume_5m"]},
                "txns": {"m5": {
                    "buys": int(dex_data["buy_ratio"] * 100),
                    "sells": int((1 - dex_data["buy_ratio"]) * 100)
                }},
                "fdv": dex_data["market_cap"]
            }
            all_pairs.append(pair)

        # ── Pipeline normal → Grok ──
        if not all_pairs:
            print("⚠ No pairs this cycle")
            elapsed = time.time() - scan_start
            time.sleep(max(0, 1.0 - elapsed))
            continue

        print(f"Total pairs: {len(all_pairs)}")

        now_ms = time.time() * 1000
        eligible_tokens = []

        for pair in all_pairs:

            token_data = dex.extract_token_data(pair)
            if not token_data:
                continue

            # Filtre âge paire (rejeter tokens > 2h = pump déjà passé)
            pair_created_at = pair.get("pairCreatedAt")
            if pair_created_at:
                age_pair_min = (now_ms - pair_created_at) / 60000
                if age_pair_min > 30:
                    continue
            

            slippage = dex.estimate_slippage(trader.trade_amount, token_data["liquidity"])
            if slippage > 13:
                continue

            if trader.traded_today(token_data["address"]):
                continue
            if trader.is_in_cooldown(token_data["address"]):
                continue
            if any(t.address == token_data["address"] for t in trader.active_trades):
                continue

            # hard_filters
            class TmpToken:
                pass
            t = TmpToken()
            t.market_cap = token_data["market_cap"]
            t.liquidity = token_data["liquidity"]
            t.volume_5m = token_data["volume_5m"]
            t.buy_ratio = token_data["buy_ratio"]
            t.top_holder_percent = 10
            t.age_minutes = token_data["age_minutes"]
            security = dex.security_cache.get(token_data["address"])
            if security:
                t.mint_disabled = security["mint_disabled"]
                t.freeze_disabled = security["freeze_disabled"]
            else:
                t.mint_disabled = True   # défaut optimiste
                t.freeze_disabled = True
                dex.prefetch_security_async(token_data["address"], analyzer)  # vérif en background
            t.risk_score = 0
            t.volume_spike = token_data["volume_5m"] > token_data["liquidity"]
            t.holder_growth = token_data["buy_ratio"] > 0.65

            if not scanner.hard_filters(t):
                print(f"  ❌ hard_filter failed: MC={t.market_cap} Liq={t.liquidity} Vol={t.volume_5m} Buy={t.buy_ratio} Age={t.age_minutes}")
                continue

            print(
                token_data["symbol"],
                "MC:", token_data["market_cap"],
                "Liq:", token_data["liquidity"],
                "Vol5m:", token_data["volume_5m"],
                "Buy:", token_data["buy_ratio"],
                "Age:", token_data["age_minutes"]
            )
            
            eligible_tokens.append(token_data)
            

            if time.time() - last_session_clear > 300:  # toutes les 5 minutes
                processed_this_session.clear()
                last_session_clear = time.time()
                print("🔄 processed_this_session cleared")

        print(f"Eligible tokens: {len(eligible_tokens)}")

        if eligible_tokens:
            eligible_tokens.sort(
                key=lambda x: x["volume_5m"] * x["buy_ratio"],
                reverse=True
            )
            top_tokens = eligible_tokens[:5]
            decisions = grok.analyze_tokens(top_tokens)

            for decision in decisions:
                if decision["decision"] == "WAIT":
                    # Recalculer le score sans Grok
                    for token in eligible_tokens:
                        if token["address"] == decision["address"]:
                            # score de base sans hype fields
                            base_score = 0
                            if 50000 <= token["market_cap"] <= 300000:
                                base_score += 20
                            if token["volume_5m"] > token["liquidity"] * 2:
                                base_score += 15
                            if token["buy_ratio"] > 0.65:
                                base_score += 15
                            if base_score >= 35:  # bon token même sans hype
                                decision["decision"] = "X2"  # forcer X2
                            else:
                                continue

                for token in eligible_tokens:
                    if token["address"] == decision["address"]:
                        trade_queue.put({
                            "mode": decision["decision"],
                            "address": token["address"],
                            "price": None,  # récupéré dans trade_loop
                            "symbol": token["symbol"],
                            "fast": False,
                            "token_data": token,
                            "decision": decision
                        })
                        break

        elapsed = time.time() - scan_start
        sleep_time = max(0, 1.0 - elapsed)
        print(f"⏱ Scan {elapsed:.2f}s | sleep {sleep_time:.2f}s")
        time.sleep(sleep_time)

# THREAD 2A : update des trades actifs — très rapide, toutes les 0.5s
def price_update_loop(dex, trader):
    while trader.bot_running:
        with trader._lock:
            trades_snapshot = list(trader.active_trades)

        for trade in trades_snapshot:
            dex_data = dex.get_trade_dex_data(trade.address)

            if not dex_data:
                trade.consecutive_failures = getattr(trade, 'consecutive_failures', 0) + 1
                if trade.consecutive_failures >= 5:
                    print("🚨 RUG CONFIRMED:", trade.address)
                    trader.update_trades(trade.address, 0.00000001)
                continue

            trade.consecutive_failures = 0

            if dex_data["liquidity"] <= 100:
                trader.update_trades(trade.address, 0.00000001)
                continue

            if dex.detect_liquidity_drain(trade.address, dex_data["liquidity"]):
                trader.update_trades(trade.address, 0.00000001)
                continue

            current_price = dex.get_birdeye_price(trade.address)
            if current_price is None:
                continue
            if current_price > trade.entry_price * 100:
                continue

            trader.update_trades(trade.address, float(current_price))

        time.sleep(0.5)


# THREAD 2B : traitement queue — peut prendre du temps, pas grave
def queue_loop(dex, scanner, analyzer, trader, trade_queue, curve):
    observing_tokens = {}
    while trader.bot_running:
        try:
            item = trade_queue.get(timeout=1)  # attend 1s max
        except:
            continue  # queue vide, recommence

        address = item["address"]
        print(f"🔍 Queue item: {address[:8]} mode={item['mode']}")

        if len(trader.active_trades) >= 4:
            print("❌ Max trades reached")
            continue
        if trader.capital_total < trader.trade_amount:
            print(f"❌ Not enough capital: {trader.capital_total}")
            continue
        if trader.traded_today(address):
            print(f"❌ Already traded today: {address[:8]}")
            continue
        if trader.is_in_cooldown(address):
            print(f"❌ In cooldown: {address[:8]}")
            continue
        if any(t.address == address for t in trader.active_trades):
            continue

        if address.startswith("0x"):
            print(f"❌ Not Solana token: {address[:8]}")
            continue

        if item["fast"]:
            price = item["price"]
            copied_from = item.get("copied_from", None)
            if price:
                trader.open_trade(item["mode"], address, float(price), item["symbol"], copied_from=copied_from)
            continue

        # Pipeline normal — appels RPC ici, pas grave car thread dédié
        token_data = item.get("token_data", {})
        decision = item.get("decision", {})

        class FinalToken:
            pass
        ft = FinalToken()
        ft.market_cap = token_data.get("market_cap", 0)
        ft.liquidity = token_data.get("liquidity", 0)
        ft.volume_5m = token_data.get("volume_5m", 0)
        ft.buy_ratio = token_data.get("buy_ratio", 0)
        ft.top_holder_percent = token_data.get("top_holder_percent", 10)
        ft.age_minutes = token_data.get("age_minutes", 30)
        ft.twitter_mentions = decision.get("twitter_mentions", 0)
        ft.volume_spike = decision.get("volume_spike", False)
        ft.holder_growth = decision.get("holder_growth", False)

        final_score = scanner.calculate_score(ft)
        print("Final score:", final_score)

        if final_score < 40:
            print(f"❌ Score too low: {final_score}")
            continue
        address = item["address"]

        dex.prefetch_security_async(address, analyzer)

        # Récupérer le prix actuel pour ajouter un snapshot
        current_price = dex.get_real_price(address)
        if current_price:
            curve.add_snapshot(
                address,
                current_price,
                token_data.get("volume_5m", 0),
                token_data.get("buy_ratio", 0)
            )

        # Pas encore assez de données — remettre dans la queue 
        if not curve.is_ready(address):
            first_seen = observing_tokens.get(address, time.time())
            observing_tokens[address] = first_seen
            
            elapsed = time.time() - first_seen
            snapshots = len(curve.price_history.get(address, []))
            print(f"⏳ Observing {address[:8]}: {snapshots}/{curve.MIN_SNAPSHOTS} snapshots ({int(elapsed)}s)")
            
            # Si observation > 3 minutes sans assez de snapshots → abandonner
            if elapsed > 300:
                print(f"❌ Observation timeout: {address[:8]}")
                curve.clear(address)
                del observing_tokens[address]
                continue
            trade_queue.put(item)  
            time.sleep(5)          
            continue               

        # Analyser la courbe
        curve_result = curve.analyze(address)
        print(f"📊 Curve {address[:8]}: {curve_result['pattern']} → {curve_result['verdict']} ({curve_result['reason']})")

        if curve_result["verdict"] == "REJECT":
            print(f"❌ Curve REJECT: {curve_result['reason']}")
            curve.clear(address)
            continue

        if curve_result["verdict"] == "WAIT":
            # Remettre dans la queue
            trade_queue.put(item)
            time.sleep(5)
            continue
        
        if address in observing_tokens:
            del observing_tokens[address]

        # ✅ verdict == BUY — continuer vers l'ouverture du trade
        curve.clear(address)

        security = dex.security_cache.get(address)

        if security is None:
            # Pas encore en cache — vérifier maintenant (rare)
            security = analyzer.check_mint_security(address)

        if not security or not security["mint_disabled"]:
            print(f"❌ Mint not disabled: {address[:8]}")
            dex.seen_addresses.add(address)  # ne plus retraiter
            continue

        if not security["freeze_disabled"]:
            print(f"⚠ Freeze authority active: {address[:8]} — skip")
            dex.seen_addresses.add(address)
            continue

        price = dex.get_real_price(address)
        if price is None:
            price = dex.get_birdeye_price(address)
        if price:
            trader.open_trade(
                item["mode"],
                address,
                float(price),
                item["symbol"]
            )
            dex.seen_addresses.add(address)
        else:
            print(f"❌ No price for {address[:8]}")

# =============================
# THREAD 3 : TELEGRAM
# =============================
def telegram_loop(trader):
    consecutive_errors = 0
    while trader.bot_running:
        try:
            trader.check_telegram_commands()
            consecutive_errors = 0  # reset si succès
        except Exception as e:
            consecutive_errors += 1
            print(f"⚠ Telegram error ({consecutive_errors}): {e}")
            
            # Si trop d'erreurs consécutives → attendre plus longtemps
            if consecutive_errors >= 5:
                print("🔄 Telegram reconnecting...")
                time.sleep(30)  # attendre 30s avant de réessayer
                consecutive_errors = 0
            else:
                time.sleep(5)
            continue
            
        time.sleep(2)


# =============================
# MAIN
# =============================
if __name__ == "__main__":

    dex = DexScanner()
    dex.start_pump_ws()
    dex.start_raydium_ws()
    scanner = ScannerEngine()
    grok = GrokEngine()
    analyzer = OnChainAnalyzer()
    trader = TradeManager(starting_capital=20, dex=dex)
    trade_queue = queue.Queue()
    curve = CurveAnalyzer()

    print("Starting ultra-fast scanner (1s mode)...\n")
    trader.telegram.send_message("🚀 Bot started (1s scan mode).")

    t_scan = threading.Thread(
        target=scan_loop,
        args=(dex, scanner, grok, analyzer, trader, trade_queue),
        daemon=True
    )

    t_secondary = threading.Thread(
        target=secondary_scan_loop,
        args=(dex,),
        daemon=True
    )
    t_secondary.start()

    t_price = threading.Thread(
    target=price_update_loop,
    args=(dex, trader),
    daemon=True
    )
    t_queue = threading.Thread(
        target=queue_loop,
        args=(dex, scanner, analyzer, trader, trade_queue, curve),
        daemon=True
    )

    
    t_telegram = threading.Thread(
        target=telegram_loop,
        args=(trader,),
        daemon=True
    )

    t_scan.start()
    t_price.start()
    t_queue.start()
    t_telegram.start()

    try:
        while trader.bot_running:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Bot stopped manually.")
        trader.telegram.send_message("🛑 Bot stopped manually (CTRL+C).")

    except Exception as e:
        print("Bot crashed:", str(e))
        trader.telegram.send_message(f"🚨 BOT CRASHED\nError: {e}")
        raise
    


        