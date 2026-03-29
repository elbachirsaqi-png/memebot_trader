import requests
import json
import os
from dotenv import load_dotenv
load_dotenv()
import time


class GrokEngine:

    def __init__(self):
        self.api_key = os.getenv("GROK_API_KEY")

    def analyze_tokens(self, tokens):

        prompt = f"""
You are the decision engine of an automated Solana memecoin trading bot.

IMPORTANT: 
Tokens you receive have ALREADY passed:
- security checks
- on-chain checks
- hard filters

Your job:
Evaluate each token independently.

For EACH token return a decision:
- "X2"
- "X5"
- "X10"


---------------------------------------------------
SYSTEM CONTEXT (CRITICAL)

After your decision, the bot calculates a FINAL SCORE:

+20 if 50k <= market_cap <= 300k
+15 if volume_5m > liquidity * 2
+15 if buy_ratio > 0.65
+20 if volume_spike == true
+15 if holder_growth == true
+15 if twitter_mentions > 100

The bot opens a trade ONLY if FINAL_SCORE >= 60.

Be realistic and strict.

---------------------------------------------------
TRADE EXIT LOGIC (IMPORTANT FOR MODE SELECTION)

X2:
- Take profit at ~2x
- Or sell on pullback after near target (1.9 reached then drops to 1.7)

X5:
- Take profit at ~5x
- Or sell on pullback after near target (4.9 reached then drops to 4.0)

X10:
- Rare.
- Only for exceptional momentum.
- After 10x, trailing stop activates at 70% of max.

Global stop loss exists.

Do NOT choose X10 unless conditions are exceptional.

---------------------------------------------------
HOW TO EVALUATE TOKENS

Strong token conditions:
- buy_ratio >= 0.65 (strong)
- buy_ratio >= 0.75 (exceptional)
- volume_5m / liquidity >= 2 (strong)
- volume_5m / liquidity >= 3.5 (exceptional)
- liquidity >= 20k minimum
- liquidity >= 50k for X10
- top_holder_percent <= 30 preferred
- top_holder_percent <= 15 for X10
- age between 10 and 240 minutes preferred

---------------------------------------------------
HYPE FIELD RULES

You do NOT have real Twitter access.
You estimate hype from momentum.

twitter_mentions:
- Weak momentum: 0–80
- Strong momentum: 120–250
- Exceptional momentum: 250–500

volume_spike:
True ONLY if volume_5m is clearly abnormal relative to liquidity (>= 3x)

holder_growth:
True ONLY if:
- Strong buy_ratio
- Strong volume
- Age is not extremely old

---------------------------------------------------
MODE SELECTION RULES

Choose:

X2:
Good but not perfect momentum.

X5:
Strong momentum:
- buy_ratio >= 0.68
- volume/liquidity >= 2.5
- top_holder <= 30

X10:
ONLY if ALL:
- buy_ratio >= 0.75
- volume/liquidity >= 3.5
- liquidity >= 50k
- top_holder <= 15
- age <= 90

---------------------------------------------------
OUTPUT FORMAT (STRICT JSON ONLY)

Return a JSON array:

[
 {{
   "address": "token_address",
   "decision": "X2 | X5 | X10 | WAIT",
   "twitter_mentions": 0,
   "volume_spike": true,
   "holder_growth": true,
   "hype_score": 0
 }}
]

Rules:
- One object per token
- Address must match the token
- If decision is WAIT → still include the token
- No explanations
- No markdown
- No extra text

---------------------------------------------------
TOKENS:
{tokens}
"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "grok-4-fast-non-reasoning",  
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        url = "https://api.x.ai/v1/chat/completions"

        for attempt in range(3):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30  # ✅ 30s au lieu de 20s
                )

                if response.status_code != 200:
                    print("Grok status:", response.status_code)
                    time.sleep(1)
                    continue

                if not response.text:
                    print("Grok empty response")
                    time.sleep(1)
                    continue

                result = response.json()

                if not isinstance(result, dict):
                    time.sleep(1)
                    continue

                break

            except Exception as e:
                print("Grok request error:", e)
                time.sleep(1)

        else:
            return []  # ✅ liste vide, jamais un dict

        print("DEBUG API RESPONSE:", result)

        if "choices" not in result:
            return []  # ✅ liste vide

        decision_text = result["choices"][0]["message"]["content"]

        # Nettoyer les backticks markdown si Grok en ajoute
        decision_text = decision_text.strip()
        if decision_text.startswith("```"):
            decision_text = decision_text.split("```")[1]
            if decision_text.startswith("json"):
                decision_text = decision_text[4:]
        decision_text = decision_text.strip()

        try:
            decision_json = json.loads(decision_text)

            if isinstance(decision_json, dict):
                return [decision_json]  # ✅ toujours une liste

            if isinstance(decision_json, list):
                return decision_json

            return []  # ✅ fallback liste vide

        except:
            print("Grok JSON parse error:", decision_text[:200])
            return []  # ✅ liste vide
    
    