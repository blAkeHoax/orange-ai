import os
import sys
import sqlite3
import json

DESKTOP_ROOT = r"D:\Orange AI\Orange AI Desktop"
TAURI_ROOT = r"D:\Orange AI\Orange AI Tauri"
USER_DATA_DIR = r"C:\Users\User\AppData\Local\Orange AI"

if DESKTOP_ROOT not in sys.path:
    sys.path.insert(0, DESKTOP_ROOT)
if os.path.join(TAURI_ROOT, "runtime") not in sys.path:
    sys.path.insert(0, os.path.join(TAURI_ROOT, "runtime"))

# 1. Inspect memory.db tables
db_path = os.path.join(USER_DATA_DIR, "memory.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables in memory.db:", tables)

# Check reminders table schema if exists
if "reminders" in tables:
    cur.execute("PRAGMA table_info(reminders)")
    print("reminders schema:", cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM reminders")
    print("reminders count:", cur.fetchone()[0])
else:
    print("reminders table NOT in memory.db")

# 2. Inspect scheduler module
from brain import scheduler
print("Scheduler module attributes:", [a for a in dir(scheduler) if not a.startswith("__")])

# 3. Inspect recommendations module
from brain.briefing import recommendations as rec_mod
print("RecommendationStore methods:", [m for m in dir(rec_mod.RecommendationStore) if not m.startswith("__")])
print("RecommendationState members:", [m.name for m in rec_mod.RecommendationState])

# 4. Inspect tool permissions & AgentEngine
import tools.permissions as tool_perm
import tools.registry as tool_reg
print("Tool permissions attributes:", [a for a in dir(tool_perm) if not a.startswith("__")])
print("Registered tools:", list(tool_reg.registry._tools.keys()) if hasattr(tool_reg.registry, "_tools") else "no _tools")

conn.close()
