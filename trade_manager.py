from state_machine import Trade
from database import TradeDatabase
import time
from telegram_bot import TelegramBot
from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT")

class TradeManager:

    def __init__(self, starting_capital=20, dex=None):
        self.active_trades = []
        self.db = TradeDatabase()
        self.dex = dex
        self.closed_trades_session = []

        self.capital_total = starting_capital

        self.trade_amount = 5  # 5$ par trade

        self.cooldowns = {}  # address -> timestamp

        self.token_trade_history = {}

        self.telegram = TelegramBot(TOKEN, CHAT_ID)
        self.bot_running = True

    def traded_today(self, address):

        if address not in self.token_trade_history:
            return False

        last_trade = self.token_trade_history[address]

        # 1 heure
        if time.time() - last_trade < 3600:
            return True

        return False
   
    def open_trade(self, mode, address, entry_price, symbol=None):

        # 🚫 Empêcher double trade actif
        for trade in self.active_trades:
            if trade.address == address:
                print("Trade already active for this token.")
                return

        if len(self.active_trades) >= 4:
            print("Max active trades reached.")
            return

        if self.capital_total < self.trade_amount:
            print("Not enough capital.")
            return

        self.capital_total -= self.trade_amount

        trade = Trade(mode, address, entry_price)
        trade.symbol = symbol
        self.active_trades.append(trade)

        print(f"Trade opened: {address} | Mode: {mode}")
        self.telegram.send_message(
            f"📈 OPEN TRADE\n"
            f"Coin: {symbol}\n"
            f"Address: {address}\n"
            f"Entry: {entry_price}"
        )
        self.token_trade_history[address] = time.time()

    def update_all_active_trades(self, price_fetcher):

        closed_trades = []

        for trade in self.active_trades:

            try:
                price = price_fetcher(trade.address)

                if price is None:
                    continue

                result = trade.update_price(price)

                if result:

                    print("Trade closed:", result)

                    profit_percent = result["profit_percent"]
                    fee = self.trade_amount * 0.003   # 0.3% swap
                    dollar_profit = (profit_percent / 100) * self.trade_amount - fee

                    self.capital_total += self.trade_amount + dollar_profit

                    self.db.log_trade(
                        result["mode"],
                        result["entry"],
                        result["exit"],
                        result["profit_percent"],
                        result["reason"]
                    )

                    self.closed_trades_session.append(result)

                    closed_trades.append(trade)

            except Exception as e:
                print("Error updating trade:", e)

        for trade in closed_trades:
            self.active_trades.remove(trade)
        
    def update_trades(self, address, price):

        closed_trades = []

        for trade in self.active_trades:
            if trade.address != address:
                continue

            result = trade.update_price(price)

            if result:

                print("Trade closed:", result)
                self.telegram.send_message(
                    f"📉 CLOSE TRADE\n"
                    f"Coin: {getattr(trade, 'symbol', 'UNK')}\n"
                    f"Profit: {round(result['profit_percent'],2)}%\n"
                    f"Reason: {result['reason']}"
                )

                # --- Calcul profit en $ ---
                profit_percent = result["profit_percent"]
                fee = self.trade_amount * 0.003   # 0.3% swap
                dollar_profit = (profit_percent / 100) * self.trade_amount - fee

                # 🔥 détecter sniper wallets si gros profit
                if profit_percent > 200:
                    self.dex.detect_early_buyers(trade.address)

                # --- Mise à jour capital ---
                self.capital_total += self.trade_amount + dollar_profit

                print(f"Capital now: {round(self.capital_total, 2)}$")

                # --- Log en base ---
                self.db.log_trade(
                    result["mode"],
                    result["entry"],
                    result["exit"],
                    result["profit_percent"],
                    result["reason"]
                )

                # --- Ajouter à session ---
                self.closed_trades_session.append(result)
                
                # --- Cooldown intelligent ---
                cooldown_duration = 0
                reason = result["reason"]

                if reason == "STOP_LOSS":
                    cooldown_duration = 45 * 60  # 45 min

                elif reason == "SELL_FLOOR":
                    cooldown_duration = 20 * 60  # 20 min

                if cooldown_duration > 0:
                    self.cooldowns[trade.address] = time.time() + cooldown_duration
                
                closed_trades.append(trade)

        # --- Supprimer trades fermés ---
        for trade in closed_trades:
            self.active_trades.remove(trade)

        # --- Résumé si 4 trades fermés ---
        if len(self.closed_trades_session) >= 4:
            self.print_session_summary()
            self.closed_trades_session.clear()

    # =========================
    # COOLDOWN SYSTEM
    # =========================

    def is_in_cooldown(self, address):

        if address not in self.cooldowns:
            return False

        if time.time() > self.cooldowns[address]:
            del self.cooldowns[address]
            return False

        return True
    
    # =========================
    # SESSION SUMMARY
    # =========================

    def print_session_summary(self):

        total_profit_percent = 0
        total_profit_dollars = 0
        wins = 0
        losses = 0

        for trade in self.closed_trades_session:
            percent = trade["profit_percent"]
            total_profit_percent += percent

            dollar_profit = (percent / 100) * self.trade_amount
            total_profit_dollars += dollar_profit

            if percent > 0:
                wins += 1
            else:
                losses += 1

        print("\n===== SESSION SUMMARY =====")
        print(f"Trades closed: {len(self.closed_trades_session)}")
        print(f"Wins: {wins}")
        print(f"Losses: {losses}")
        print(f"Total Profit %: {round(total_profit_percent, 2)}%")
        print(f"Total Profit $: {round(total_profit_dollars, 2)}$")
        print("===========================\n")

        summary_text = (
            f"📊 SESSION SUMMARY\n"
            f"Trades: {len(self.closed_trades_session)}\n"
            f"Wins: {wins}\n"
            f"Losses: {losses}\n"
            f"Profit $: {round(total_profit_dollars, 2)}$\n"
            f"Capital: {round(self.capital_total, 2)}$"
        )

        self.telegram.send_message(summary_text)

    def send_open_trades(self):

        if not self.active_trades:
            self.telegram.send_message("📭 No active trades.")
            return

        msg = "📊 OPEN TRADES:\n\n"

        for trade in self.active_trades:

            duration = (time.time() - trade.open_time) / 60

            # calcul pnl si current_price existe
            if trade.current_price:
                pnl_percent = ((trade.current_price - trade.entry_price) / trade.entry_price) * 100
            else:
                pnl_percent = 0

            msg += (
                f"🔹 {trade.address[:6]}...\n"
                f"Mode: {trade.mode}\n"
                f"Entry: {trade.entry_price:.8f}\n"
                f"PnL: {pnl_percent:.2f}%\n"
                f"Minutes: {duration:.1f}\n\n"
            ) 

        msg += f"💰 Capital: {round(self.capital_total,2)}$"

        self.telegram.send_message(msg)

    def check_telegram_commands(self):

        updates = self.telegram.get_updates()

        for update in updates:

            if "message" not in update:
                continue

            text = update["message"].get("text", "")

            if text == "/stop":
                self.telegram.send_message("🛑 Bot stopped.")
                self.bot_running = False

            elif text == "/status":
                self.telegram.send_message(
                    f"💰 Capital: {round(self.capital_total,2)}$\n"
                    f"📈 Active trades: {len(self.active_trades)}"
                )

            elif text == "/resume":
                self.telegram.send_message("▶ Bot resumed.")
                self.bot_running = True

            elif text == "/trades":
                self.send_open_trades()