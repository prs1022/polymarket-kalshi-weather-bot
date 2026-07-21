#!/usr/bin/env python3
"""Check trades for market 1784103000."""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('tradingbot.db')
cursor = conn.cursor()

# Query trades
print("\n=== TRADES for market_ticker='1784103000' ===\n")
cursor.execute('''
    SELECT id, market_ticker, is_live, direction, entry_price, size, edge_at_entry, 
           timestamp, settled, event_slug, model_probability, market_price_at_entry
    FROM trades 
    WHERE market_ticker='1784103000' 
    ORDER BY timestamp DESC
''')

rows = cursor.fetchall()
if rows:
    print(f"Found {len(rows)} trade(s):\n")
    for row in rows:
        print(f"Trade ID: {row[0]}")
        print(f"  Market: {row[1]}")
        print(f"  Is Live: {'YES' if row[2] else 'NO (模拟)'}")
        print(f"  Direction: {row[3]}")
        print(f"  Entry Price: {row[4]:.3f}")
        print(f"  Size: ${row[5]:.2f}")
        print(f"  Edge at Entry: {row[6]:.3%}")
        print(f"  Timestamp: {row[7]}")
        print(f"  Settled: {row[8]}")
        print(f"  Event Slug: {row[9]}")
        print(f"  Model Prob: {row[10]:.3f}")
        print(f"  Market Price: {row[11]:.3f}")
        print()
else:
    print("No trades found for this market.")

# Query signals
print("\n=== SIGNALS for market_ticker='1784103000' ===\n")
cursor.execute('''
    SELECT id, market_ticker, direction, model_probability, market_price, edge, 
           timestamp, executed, reasoning
    FROM signals 
    WHERE market_ticker='1784103000' 
    ORDER BY timestamp DESC
    LIMIT 10
''')

signal_rows = cursor.fetchall()
if signal_rows:
    print(f"Found {len(signal_rows)} signal(s):\n")
    for row in signal_rows:
        print(f"Signal ID: {row[0]}")
        print(f"  Direction: {row[2]}")
        print(f"  Model Prob: {row[3]:.3%}")
        print(f"  Market Price: {row[4]:.3%}")
        print(f"  Edge: {row[5]:.3%}")
        print(f"  Timestamp: {row[6]}")
        print(f"  Executed: {row[7]}")
        print(f"  Reasoning: {row[8][:200]}...")
        print()
else:
    print("No signals found for this market.")

conn.close()
