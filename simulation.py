import random
from trade_manager import TradeManager


BUY_TAX = 0.05
SELL_TAX = 0.05
RUG_PROBABILITY = 0.1
FRONTRUN_PROBABILITY = 0.05
MAX_SLIPPAGE = 0.13
MAX_SPREAD = 0.12


def realistic_price_path():

    price = 1.0
    path = []

    for _ in range(50):

        scenario = random.random()

        # 70% dump
        if scenario < 0.7:
            move = random.uniform(-0.3, -0.05)

        # 20% flat
        elif scenario < 0.9:
            move = random.uniform(-0.02, 0.02)

        # 9% pump
        elif scenario < 0.99:
            move = random.uniform(0.05, 0.3)

        # 1% super run
        else:
            move = random.uniform(0.5, 2.0)

        price = max(0.1, price * (1 + move))
        path.append(round(price, 2))

    # Rug event
    if random.random() < RUG_PROBABILITY:
        path.append(round(price * 0.2, 2))

    return path


def apply_slippage(price):
    slip = random.uniform(0, MAX_SLIPPAGE)
    return price * (1 + slip)


if __name__ == "__main__":

    manager = TradeManager()
    modes = ["X2", "X5", "X10"]

    trade_count = 0

    while trade_count < 100:

        # Spread simulation
        spread = random.uniform(0, 0.2)
        if spread > MAX_SPREAD:
            trade_count += 1
            continue

        # Front-run fail
        if random.random() < FRONTRUN_PROBABILITY:
            trade_count += 1
            continue

        manager.open_trade(random.choice(modes))

        path = realistic_price_path()

        for price in path:

            # Apply slippage
            real_price = apply_slippage(price)

            manager.update_trades(real_price)

        trade_count += 1

    print("\nFinal capital:", round(manager.capital_total, 2))