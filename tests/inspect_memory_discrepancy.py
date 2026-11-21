import os
import sys
import sqlite3
import json

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
sys.path.insert(0, r"D:\Orange AI\Orange AI Tauri")

from runtime.runtime_adapter import handle_memory_stats, handle_memory_legacy, handle_memory_structured

def inspect_mem():
    print("=== INSPECTING MEMORY COUNTS ===")
    
    # 1. Database level (AppData)
    p_appdata = os.path.expandvars(r"%LOCALAPPDATA%\Orange AI\memory.db")
    if os.path.exists(p_appdata):
        conn = sqlite3.connect(p_appdata)
        rows_leg = conn.execute("SELECT id, created_at FROM memories ORDER BY id ASC").fetchall()
        rows_struct = conn.execute("SELECT id, category, memory_key, updated_at FROM structured_memories").fetchall()
        print(f"AppData SQLite: memories={len(rows_leg)}, structured_memories={len(rows_struct)}")
        for r in rows_leg:
            print(f"  leg id={r[0]}, created={r[1]}")
        conn.close()

    # 2. Database level (Dev)
    p_dev = r"D:\Orange AI\Orange AI Desktop\memory.db"
    if os.path.exists(p_dev):
        conn2 = sqlite3.connect(p_dev)
        rows_leg2 = conn2.execute("SELECT id, created_at FROM memories ORDER BY id ASC").fetchall()
        rows_struct2 = conn2.execute("SELECT id, category, memory_key, updated_at FROM structured_memories").fetchall()
        print(f"\nDev SQLite: memories={len(rows_leg2)}, structured_memories={len(rows_struct2)}")
        conn2.close()

    # 3. Adapter level
    stats = handle_memory_stats({})
    print(f"\nAdapter handle_memory_stats output: {json.dumps(stats)}")

    leg_list = handle_memory_legacy({"limit": 80})
    print(f"Adapter handle_memory_legacy output count: {len(leg_list)}")

    struct_list = handle_memory_structured({})
    print(f"Adapter handle_memory_structured output count: {len(struct_list)}")

if __name__ == "__main__":
    inspect_mem()
