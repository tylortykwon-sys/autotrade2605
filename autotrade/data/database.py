import sqlite3
import os
from pathlib import Path
from config.settings import DB_PATH


def get_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            date        TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            UNIQUE(ticker, date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategy_params (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            strategy    TEXT NOT NULL,
            params      TEXT,
            sharpe      REAL,
            mdd         REAL,
            win_rate    REAL,
            updated_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(ticker, strategy)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT,
            side         TEXT,
            price        REAL,
            quantity     INTEGER,
            amount       REAL,
            strategy     TEXT,
            pnl          REAL,
            pnl_pct      REAL,
            executed_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT,
            total_value     REAL,
            cash            REAL,
            positions       TEXT,
            daily_pnl       REAL,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')

    conn.commit()
    conn.close()
    print(f"[DB] 초기화 완료: {DB_PATH}")


def insert_market_data(rows: list[dict]):
    conn = get_connection()
    conn.executemany('''
        INSERT OR REPLACE INTO market_data
        (ticker, date, open, high, low, close, volume)
        VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
    ''', rows)
    conn.commit()
    conn.close()


def get_ohlcv(ticker: str, days: int = 200) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM market_data
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
    ''', (ticker, days))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows[::-1]


def insert_trade(trade: dict):
    conn = get_connection()
    conn.execute('''
        INSERT INTO trades (ticker, side, price, quantity, amount, strategy, pnl, pnl_pct)
        VALUES (:ticker, :side, :price, :quantity, :amount, :strategy, :pnl, :pnl_pct)
    ''', trade)
    conn.commit()
    conn.close()


def save_portfolio_snapshot(snapshot: dict):
    conn = get_connection()
    conn.execute('''
        INSERT INTO portfolio_snapshots (snapshot_date, total_value, cash, positions, daily_pnl)
        VALUES (:snapshot_date, :total_value, :cash, :positions, :daily_pnl)
    ''', snapshot)
    conn.commit()
    conn.close()


def get_trades(ticker: str = None, limit: int = 100) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    if ticker:
        cursor.execute(
            'SELECT * FROM trades WHERE ticker=? ORDER BY executed_at DESC LIMIT ?',
            (ticker, limit)
        )
    else:
        cursor.execute(
            'SELECT * FROM trades ORDER BY executed_at DESC LIMIT ?',
            (limit,)
        )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
