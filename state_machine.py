import time


class Trade:

    def __init__(self, mode, address, entry_price):
        self.address = address
        self.entry_price = entry_price
        self.current_price = entry_price
        self.mode = mode  # "X2", "X5", "X10"
        self.open_time = time.time()
        self.stop_loss_level = 0.6
        self.floor_level = None
        self.super_run_active = False
        self.near_target_hit = False
        self.max_multiple = 1
        self.consecutive_failures = 0

        self.start_time = time.time()

    # =========================
    # PUBLIC METHOD
    # =========================

    def update_price(self, price):
        if price <= 0:
            self.current_price = 0.00000001
        else:
            self.current_price = price
        self.multiple = self.current_price / self.entry_price
        self.update_max_price()
        self.update_floors()
        return self.evaluate_exit()

    # =========================
    # CORE LOGIC
    # =========================

    def update_max_price(self):
        # Met à jour le max multiple
        if self.multiple > self.max_multiple:
            self.max_multiple = self.multiple

        if self.mode == "X2" and self.max_multiple >= 1.9:
            self.near_target_hit = True

        if self.mode == "X5" and self.max_multiple >= 4.9:
            self.near_target_hit = True

        if self.mode == "X10" and self.max_multiple >= 9.9:
            self.near_target_hit = True

        if self.mode == "X5" and self.max_multiple >= 2:
            self.near_target_hit = False

        if self.mode == "X10" and self.max_multiple >= 5:
            self.near_target_hit = False

    def update_floors(self):

        # TP1 → sécuriser trade
        if self.max_multiple >= 1.2 and self.floor_level is None:
            self.floor_level = 1.0
        
        # Sécuriser à +50%
        if self.max_multiple >= 1.5:
            self.floor_level = 1.2  # lock +20%

        # X5 and X10 floor at 2x
        if self.mode in ["X5", "X10"]:
            if self.max_multiple >= 2:
                self.floor_level = 1.6  # lock +60%
        if self.max_multiple >= 3:
            self.floor_level = 2.2  # lock +120%

        # X10 additional floor at 5x
        if self.mode == "X10":
            if self.max_multiple >= 5:
                self.floor_level = 4
            if self.max_multiple >= 7:
                self.floor_level = 6.0
                
        # Super run activation
        if self.mode == "X10" and self.max_multiple >= 10:
            self.super_run_active = True

    def evaluate_exit(self):

        # 1️⃣ Stop loss
        if self.multiple <= self.stop_loss_level:
            return self.close_trade("STOP_LOSS")

        # 2️⃣ Timeout
        if time.time() - self.start_time > 3600:
            if self.multiple < 1.3:
                return self.close_trade("TIMEOUT_EXIT")

        # 3️⃣ BUY_X2 logic
        # X2 retracement logic
        if self.mode == "X2":

            # vrai TP
            if self.multiple >= 2:
                self.mode = "X5"
                self.near_target_hit = False
                print("🚀 Mode upgraded to X5")

            # retracement après near TP
            if self.near_target_hit and self.multiple <= 1.7:
                return self.close_trade("SELL_X2_PULLBACK")

        # 4️⃣ BUY_X5 logic
        if self.multiple >= 5:
            self.mode = "X10"
            self.near_target_hit = False
            print("🚀 Mode upgraded to X10")

            if self.near_target_hit and self.multiple <= 4:
                return self.close_trade("SELL_X5_PULLBACK")

        # 5️⃣ BUY_X10 logic before super run
        if self.mode == "X10":

            if self.multiple >= 10:
                self.super_run_active = True

            if self.near_target_hit and self.multiple <= 8:
                return self.close_trade("SELL_X10_PULLBACK")

        # 6️⃣ Super Run trailing
        if self.super_run_active:
            dynamic_floor = self.max_multiple * 0.7
            if self.multiple <= dynamic_floor:
                return self.close_trade("SELL_SUPER_RUN")

        # 7️⃣ Floor protection
        if self.floor_level:
            if self.multiple <= self.floor_level:
                return self.close_trade("SELL_FLOOR")

        return None

    # =========================
    # CLOSE TRADE
    # =========================

    def close_trade(self, reason):
        profit = ((self.current_price - self.entry_price) / self.entry_price) * 100

        result = {
            "mode": self.mode,
            "entry": self.entry_price,
            "exit": self.current_price,
            "profit_percent": round(profit, 2),
            "reason": reason
        }

        return result
