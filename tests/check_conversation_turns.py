import sqlite3
import os

p = os.path.expandvars(r"%LOCALAPPDATA%\Orange AI\memory.db")
conn = sqlite3.connect(p)
cur = conn.execute("SELECT id, role, content FROM conversation_history WHERE content LIKE '%BTEC%' OR content LIKE '%undergraduate%'")
rows = cur.fetchall()
print(f"Found {len(rows)} matching rows in conversation_history:")
for r in rows:
    print(f"[{r[0]}] {r[1]}: {r[2][:120]}...")
conn.close()
