from grok_engine import GrokEngine

grok = GrokEngine()

tokens = [
    {
        "name": "TEST1",
        "address": "abc123",
        "market_cap": 250000,
        "liquidity": 40000,
        "volume_5m": 9000,
        "buy_ratio": 0.7,
        "top_holder_percent": 8,
        "age_minutes": 15,
        "score": 85
    },
    {
        "name": "TEST2",
        "address": "def456",
        "market_cap": 150000,
        "liquidity": 20000,
        "volume_5m": 4000,
        "buy_ratio": 0.55,
        "top_holder_percent": 18,
        "age_minutes": 25,
        "score": 70
    }
]

result = grok.analyze_tokens(tokens)

print("Grok Response:")
print(result)*