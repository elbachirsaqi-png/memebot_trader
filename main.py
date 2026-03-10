from trade_manager import TradeManager


if __name__ == "__main__":

    manager = TradeManager()

    # Ouvre 4 trades différents
    manager.open_trade("X2")
    manager.open_trade("X5")
    manager.open_trade("X10")
    manager.open_trade("X10")

    price_movements = [1.2, 2.1, 1.6, 0.6, 2.1, 1.6, 0.6, 12, 20, 13]

    for price in price_movements:
        print("Price update:", price)
        manager.update_trades(price)