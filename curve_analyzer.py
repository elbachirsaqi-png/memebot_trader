import time
import collections


class CurveAnalyzer:
    """
    Analyse le comportement du prix avant d'ouvrir un trade.
    Collecte des snapshots de prix et détecte les patterns.
    """

    def __init__(self):
        # address -> deque de (timestamp, price, volume)
        self.price_history = {}
        self.SNAPSHOT_INTERVAL = 15   # 1 snapshot toutes les 20s
        self.MIN_SNAPSHOTS = 3       # minimum 4 points = ~80s d'observation
        self.MAX_SNAPSHOTS = 10       # garder max 10 points

    # =========================
    # AJOUTER UN SNAPSHOT
    # =========================

    def add_snapshot(self, address, price, volume_5m, buy_ratio):
        """Appelé depuis scan_loop à chaque cycle."""

        now = time.time()

        if address not in self.price_history:
            self.price_history[address] = collections.deque(maxlen=self.MAX_SNAPSHOTS)

        history = self.price_history[address]

        # Ne pas ajouter si dernier snapshot trop récent
        if history and now - history[-1]["ts"] < self.SNAPSHOT_INTERVAL:
            return

        history.append({
            "ts": now,
            "price": price,
            "volume_5m": volume_5m,
            "buy_ratio": buy_ratio
        })

    def is_ready(self, address):
        """Vrai si on a assez de données pour analyser."""
        if address not in self.price_history:
            return False
        return len(self.price_history[address]) >= self.MIN_SNAPSHOTS

    def clear(self, address):
        """Nettoyer après ouverture ou rejet du trade."""
        if address in self.price_history:
            del self.price_history[address]

    # =========================
    # ANALYSE PRINCIPALE
    # =========================

    def analyze(self, address):
        """
        Retourne un dict avec le verdict et les métriques.
        {
            "verdict": "BUY" | "WAIT" | "REJECT",
            "pattern": "ACCUMULATION" | "PUMP_DUMP" | "FLAT" | "RECOVERY",
            "confidence": 0-100,
            "reason": "..."
        }
        """

        if not self.is_ready(address):
            return {"verdict": "WAIT", "pattern": "LOADING", "confidence": 0, "reason": "Not enough data"}

        history = list(self.price_history[address])
        prices = [s["price"] for s in history]
        volumes = [s["volume_5m"] for s in history]
        buy_ratios = [s["buy_ratio"] for s in history]

        # ── Métriques de base ──
        price_first = prices[0]
        price_last = prices[-1]
        price_max = max(prices)
        price_min = min(prices)

        change_total = (price_last - price_first) / price_first  # variation totale
        change_from_peak = (price_last - price_max) / price_max   # chute depuis le max
        volatility = (price_max - price_min) / price_min           # amplitude

        avg_buy_ratio = sum(buy_ratios) / len(buy_ratios)
        buy_ratio_trend = buy_ratios[-1] - buy_ratios[0]  # positif = buy ratio qui monte

        volume_trend = (volumes[-1] - volumes[0]) / volumes[0] if volumes[0] > 0 else 0

        # ── Détection patterns ──

        # REVERSAL — chute puis début de reprise (même petit +3%)
        if len(prices) >= 3:
            # Trouver le point bas récent
            min_idx = prices.index(min(prices[-3:]))  # bas dans les 3 derniers points
            price_at_bottom = prices[-(3 - min_idx)] if min_idx < 3 else prices[-2]
            
            # La courbe était en descente
            was_declining = prices[-3] > prices[-2] or prices[-2] > price_at_bottom
            
            # Elle commence à remonter
            recovery_pct = (prices[-1] - min(prices[-3:])) / min(prices[-3:])
            
            if was_declining and recovery_pct >= 0.03 and buy_ratio_trend >= 0:
    
                # Vérifier que ce n'est pas un pump & dump déguisé
                # Si le prix est encore très loin du peak initial, c'est un vrai reversal
                still_below_peak = prices[-1] < price_max * 0.85
                
                # Buy ratio actuel doit être correct
                current_buy_ratio = buy_ratios[-1]
                
                if current_buy_ratio >= 0.55 and (still_below_peak or change_from_peak > -0.15):
                    return {
                        "verdict": "BUY",
                        "pattern": "REVERSAL",
                        "confidence": 80,
                        "reason": f"Reversal +{round(recovery_pct*100,1)}% | buy_ratio={round(current_buy_ratio,2)}"
                    }
        
        # PUMP & DUMP — prix monté puis rechute > 30%
        if price_max > price_first * 1.3 and change_from_peak < -0.25:
            return {
                "verdict": "REJECT",
                "pattern": "PUMP_DUMP",
                "confidence": 90,
                "reason": f"Pump & dump détecté — chute {round(change_from_peak*100,1)}% depuis le peak"
            }

        # FLAT — aucun mouvement significatif
        if volatility < 0.05 and abs(change_total) < 0.03:
            return {
                "verdict": "REJECT",
                "pattern": "FLAT",
                "confidence": 80,
                "reason": "Token trop flat — pas de momentum"
            }

        # DUMP CONTINU — prix baisse sans rebond
        if change_total < -0.15 and buy_ratio_trend < 0:
            return {
                "verdict": "REJECT",
                "pattern": "DUMP",
                "confidence": 85,
                "reason": f"Dump continu {round(change_total*100,1)}% sans rebond"
            }

        # RECOVERY — prix a chuté puis remonte (bon signal)
        peak_idx = prices.index(price_max)
        if peak_idx < len(prices) - 2:  # peak n'est pas récent
            recovery = (price_last - price_min) / price_min
            if recovery > 0.15 and buy_ratio_trend > 0.05:
                return {
                    "verdict": "BUY",
                    "pattern": "RECOVERY",
                    "confidence": 75,
                    "reason": f"Recovery +{round(recovery*100,1)}% avec buy ratio en hausse"
                }

        # ACCUMULATION — prix monte progressivement avec volume croissant
        prices_increasing = all(prices[i] <= prices[i+1] for i in range(len(prices)-2))
        if prices_increasing and volume_trend > 0.1 and avg_buy_ratio > 0.62:
            return {
                "verdict": "BUY",
                "pattern": "ACCUMULATION",
                "confidence": 85,
                "reason": f"Accumulation propre +{round(change_total*100,1)}% vol+{round(volume_trend*100,1)}%"
            }

        # MOMENTUM — forte hausse récente avec buy ratio élevé
        recent_change = (prices[-1] - prices[-2]) / prices[-2] if len(prices) >= 2 else 0
        if change_total > 0.1 and avg_buy_ratio > 0.65 and recent_change > 0:
            return {
                "verdict": "BUY",
                "pattern": "MOMENTUM",
                "confidence": 70,
                "reason": f"Momentum +{round(change_total*100,1)}% buy_ratio={round(avg_buy_ratio,2)}"
            }

        # Sinon — continuer à observer
        return {
            "verdict": "WAIT",
            "pattern": "OBSERVING",
            "confidence": 50,
            "reason": "Pattern pas encore clair"
        }