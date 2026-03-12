import sqlite3
import os

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "backend", "data", "memory.db")

conn = sqlite3.connect(SQLITE_PATH)
cursor = conn.cursor()

# 检查doc_stats表
print("=== doc_stats 表内容 ===")
cursor.execute("SELECT * FROM doc_stats")
rows = cursor.fetchall()
if rows:
    print(f"共 {len(rows)} 条记录:")
    for row in rows:
        print(row)
else:
    print("doc_stats 表为空！")

# 检查session_store表
print("\n=== session_store 表内容 ===")
cursor.execute("SELECT * FROM session_store")
rows = cursor.fetchall()
if rows:
    print(f"共 {len(rows)} 条记录:")
    for row in rows:
        print(f"session_id: {row[0]}, user_id: {row[1]}, 消息数: {len(eval(row[2]))}, 更新时间: {row[3]}")
else:
    print("session_store 表为空！")

# 检查insights表
print("\n=== insights 表内容 ===")
cursor.execute("SELECT * FROM insights")
rows = cursor.fetchall()
if rows:
    print(f"共 {len(rows)} 条记录:")
    for row in rows:
        print(row)
else:
    print("insights 表为空！")

conn.close()
