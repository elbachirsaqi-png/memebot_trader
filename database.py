import sqlite3
from datetime import datetime


class TradeDatabase:

    def __init__(self, db_name="trades.db"):
        self.conn = sqlite3.connect("trades.db", check_same_thread=False)
        self.create_table()

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT,
            entry_price REAL,
            exit_price REAL,
            profit_percent REAL,
            reason TEXT,
            timestamp TEXT
        )
        """
        self.conn.execute(query)
        self.conn.commit()

    def log_trade(self, mode, entry, exit_price, profit, reason):
        query = """
        INSERT INTO trades (mode, entry_price, exit_price, profit_percent, reason, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(query, (
            mode,
            entry,
            exit_price,
            profit,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        self.conn.commit()