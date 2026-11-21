# ORANGE AI v2.0.0: COMPREHENSIVE PRE-STAGE-5 BUG AUDIT
**Authoritative Architectural, Runtime, Security, and Quality Audit**

**Audit Execution Date:** 2026-11-20  
**Target Release:** Orange AI Desktop v2.0.0  
**Official Application Workspace:** `D:\Orange AI\Orange AI Tauri`  
**Protected Reference Workspace:** `D:\Orange AI\Orange AI Desktop` (Read-Only)  
**Hosted API Backend:** `https://orange-api-cuuo.onrender.com`  
**Audit Authorization:** Read-Only Inspection & Safe Non-Destructive Testing  
**Overall Verdict:** **PASS WITH LIMITATIONS**

---

## 1. EXECUTIVE SUMMARY

Before authorizing Stage 5 (JARVIS Roadmap) implementation, a comprehensive, evidence-based audit of Orange AI Desktop v2.0.0 was conducted across the React frontend, Rust native shell, Python sidecar runtime adapter, SQLite persistence layer, and hosted Orange API integration.

### Overall Verdict: PASS WITH LIMITATIONS
The desktop architecture successfully establishes a hardened foundation:
- Native single-instance mutex enforcement and Windows Job Object process confinement operate with zero orphan process leaks.
- SQLite WAL checkpointing, database isolation guards, and quiescence shutdown for updates are formally verified.
- The two-phase confirmation security gate strictly prevents unauthorized or bypassed execution of dangerous tools.
- Proactive event dispatching, notification toast rendering, morning briefing presentation, and recommendation lifecycle states operate across the Tauri IPC bridge.

**However, the audit identified 5 critical and high-priority limitations that must be remediated before Stage 5 JARVIS development begins:**
1. **Model Contract Mismatch (P1):** The Tauri frontend and Python runtime adapter default to and expose 4 NVIDIA foundation models (`nvidia/llama-3.1-nemotron-70b-instruct`, `meta/llama-3.1-70b-instruct`, `openbmb/minicpm-v-2_6`, `mistralai/mistral-large-2-instruct`). None of these models exist in the hosted Orange API's registry (`app/services/model_registry.py`), causing any request with model overrides or default model injection to fail with HTTP 400 `Unknown model identifier`.
2. **Silent Runtime Crash & 120-Second Request Hang (P1):** The Rust supervisor does not monitor child process EOF on standard I/O. If the Python runtime adapter crashes after startup, the supervisor status remains permanently in `Ready`, requests hang for the full 120-second timeout, and the frontend never transitions to `RecoveryView`.
3. **Missing Content Security Policy & Empty Updater Public Key (P1 Security):** In `tauri.conf.json`, `"security": { "csp": null }` disables browser CSP defense-in-depth, and `"updater": { "pubkey": "" }` enables the GitHub updater endpoint without cryptographic signature verification.
4. **Split-Brain GUI Settings Storage (P2):** The Tauri runtime adapter reads and writes settings to `%LOCALAPPDATA%\Orange AI\gui_settings.json`, whereas the legacy `gui/settings.py` module (imported by `main.py` and `brain/briefing/settings.py`) reads from `D:\Orange AI\Orange AI Desktop\gui_settings.json`, causing user preference updates in the UI to be ignored by core Python scheduling routines.
5. **Chat Timeline Advisory Regex Mojibake (P2):** Corrupted UTF-8 bytes (`ðŸ’¡`) in `ApplicationShell.jsx` prevent stripping embedded advisory blocks when structured recommendation cards are returned, causing duplicate advisory display in the conversation timeline.

---

## 2. PRESERVED PROJECT STATE & ENVIRONMENT BASELINE

| Component | Verified Setting / Version | Architectural Status |
|---|---|---|
| **Active Workspace** | `D:\Orange AI\Orange AI Tauri` | Sole official desktop workspace |
| **Reference Workspace** | `D:\Orange AI\Orange AI Desktop` | Permanently retired; 100% read-only |
| **Backend Workspace** | `D:\Orange AI\Orange API` | Git branch `main`, commit `4d8477f` |
| **Application Version** | `2.0.0` | In `package.json`, `tauri.conf.json`, `Cargo.toml` |
| **Node.js Toolchain** | `v24.18.0` / npm `11.16.0` | Verified |
| **Rust Compiler** | `rustc 1.100.0 (0ef1bc386 2026-11-09)` / `cargo 1.100.0` | `x86_64-pc-windows-gnu` |
| **Python Runtime** | `3.14.6` (Windows amd64) | Active in `Orange AI Desktop\venv` |
| **Tauri Framework** | Tauri Core `2.12.5`, Tauri API `2.2.0`, CLI `2.2.0` | Verified |
| **Frontend Framework** | React `18.3.1`, Vite `5.4.21` | Production build verified (`dist/`) |
| **Bundled Runtime** | `src-tauri/resources/runtime/runtime_adapter.exe` | PyInstaller standalone binary (8.21 MB) |
| **Operational DB** | `C:\Users\User\AppData\Local\Orange AI\memory.db` | Verified intact (12 tables) |
| **Hosted Backend** | `https://orange-api-cuuo.onrender.com` | Live and operational on Render |

---

## 3. AUDIT FINDINGS BY SUBSYSTEM

### 3.1 Frontend & User Experience (React + Vite)
- **Component Integrity:** All views (`HomeView`, `ChatView`, `ActivityView`, `AgentJobsView`, `MemoryView`, `PermissionsView`, `SettingsView`, `ToolsView`, `RecoveryView`) render cleanly without syntax errors. Production build succeeds (`vite build`, exit code 0).
- **Advisory Mojibake Bug:** In `ApplicationShell.jsx:144`, `replyText.split(/\n+ðŸ’¡\s+\*\*Orange AI Advisory\*\*/)` contains corrupted UTF-8 bytes for emoji 💡 (`\u{1F4A1}`), failing to strip embedded advisory text from chat messages when structured `RecommendationCard` items are present.
- **Async Event Listener Race:** `ApplicationShell.jsx:110-230` initiates `initRuntime()` asynchronously inside `useEffect` without an `isMounted` guard. If unmounted while awaiting promises, newly registered Tauri event unlisteners are orphaned in memory.
- **Composer Constraints:** `Composer.jsx` uses a single-line `<input type="text">` preventing multiline input, and Attachment/Mic buttons have no backend wiring.

### 3.2 Backend & Hosted Orange API Contract
- **Hosted Model Registry Disconnect:** The hosted Orange API on Render strictly enforces:
  - `nvidia/nemotron-3.5-lightning-30b-a3b` (Default, available)
  - `z-ai/glm-5.3-flash` (Available)
  - `openai/gpt-oss-20b` (Unavailable)
  - `google/gemma-4-31b-it` (Unavailable)
  The Tauri frontend and Python runtime adapter advertise and inject models that do not exist on the hosted server (`nvidia/llama-3.1-nemotron-70b-instruct`, `meta/llama-3.1-70b-instruct`, `openbmb/minicpm-v-2_6`, `mistralai/mistral-large-2-instruct`). When sent, the server returns HTTP 400.
- **Daily Briefing Synthesis Degradation:** Due to the model ID mismatch, `synthesizer.py` calls to the hosted API fail with HTTP 400, forcing the morning briefing into local deterministic fallback on every run.

### 3.3 Python Runtime & Rust Supervisor Bridge
- **Crash Detection Absence:** If `runtime_adapter.exe` crashes or is killed externally, Rust's Tokio reader thread reaches EOF and exits, but never updates `supervisor.status` from `Ready` to `ProcessTerminated`, does not notify the webview, and leaves in-flight requests hanging for 120 seconds.
- **Misleading Path Log:** In `runtime_adapter.py:75`, `if os.path.exists(_desktop_workspace) and _desktop_workspace not in sys.path` logs a false warning `"Desktop workspace path not found"` when the directory is already present in `sys.path`.
- **Settings Split-Brain:** In dev/hybrid mode, `gui/settings.py` references `D:\Orange AI\Orange AI Desktop\gui_settings.json` while `runtime_adapter.py` references `%LOCALAPPDATA%\Orange AI\gui_settings.json`.

### 3.4 Database & Data Safety (SQLite)
- **Operational Data Isolation:** Automated test suites enforce a test isolation guard (`_guarded_sqlite3_connect`) that intercepts and aborts any attempt to connect to the operational database in `%LOCALAPPDATA%\Orange AI\memory.db`.
- **Quiescence & Checkpoint Safety:** Verified 100% clean WAL checkpointing via `PRAGMA wal_checkpoint(TRUNCATE)` returning `(0, 0, 0)` with WAL file truncated to 0 bytes before update quiescence.
- **Concurrency Risk:** In `Orange AI Desktop/brain/memory.py`, a single global `_conn` object is shared across all worker threads without thread-locking, risking cursor collision under simultaneous chat and background operations.

### 3.5 Security & Permissions
- **Two-Phase Confirmation Integrity:** Verified that `CONFIRMATION_REQUIRED` actions cannot be executed without explicit affirmative user consent (`chat.confirm`), expired/tampered tokens are rejected, and `HIGH_RISK` tools are denied unconditionally even if administrator privileges are active.
- **Git Sandboxing:** `tools/command.py` strictly restricts execution to canonical `git.exe` with a closed whitelist of 7 read-only subcommands inside an anonymous Windows Job Object with handle inheritance restricted via `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`.
- **Tauri CSP & Updater Exposure:** CSP is set to `null` in `tauri.conf.json`, and the GitHub updater plugin has an empty public key (`pubkey: ""`).

---

## 4. DETAILED FEATURE MATRIX

| Feature Area | Current Status | Operational Assessment |
|---|---|---|
| **Conversations & Chat History** | Partial / Degraded | Works when model override is omitted; broken when desktop selected model is transmitted (HTTP 400). History pagination verified. |
| **Persistent Memory & Profile** | Working & Verified | Real records exist in `structured_memories` and `memories`. Injected into model context via `budget_chat_memory`. |
| **Memory Correction & Forgetting** | Working & Verified | Slugified retraction and keyword forgetting operate transactionally. |
| **Desktop Tools (System, Files, Apps)** | Working & Verified | Safe read tools execute directly; state-changing tools trigger interactive confirmation prompt. |
| **Git Command Sandboxing** | Working & Verified | Strict Win32 `CreateProcessW` containment, Job Object binding, 7 read-only subcommands. |
| **Agent Engine (Multi-Step Tasks)** | Implemented / Unverified | Engine code exists in `brain/agent.py`; zero job steps in operational DB; needs end-to-end user journey validation. |
| **Job Runtime & Background Tasks** | Implemented / Unverified | SQLite schema and model state exist; zero records in production `jobs` table. |
| **Reminders & Due Notifications** | Working & Verified | Scheduler detects overdue reminders, marks `fired=1`, and emits `reminder.due` proactive event with toast presentation. |
| **Checklist (`todo_write`)** | Implemented / Unverified | Tool is registered as `SAFE` in `ToolRegistry`; UI reactive binding is not fully integrated. |
| **Daily Morning Briefing** | Partial / Fallback Only | Scheduled evaluation and delivery work; remote LLM synthesis fails due to model contract mismatch (HTTP 400 fallback). |
| **Recommendation Lifecycle** | Working & Verified | 7-day dismiss suppression, 24-hour snooze suppression, zero-client-trust execution handshake. |
| **Settings Persistence** | Partial / Split-Brain | Saved in `AppData/Local/Orange AI/gui_settings.json`; backend `brain/briefing/settings.py` references legacy file path. |
| **Permission Checks & Gates** | Working & Verified | Strict `SAFE`, `CONFIRMATION_REQUIRED`, `HIGH_RISK` enforcement with atomic confirmation tokens. |
| **Update Quiescence & Checkpointing** | Working & Verified | `system.shutdown_for_update` truncates WAL, rejects incoming turns with `-32001`, and validates database integrity. |
| **Single-Instance Enforcement** | Working & Verified | Named Windows mutex `Local\OrangeAIDesktopSingleInstanceMutex` terminates secondary instances immediately with code 0. |

---

## 5. AUDIT ARTIFACTS INVENTORY

The following formal audit deliverables have been generated as part of this pre-Stage-5 review:

1. [ORANGE_AI_PRE_STAGE_5_AUDIT.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_PRE_STAGE_5_AUDIT.md) — Comprehensive executive and technical audit report.
2. [ORANGE_AI_BUG_REGISTER.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_BUG_REGISTER.md) — Defect register categorized by P0–P3 severity with reproduction steps and root causes.
3. [ORANGE_AI_TEST_RESULTS.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_TEST_RESULTS.md) — Test execution evidence across unit, integration, and security suites.
4. [ORANGE_AI_SECURITY_FINDINGS.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_SECURITY_FINDINGS.md) — Deep-dive security analysis covering CSP, updater, command execution, and credentials.
5. [ORANGE_AI_COVERAGE_GAPS.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_COVERAGE_GAPS.md) — Inventory of unverified flows, missing tests, and environment toolchain defects.
6. [ORANGE_AI_RECOMMENDED_FIX_ORDER.md](file:///D:/Orange%20AI/Orange%20AI%20Tauri/ORANGE_AI_RECOMMENDED_FIX_ORDER.md) — Sequenced, dependency-ordered remediation plan prior to Stage 5 authorization.
