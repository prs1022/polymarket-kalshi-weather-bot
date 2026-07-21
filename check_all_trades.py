#!/usr/bin/env python3
"""Check all trades and signals."""
import sqlite3

conn = sqlite3.connect('tradingbot.db')
cursor = conn.cursor()

# Check all trades with pattern
print("\n=== Searching for trades containing '1784103000' ===\n")
cursor.execute('''
    SELECT id, market_ticker, is_live, direction, entry_price, size, edge_at_entry, 
           timestamp, settled, event_slug
    FROM trades 
    WHERE market_ticker LIKE '%1784103000%' OR event_slug LIKE '%1784103000%'
    ORDER BY timestamp DESC
    LIMIT 20
''')

rows = cursor.fetchall()
if rows:
    print(f"Found {len(rows)} trade(s):\n")
    for row in rows:
        print(f"Trade ID: {row[0]}")
        print(f"  Market Ticker: {row[1]}")
        print(f"  Is Live: {'YES (实盘)' if row[2] else 'NO (模拟)'}")
        print(f"  Direction: {row[3]}")
        print(f"  Entry Price: {row[4]:.3f}")
        print(f"  Size: ${row[5]:.2f}")
        print(f"  Edge: {row[6]:.3%}")
        print(f"  Timestamp: {row[7]}")
        print(f"  Settled: {row[8]}")
        print(f"  Event Slug: {row[9]}")
        print()
else:
    print("No trades found.")

# Check recent trades
print("\n=== Recent 10 trades ===\n")
cursor.execute('''
    SELECT id, market_ticker, is_live, direction, entry_price, size, edge_at_entry, 
           timestamp, settled, event_slug
    FROM trades 
    ORDER BY timestamp DESC
    LIMIT 10
''')

rows = cursor.fetchall()
for row in rows:
    print(f"ID:{row[0]} | Live:{row[2]} | {row[3]} | Edge:{row[6]:.3%} | ${row[5]:.2f} | {row[9][:50]}")

# Check signals
print("\n\n=== Searching for signals containing '1784103000' ===\n")
cursor.execute('''
    SELECT id, market_ticker, direction, edge, timestamp, executed
    FROM signals 
    WHERE market_ticker LIKE '%1784103000%'
    ORDER BY timestamp DESC
    LIMIT 10
''')

signal_rows = cursor.fetchall()
if signal_rows:
    print(f"Found {len(signal_rows)} signal(s):\n")
    for row in signal_rows:
        print(f"Signal ID:{row[0]} | Market:{row[1]} | Dir:{row[2]} | Edge:{row[3]:.3%} | Time:{row[4]} | Exec:{row[5]}")
else:
    print("No signals found.")

# Check recent signals with high edge
print("\n\n=== Recent signals with edge > 5% ===\n")
cursor.execute('''
    SELECT id, market_ticker, direction, edge, timestamp, executed
    FROM signals 
    WHERE ABS(edge) >= 0.05
    ORDER BY timestamp DESC
    LIMIT 20
''')

rows = cursor.fetchall()
for row in rows:
    print(f"ID:{row[0]} | Market:{row[1][:20]} | Dir:{row[2]} | Edge:{row[3]:.3%} | Time:{row[4]} | Exec:{row[5]}")

conn.close()
