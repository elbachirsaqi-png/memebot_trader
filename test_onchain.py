from dex_scanner import DexScanner
from onchain_analyzer import OnChainAnalyzer


dex = DexScanner()
analyzer = OnChainAnalyzer()

pairs = dex.fetch_pairs()

for pair in pairs[:3]:

    token = dex.extract_token_data(pair)

    if not token:
        continue

    print("\nToken:", token["name"])
    print("Address:", token["address"])

    percent = analyzer.get_top_holder_percent(token["address"])

    print("Top holder %:", percent)
    age = analyzer.get_token_age_minutes(token["address"])
    print("Token age (minutes):", age)

    security = analyzer.check_mint_security(token["address"])
    print("Mint security:", security)