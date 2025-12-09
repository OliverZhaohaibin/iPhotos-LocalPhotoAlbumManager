import sqlite3

conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE t (id INTEGER, dt TEXT)")
conn.execute("INSERT INTO t VALUES (1, '2023-01-01')")
conn.execute("INSERT INTO t VALUES (2, NULL)")
conn.execute("INSERT INTO t VALUES (3, '2024-01-01')")

print("--- ORDER BY dt DESC ---")
for row in conn.execute("SELECT * FROM t ORDER BY dt DESC"):
    print(row)

print("\n--- ORDER BY dt ASC ---")
for row in conn.execute("SELECT * FROM t ORDER BY dt ASC"):
    print(row)

conn.close()
