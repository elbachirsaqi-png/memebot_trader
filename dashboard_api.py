from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__, static_folder="dashboard_static")
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return send_from_directory("dashboard_static", "index.html")


@app.route("/api/stats")
def stats():
    conn = get_db()
    trades = conn.execute("SELECT * FROM trades ORDER BY timestamp DESC").fetchall()
    conn.close()

    if not trades:
        return jsonify({
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_profit": 0, "best_trade": 0, "worst_trade": 0,
            "avg_profit": 0, "capital_start": 20
        })

    profits = [t["profit_percent"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    return jsonify({
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_profit": round(sum(profits) / 100 * 5, 2),
        "best_trade": round(max(profits), 2),
        "worst_trade": round(min(profits), 2),
        "avg_profit": round(sum(profits) / len(profits), 2),
    })


@app.route("/api/trades")
def trades():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trades/by_day")
def trades_by_day():
    conn = get_db()
    rows = conn.execute("""
        SELECT 
            DATE(timestamp) as day,
            COUNT(*) as total,
            SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN profit_percent <= 0 THEN 1 ELSE 0 END) as losses,
            ROUND(SUM(profit_percent) / 100 * 5, 2) as profit_dollars,
            ROUND(AVG(profit_percent), 2) as avg_profit
        FROM trades
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trades/by_reason")
def trades_by_reason():
    conn = get_db()
    rows = conn.execute("""
        SELECT 
            reason,
            COUNT(*) as count,
            ROUND(AVG(profit_percent), 2) as avg_profit,
            SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END) as wins
        FROM trades
        GROUP BY reason
        ORDER BY count DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trades/by_hour")
def trades_by_hour():
    conn = get_db()
    rows = conn.execute("""
        SELECT 
            CAST(strftime('%H', timestamp) AS INTEGER) as hour,
            COUNT(*) as total,
            SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(profit_percent), 2) as avg_profit
        FROM trades
        GROUP BY hour
        ORDER BY hour
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trades/by_mode")
def trades_by_mode():
    conn = get_db()
    rows = conn.execute("""
        SELECT 
            mode,
            COUNT(*) as count,
            SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(profit_percent), 2) as avg_profit,
            ROUND(MAX(profit_percent), 2) as best
        FROM trades
        GROUP BY mode
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/equity_curve")
def equity_curve():
    conn = get_db()
    rows = conn.execute(
        "SELECT profit_percent, timestamp FROM trades ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()

    capital = 20.0
    curve = [{"timestamp": "Start", "capital": capital}]
    for r in rows:
        capital += (r["profit_percent"] / 100) * 5
        curve.append({"timestamp": r["timestamp"], "capital": round(capital, 2)})
    return jsonify(curve)


if __name__ == "__main__":
    os.makedirs("dashboard_static", exist_ok=True)
    print("Dashboard running on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
