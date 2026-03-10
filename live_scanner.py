import time
import json
from dex_scanner import DexScanner
from scanner_engine import ScannerEngine
from grok_engine import GrokEngine
from trade_manager import TradeManager
from onchain_analyzer import OnChainAnalyzer


def save_watchlist(tokens):
    with open("watchlist.json", "w") as f:
        json.dump(tokens, f, indent=4)


if __name__ == "__main__":

    dex = DexScanner()
    dex.start_pump_ws()
    dex.start_raydium_ws()
    scanner = ScannerEngine()
    grok = GrokEngine()
    analyzer = OnChainAnalyzer()

    trader = TradeManager(starting_capital=20, dex=dex)

    print("Starting live scanner...\n")
    trader.telegram.send_message("🚀 Bot started.")

    try:
        last_scan_time = 0
        last_deep_scan = 0

        waiting_tokens = {}

        while trader.bot_running:
            
            trader.check_telegram_commands()

            
            # 🔁 1) UPDATE TRADES EVERY ~5 SECONDS (1 quote par trade)
            if trader.active_trades:
                for trade in list(trader.active_trades):

                    # récupérer data Dexscreener
                    dex_data = dex.fetch_dexscreener_data(trade.address)

                    if dex_data:

                        liquidity = dex_data["liquidity"]

                        # 🔥 rug detection
                        if dex.detect_liquidity_drain(trade.address, liquidity):

                            print("🚨 RUG DETECTED:", trade.address)

                            trader.update_trades(trade.address, 0.00000001)
                            continue

                    # prix réel swapable
                    current_price = dex.get_swap_price(trade.address)

                    if current_price is not None:
                        trader.update_trades(trade.address, float(current_price))

            # 🔎 Scan rapide toutes les 2 secondes
            if time.time() - last_scan_time < 2:
                time.sleep(2)
                continue

            last_scan_time = time.time()

            early_tokens = dex.fetch_new_tokens()

            pump_ws = dex.ws_token
            dex.ws_token = None
            pump_mints = dex.fetch_pump_mints()
            pump_tokens = dex.fetch_pumpfun_tokens()
            ray_tokens = dex.fetch_raydium_pools()
            pump_complete = dex.fetch_pump_curve_completions()
            sniper_tokens = dex.fetch_sniper_buys()

            if pump_ws:
                early_tokens.append(pump_ws)
            early_tokens += pump_mints
            early_tokens += pump_tokens
            early_tokens += ray_tokens
            early_tokens += pump_complete
            early_tokens += sniper_tokens

            # Jupiter + Dex scan seulement toutes les 30s
            if time.time() - last_deep_scan > 30:

                all_pairs, new_pairs = dex.fetch_pairs()

                last_deep_scan = time.time()

            else:
                all_pairs = []
                new_pairs = []

            # 🆕 SCAN DES NOUVELLES POOLS DEX
            new_pools = dex.fetch_new_pools()

            # 🔥 vérifier si un token en attente vient d'avoir une pool

            for pair in new_pools:

                address = pair["baseToken"]["address"]

                if address in waiting_tokens:

                    try:
                        price = dex.get_swap_price(address)
                    except:
                        continue

                    symbol = waiting_tokens[address]["symbol"]

                    print("🚀 POOL DETECTED:", symbol)

                    trader.open_trade(
                        mode="X10",
                        address=address,
                        entry_price=price,
                        symbol=symbol
                    )

                    capital_full = (
                        len(trader.active_trades) >= 4 or
                        trader.capital_total < trader.trade_amount
                    )
                    del waiting_tokens[address]

            for pair in new_pools:

                address = pair["baseToken"]["address"]

                if address in dex.seen_addresses:
                    continue

                dex.seen_addresses.add(address)

                all_pairs.append(pair)
            
            # 🔥 Ajouter early tokens au pipeline
            for token in early_tokens[:30]:

                address = token["address"]

                if address in dex.seen_addresses:
                    continue

                price = dex.get_swap_price(address)

                # si la pool n'existe pas encore
                if price is None:

                    if address not in waiting_tokens:

                        waiting_tokens[address] = {
                            "symbol": token.get("symbol", "UNK"),
                            "detected_time": time.time()
                        }

                        print("⏳ Waiting pool:", address)

                    continue

                # 🔥 COPY TRADE SNIPER
                if token.get("symbol") == "SNIPER":

                    dex_data = dex.fetch_dexscreener_data(address)

                    if not dex_data:
                        continue

                    if dex_data["liquidity"] < 20000:
                        continue

                    print("🔥 SNIPER BUY DETECTED:", address)

                    trader.open_trade(
                        mode="X5",
                        address=address,
                        entry_price=float(price),
                        symbol="SNIPER"
                    )

                    capital_full = (
                        len(trader.active_trades) >= 4 or
                        trader.capital_total < trader.trade_amount
                    )
                    dex.seen_addresses.add(address)
                    continue

                if trader.traded_today(address):
                    continue

                dex_data = dex.fetch_dexscreener_data(address)

                if not dex_data:
                    continue

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

                all_pairs.append(pair)
                dex.seen_addresses.add(address)

            # nettoyer les tokens qui attendent trop longtemps
            for address in list(waiting_tokens):

                if time.time() - waiting_tokens[address]["detected_time"] > 1800:

                    print("❌ Pool never appeared:", address)

                    del waiting_tokens[address]
            print("Waiting tokens:", len(waiting_tokens))        

            if not all_pairs:
                print("⚠ No pairs returned from Dex")
                time.sleep(5)
                continue

            # 🔒 3) SI CAPITAL PLEIN → on skip seulement l'ouverture
            capital_full = (
                len(trader.active_trades) >= 4 or
                trader.capital_total < trader.trade_amount
            )
            

            print("Total pairs:", len(all_pairs))
            print("New pairs:", len(new_pairs))

            eligible_tokens = []

            for pair in all_pairs:

                token_data = dex.extract_token_data(pair)
                if not token_data:
                    continue

                class RealToken:
                    pass

                token = RealToken()
                token.name = token_data["name"]
                token.symbol = token_data["symbol"]
                token.market_cap = token_data["market_cap"]
                token.liquidity = token_data["liquidity"]
                token.volume_5m = token_data["volume_5m"]
                token.buy_ratio = token_data["buy_ratio"]
                token.volume_spike = False
                token.holder_growth = False
                token.address = token_data["address"]
                
                # 🔥 Pump detection
                if token.volume_5m > token.liquidity:
                    token.volume_spike = True

                if token.buy_ratio > 0.65:
                    token.holder_growth = True
                
                # --- Pre-filter léger avant RPC ---
                if token.market_cap < 30000 or token.market_cap > 2000000:
                    continue

                if token.liquidity < 10000:
                    continue

                security = analyzer.check_mint_security(token.address)

                if not security:
                    continue

                token.mint_disabled = security["mint_disabled"]
                token.freeze_disabled = security["freeze_disabled"]
                token.risk_score = getattr(token, "risk_score", 0)

                if not token.freeze_disabled:
                    token.risk_score += 1

                # Ici on ajoute on-chain si dispo
                token.age_minutes = token_data.get("age_minutes", 0)


                top_holder = analyzer.get_top_holder_percent(token.address)

                if top_holder is None:
                    continue

                token.top_holder_percent = top_holder

                age = analyzer.get_token_age_minutes(token.address)

                if age is None:
                    continue

                token.age_minutes = age

                # 🔒 éviter les rugs ultra récents
                if token.age_minutes < 0.15:
                    continue

                # --- Slippage protection ---
                slippage = dex.estimate_slippage(
                    trader.trade_amount,
                    token.liquidity
                )

                if slippage > 13:
                    continue

                # --- Spread estimation ---
                if token.liquidity < 20000:
                    continue
                
                print(
                    token.symbol,
                    "MC:", token.market_cap,
                    "Liq:", token.liquidity,
                    "Vol5m:", token.volume_5m,
                    "Buy:", token.buy_ratio,
                    "TopH:", token.top_holder_percent,
                    "Age:", token.age_minutes
                )

                if scanner.hard_filters(token):
                    if any(t.address == token.address for t in trader.active_trades):
                        continue
                    if trader.traded_today(token.address):
                        continue
                    if trader.is_in_cooldown(token.address):
                        continue

                    eligible_tokens.append({
                        "name": token.name,
                        "symbol": token.symbol,
                        "address": token.address,
                        "market_cap": token.market_cap,
                        "liquidity": token.liquidity,
                        "volume_5m": token.volume_5m,
                        "buy_ratio": token.buy_ratio,
                        "top_holder_percent": token.top_holder_percent,
                        "age_minutes": token.age_minutes
                    })      

            print(f"Eligible tokens: {len(eligible_tokens)}")

            if not eligible_tokens:
                print("No valid tokens.")
            else:
                decisions = grok.analyze_tokens(eligible_tokens)

                valid_decisions = []

                for decision in decisions:

                    if decision["decision"] == "WAIT":
                        decision["decision"] = "X2"

                    selected_token = None

                    for token in eligible_tokens:
                        if token["address"] == decision["address"]:
                            selected_token = token
                            break

                    if not selected_token:
                        continue

                    valid_decisions.append((selected_token, decision))


                for token, decision in valid_decisions:

                    if capital_full:
                        print("Capital full. Skipping new trades.")
                        continue

                    selected_token = token

                    class FinalToken:
                        pass

                    final_token = FinalToken()

                    final_token.market_cap = selected_token["market_cap"]
                    final_token.liquidity = selected_token["liquidity"]
                    final_token.volume_5m = selected_token["volume_5m"]
                    final_token.buy_ratio = selected_token["buy_ratio"]
                    final_token.top_holder_percent = selected_token["top_holder_percent"]
                    final_token.age_minutes = selected_token["age_minutes"]

                    final_token.twitter_mentions = decision.get("twitter_mentions", 0)
                    final_token.volume_spike = decision.get("volume_spike", False)
                    final_token.holder_growth = decision.get("holder_growth", False)

                    print(
                        "Hype:",
                        "Twitter:", final_token.twitter_mentions,
                        "Spike:", final_token.volume_spike,
                        "Growth:", final_token.holder_growth
                    )

                    final_score = scanner.calculate_score(final_token)

                    print("Final score:", final_score)

                    if final_score >= 40:

                        current_price = dex.get_swap_price(selected_token["address"])

                        if current_price:
                            trader.open_trade(
                                mode=decision["decision"],
                                address=selected_token["address"],
                                entry_price=current_price,
                                symbol=selected_token["symbol"]
                            )
                            capital_full = (
                                len(trader.active_trades) >= 4 or
                                trader.capital_total < trader.trade_amount
                            )
                        time.sleep(5)


    except KeyboardInterrupt:
        print("Bot stopped manually.")
        trader.telegram.send_message("🛑 Bot stopped manually (CTRL+C).")

    except Exception as e:
        print("Bot crashed:", str(e))
        trader.telegram.send_message(
            f"🚨 BOT CRASHED\nError: {str(e)}"
        )
        raise

    


        