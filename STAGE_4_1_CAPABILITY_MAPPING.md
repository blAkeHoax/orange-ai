# ORANGE AI DESKTOP 2.0
# STAGE 4.1: RUNTIME CAPABILITY MAPPING REPORT

**Date:** November 14, 2026  
**Workspace:** `D:\Orange AI\Orange AI Tauri`  
**Protected Workspace:** `D:\Orange AI\Orange AI Desktop` (Untouched)  

---

## 1. Executive Summary

This report maps the functional requirements of all eight Orange AI Desktop 2.0 navigation destinations to the underlying Python runtime operations, verifies existing implementations, and identifies the minimal safe adapter extensions required for complete functional integration.

---

## 2. Workspace Capability Matrix

| Navigation Destination | UI Functionality Required | Underlying Python Operation | Adapter Status | Gap / Extension Needed |
| :--- | :--- | :--- | :--- | :--- |
| **1. Home** | Quick turn submission, health indicator, brand trigger, drawer toggle | `main.process_user_turn()`, `OrangeAPIClient.is_available()` | **Available** (`chat.send`, `system.ping`) | None |
| **2. Chat** | Multi-turn conversation, thinking indicator, confirmation modal, past history | `main.process_user_turn()`, `_confirmation_prompt_fn()`, `conversation_history` table | **Available** (`chat.send`, `chat.confirm`) | Add `chat.history` to load past turns |
| **3. Agent Jobs** | Autonomous job list, status filtering, execution step history, lifecycle controls (pause, resume, cancel, confirm) | `JobManager.list_jobs()`, `JobManager.get_job()`, `JobManager.get_history()`, `JobManager.pause()`, etc. | **Available** (`jobs.list`, `jobs.status`, `jobs.history`, `jobs.pause`, `jobs.resume`, `jobs.cancel`, `jobs.confirm`) | None |
| **4. Memory** | Memory statistics, structured categories, legacy facts, retract entity, forget keyword, add fact | `mem.memory_stats()`, `mem.recall_structured()`, `mem.recall()`, `mem.retract_entity()`, `mem.forget()`, `mem.remember()` | **Available** (`memory.stats`, `memory.structured`, `memory.legacy`, `memory.retract`, `memory.forget`) | Add `memory.remember` to persist user-submitted fact |
| **5. Activity** | System diagnostic logs, autonomous job step audit trail, conversation history turns | `orange_ai.log` parsing, `JobManager.get_history()`, `conversation_history` table in `memory.db` | **Missing** | Add `activity.get` returning logs, job steps, and conversation turns (mirrors `activity_view.py`) |
| **6. Permissions** | OS privilege level (Admin/Standard), policy tiers (Safe/Confirmation/High Risk), audited tool permissions | `tool_sys.is_running_as_admin()`, `tool_perm.check_permission()`, `tool_reg.registry.list_tools()` | **Available** (`permissions.audit`) | None |
| **7. Tools** | Audited tool catalog, categories, risk classifications, parameter schemas | `tool_reg.registry.list_metadata()` | **Available** (`tools.list`) | None |
| **8. Settings** | Appearance theme preference, Orange API connectivity, runtime storage paths, security disclosures | `gui_settings.load_settings()`, `gui_settings.save_settings()`, `OrangeAPIClient.is_available()`, `brain.paths` | **Available** (`settings.get`, `settings.update`, `system.ping`, `system.health`) | None |

---

## 3. Identified Gaps & Minimal Safe Adapter Extensions

Only three small, safe extensions are needed in `runtime_adapter.py`:

1. **`chat.history`**:
   - *Purpose*: Read recent conversation turns from `conversation_history` table in `memory.db` to populate chat view when opened.
   - *Implementation*: Queries SQLite via existing `mem.get_connection()`. Read-only.
   
2. **`activity.get`**:
   - *Purpose*: Return audited records across the three authentic sources established in Stage 4: persistent logs (`orange_ai.log`), job execution steps (`JobManager`), and conversation turns (`conversation_history`).
   - *Implementation*: Directly mirrors the logic from `D:\Orange AI\Orange AI Desktop\gui\views\activity_view.py`. Read-only.

3. **`memory.remember`**:
   - *Purpose*: Allow the user to remember a fact directly from the Memory workspace.
   - *Implementation*: Calls existing `mem.remember(fact)` in `brain.memory`.

Additionally, in `src-tauri/src/commands.rs`, add a generic `call_runtime` command to allow the React bridge to invoke any registered JSON-RPC method cleanly while retaining all existing specific commands.

---

## 4. Conclusion & Stage 4.1 Sign-Off

The existing Python backend has 90% of the required endpoints already implemented in `runtime_adapter.py`. The three minimal extensions (`chat.history`, `activity.get`, `memory.remember`) use existing, verified Python methods from `D:\Orange AI\Orange AI Desktop` without altering any core logic or database schemas.

We are ready to proceed with **Stage 4.2: Shared Frontend Integration Layer**.
