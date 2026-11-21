# ORANGE AI v2.0.0: TEST COVERAGE GAPS & UNVERIFIED FLOWS
**Definitive Inventory of Test Blindspots, Gaps, and Toolchain Deficiencies**

**Audit Execution Date:** 2026-11-20  
**Target Application:** Orange AI Desktop v2.0.0  
**Workspace:** `D:\Orange AI\Orange AI Tauri`

---

## 1. EXECUTIVE SUMMARY

While unit and integration test coverage is exceptionally strong for low-level persistence (SQLite checkpointing, quiescence, and recommendation state transitions), significant coverage blindspots exist in end-to-end integration, runtime crash supervision, frontend error handling, and multi-step task execution.

Passing tests in isolated test suites have masked production defects—most notably the hosted Orange API model ID mismatch (BUG-API-001), which went undetected because previous verification scripts validated local setting storage rather than remote HTTP 200 responses.

---

## 2. INVENTORY OF MISSING & GAPPED TEST SCENARIOS

### GAP-01: Hosted Orange API Response Code Validation
- **Missing Test:** Automated end-to-end smoke test validating that every model option presented in `SettingsView.jsx` can successfully send a prompt to `https://orange-api-cuuo.onrender.com/assist` and receive an HTTP 200 response with valid content.
- **Current False Coverage:** `tests/run_stage2b_final_verification.py` only checked that `model` was persisted in `gui_settings.json` and passed to a dummy caller; it never asserted HTTP 200 from the remote server.
- **Risk:** High. Led directly to BUG-API-001 reaching production.

### GAP-02: Post-Startup Runtime Process Crash & Supervision
- **Missing Test:** Test simulating unexpected child process termination (`kill()`) while the application is in an active `Ready` state, verifying:
  1. Supervisor transitions to `ProcessTerminated`.
  2. Frontend receives `runtime_terminated` notification.
  3. In-flight and subsequent RPC calls reject immediately with error code `-32000` rather than hanging for 120 seconds.
  4. React UI transitions from `ApplicationShell` to `RecoveryView`.
- **Current False Coverage:** Handshake tests only verify startup failure, not post-startup runtime crashes.
- **Risk:** High (BUG-RT-001). Leaves users staring at an unresponsive app for 2 minutes on crash.

### GAP-03: Settings Persistence & Backend Synchronization
- **Missing Test:** Test asserting that when `settings.update` is called via Tauri IPC, the updated configuration immediately propagates to all core Python modules:
  - `brain.briefing.settings.is_morning_briefing_enabled()`
  - `brain.briefing.settings.get_preferred_briefing_time()`
  - `brain.briefing.settings.is_contextual_advisories_enabled()`
- **Current False Coverage:** Test suites verify that `runtime_adapter.py` updates `%LOCALAPPDATA%\Orange AI\gui_settings.json`, but no test asserts that backend routines reading from `gui/settings.py` read that same file.
- **Risk:** Medium (BUG-RT-003). Settings toggled in the UI are silently ignored by the scheduler.

### GAP-04: Multi-Step Agent Engine Live Execution
- **Missing Test:** End-to-end test executing a complex multi-step user goal (e.g., "Find all markdown files in workspace and count their lines") through `brain/agent.py` and `AgentJobsView.jsx`.
- **Current State:** The production database currently has 0 rows in `jobs` and 0 rows in `job_steps`. Multi-step agent execution has not been verified in the Tauri runtime environment.
- **Risk:** Medium. Multi-step execution could fail on tool parameter serializations or confirmation deadlocks.

### GAP-05: Checklist (`todo_write`) Reactive UI State
- **Missing Test:** Test verifying that when an agent or user invokes `todo_write`, the structured checklist items emit an event that dynamically renders in the UI timeline.
- **Current State:** `todo_write` is registered in `ToolRegistry`, but UI event subscriptions and reactive checklist views are unverified.
- **Risk:** Low to Medium. Users cannot observe active checklist updates.

### GAP-06: Multithreaded Database Concurrency Stress Test
- **Missing Test:** Concurrency test spawning 20 simultaneous threads performing interleaved operations:
  - Thread 1-5: Chat history appends (`mem.save_history`)
  - Thread 6-10: Memory retractions and additions (`mem.retract_entity`, `mem.remember`)
  - Thread 11-15: Proactive event emissions and acknowledgements (`proactive_events`)
  - Thread 16-20: Activity queries (`handle_activity_get`)
- **Current State:** Single-threaded sequential unit tests only. Shared `mem._conn` concurrency has never been validated under load.
- **Risk:** Medium (BUG-DB-001). Risk of `sqlite3.OperationalError: database locked` or cursor conflicts.

### GAP-07: Content Security Policy & XSS Resistance
- **Missing Test:** Automated security scan verifying that CSP headers are present in `tauri.conf.json` and that scripts attempting to load remote untrusted origins or eval arbitrary strings are blocked by WebView2.
- **Current State:** Zero automated verification. CSP is currently `null`.
- **Risk:** High (SEC-001).

---

## 3. INFRASTRUCTURE & ENVIRONMENT DEFICIENCIES

### 3.1 Cargo MinGW Linker Conflict (BUG-ENV-001)
- **Defect:** Running `cargo test --lib` or `cargo build` in `src-tauri` fails during build script linking:
  `lld: error: unable to find library -lgcc_eh`
  `lld: error: unable to find library -lgcc`
  `clang-23: error: linker command failed with exit code 1`
- **Impact:** Rust native unit tests cannot be executed locally using the standard Cargo test harness without configuring explicit MinGW library paths in `.cargo/config.toml` or using MSVC.
- **Remediation:** Add `.cargo/config.toml` with explicit MinGW libdir search flags or adopt the MSVC Rust toolchain (`x86_64-pc-windows-msvc`).
