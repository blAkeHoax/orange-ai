import sqlite3
import os

p_appdata = os.path.expandvars(r"%LOCALAPPDATA%\Orange AI\memory.db")
if os.path.exists(p_appdata):
    conn = sqlite3.connect(p_appdata)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("AppData memory.db exists! Size:", os.path.getsize(p_appdata), "bytes")
    print("AppData tables:", tables)
    for t in tables:
        count = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  - {t}: {count} rows")
    conn.close()
else:
    print("AppData memory.db does NOT exist.")

p_dev = r"D:\Orange AI\Orange AI Desktop\memory.db"
if os.path.exists(p_dev):
    conn = sqlite3.connect(p_dev)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("\nDev memory.db exists! Size:", os.path.getsize(p_dev), "bytes")
    print("Dev tables:", tables)
    for t in tables:
        count = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  - {t}: {count} rows")
    conn.close()
