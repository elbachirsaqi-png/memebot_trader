import random
import time
from dex_scanner import DexScanner
from grok_engine import GrokEngine

class Token:

    def __init__(self):

        self.name = f"TOKEN_{random.randint(1000,9999)}"
        self.market_cap = random.randint(10000, 500000)
        self.liquidity = random.randint(5000, 150000)
        self.volume_5m = random.randint(1000, 300000)
        self.buy_ratio = random.uniform(0.3, 0.95)
        self.top_holder_percent = random.uniform(5, 40)
        self.age_minutes = random.randint(1, 180)
        self.lp_locked = random.choice([True, True, True, False])  # 75% locked
        self.twitter_mentions = random.randint(0, 800)
        

        # Momentum probabilities
        self.volume_spike = random.random() < 0.3
        self.holder_growth = random.random() < 0.3

class ScannerEngine:

    def hard_filters(self, token):

        if token.market_cap < 20000 or token.market_cap > 2000000:
            return False

        liquidity_ratio = token.liquidity / token.market_cap

        if liquidity_ratio < 0.08:
            return False

        if token.liquidity < 10000:
            return False

        if token.volume_5m < 2000:
            return False

        if token.buy_ratio < 0.5:
            return False

        if token.top_holder_percent > 45:
            return False

        if token.age_minutes < 0.15:
            return False
        
        if token.age_minutes > 30:
            return False

        if not token.mint_disabled:
            return False

        if not token.freeze_disabled:
            token.risk_score += 1

        return True

    def calculate_score(self, token):

        score = 0

        # Market cap sweet spot
        if 50000 <= token.market_cap <= 300000:
            score += 20

        # Volume vs liquidity
        if token.volume_5m > token.liquidity * 2:
            score += 15

        # Strong buy pressure
        if token.buy_ratio > 0.65:
            score += 15

        # Volume spike
        if getattr(token, "volume_spike", False):
            score += 20

        # Holder growth
        if getattr(token, "holder_growth", False):
            score += 15

        # Twitter activity
        if getattr(token, "twitter_mentions", 0) > 100:
            score += 15

        return score


if __name__ == "__main__":

    dex = DexScanner()
    scanner = ScannerEngine()
    grok = GrokEngine()

    pairs = dex.fetch_pairs()

    print("Scanning real tokens...\n")

    for pair in pairs:

        token_data = dex.extract_token_data(pair)

        if not token_data:
            continue

        # Convert to Token-like object
        class RealToken:
            pass

        token = RealToken()
        token.name = token_data["name"]
        token.market_cap = token_data["market_cap"]
        token.liquidity = token_data["liquidity"]
        token.volume_5m = token_data["volume_5m"]
        token.buy_ratio = token_data["buy_ratio"]
        token.top_holder_percent = 20  # placeholder for now
        token.age_minutes = 10
        token.lp_locked = True
        token.twitter_mentions = 200
        token.volume_spike = token.volume_5m > token.liquidity
        token.holder_growth = True
        print(token.name, token.market_cap, token.liquidity, token.volume_5m, token.buy_ratio)

        shortlist = []

        for pair in pairs:

            token_data = dex.extract_token_data(pair)

            if not token_data:
                continue

            token = RealToken()
            token.name = token_data["name"]
            token.address = token_data["address"]
            token.market_cap = token_data["market_cap"]
            token.liquidity = token_data["liquidity"]
            token.volume_5m = token_data["volume_5m"]
            token.buy_ratio = token_data["buy_ratio"]

            # ⚠️ Remplace plus tard par vraies données on-chain
            token.top_holder_percent = 10
            token.age_minutes = 15
            token.mint_disabled = True
            token.freeze_disabled = True

            if scanner.hard_filters(token):

                score = scanner.calculate_score(token)

                if score >= 60:
                    shortlist.append({
                        "name": token.name,
                        "address": token.address,
                        "market_cap": token.market_cap,
                        "liquidity": token.liquidity,
                        "volume_5m": token.volume_5m,
                        "buy_ratio": token.buy_ratio,
                        "top_holder_percent": token.top_holder_percent,
                        "age_minutes": token.age_minutes,
                        "score": score
                    })

        # Limite à max 8 tokens
        shortlist = shortlist[:8]

        if shortlist:

            print("Shortlist sent to Grok:\n", shortlist)

            result = grok.analyze_tokens(shortlist)

            print("Grok Final Decision:", result)

        else:
            print("No eligible tokens.")