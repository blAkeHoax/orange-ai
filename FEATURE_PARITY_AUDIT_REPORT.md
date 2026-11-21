# ORANGE AI DESKTOP 2.0
## STAGE 1: FEATURE PARITY AUDIT (LEGACY TKINTER -> OFFICIAL TAURI APPLICATION)

**Official Development Workspace:** `D:\Orange AI\Orange AI Tauri`  
**Retired Legacy Reference:** `D:\Orange AI\Orange AI Desktop`  
**Audit Date:** November 15, 2026  
**Auditor:** Orange AI Core Architecture Team  
**Scope Authority:** Stage 1 Read-Only Feature Inventory & Parity Verification  
**Final Parity Classification:** **PARTIAL PARITY** (79.4% Functional Parity)

---

## EXECUTIVE SUMMARY & CLASSIFICATION VERDICT

An exhaustive, source-level inspection was conducted comparing the retired CustomTkinter desktop application (`D:\Orange AI\Orange AI Desktop`) against the official Tauri 2 + React desktop application (`D:\Orange AI\Orange AI Tauri`).

### Verdict: PARTIAL PARITY

The official Tauri application has achieved full functional parity across all core intelligence and local system operations:
- **Core Intelligence & Tooling (100% Parity):** All 19 registered tools across System, Files, Processes, Apps, Planning, and Command categories execute identically through the headless Python runtime adapter.
- **Security & Permissions (100% Parity):** The 3-tier permission model (`SAFE`, `CONFIRMATION_REQUIRED`, `HIGH_RISK`) is strictly enforced in Python and cannot be bypassed by React. The interactive confirmation dialog is fully functional.
- **Memory 2.0 (100% Parity):** Structured facts, legacy recall, deletion, and manual fact injection are fully implemented.
- **Autonomous Agent Jobs (100% Parity):** Job listing, status filtering, execution step timeline, pausing, resuming, cancelling, and confirmation work seamlessly with the Python `JobManager`.
- **System Activity & Audits (100% Parity):** Real-time feeds for system logs (`orange_ai.log`), job execution audits (`jobs.db`), and conversation turns (`memory.db`) are fully operational.
- **Desktop Shell & Native Lifecycle (100% Parity + Enhancement):** Frameless custom title bar, single-instance Windows Named Mutex, theme switching, and kernel-level orphan cleanup via Windows Job Objects (`SafeJobObject`).

However, **notable functional gaps remain** that prevent a `FULL PARITY` classification:
1. **Proactive Automation Subsystem (Missing):** The background 60s recurring morning briefing loop, idle recommendation evaluator (10m inactivity threshold), and startup reconciliation were previously driven by Tkinter's `after()` timers in `gui/app.py`. The Tauri runtime adapter currently lacks these proactive worker loops.
2. **Timeline Rich Cards & Markdown (Missing):** ChatView renders plain-text message strings without markdown parsing/code block syntax highlighting, collapsible tool stdout result cards, or proactive recommendation cards.
3. **Proactive & Model Settings (Missing / Partial):** The Tauri SettingsView provides theme switching, API health testing, and storage path inspection, but omits the 4-NVIDIA-model radio selector, morning briefing scheduler controls (toggle + delivery time), and recommendation cooldown controls.
4. **Scheduler Event Notification in UI (Partial):** The Python scheduler emits reminder events over IPC, but the React UI lacks an event listener and toast/banner to present them to the user.

---

## QUANTITATIVE PARITY SCORE & COUNTING METHODOLOGY

```
+------------------------------------+-------+--------------------+
| Classification Category            | Count | Percentage of Total|
+------------------------------------+-------+--------------------+
| FULL PARITY                        |    49 |              76.6% |
| PARTIAL PARITY                     |     2 |               3.1% |
| MISSING                            |    12 |              18.8% |
| LEGACY ONLY (Deliberately Retired) |     1 |               1.5% |
| NOT VERIFIED                       |     0 |               0.0% |
+------------------------------------+-------+--------------------+
| TOTAL FEATURES EVALUATED           |    64 |             100.0% |
+------------------------------------+-------+--------------------+
```

### Disclosed Scoring Formula:
- **Total Features Identified:** 64
- **Excluded Features:** 1 (`ActionCards` on Home screen, retired under the approved Nano Banana visual design authority).
- **Relevant Target Features:** 63
- **Scoring Weights:**
  - `FULL PARITY` = 1.0 point
  - `PARTIAL PARITY` = 0.5 points
  - `MISSING` = 0.0 points
  - `NOT VERIFIED` = 0.0 points
- **Total Points Earned:** 49 + (2 x 0.5) = **50.0 points**
- **Parity Percentage:** (50.0 / 63) x 100 = **79.4%**

---

## 1. COMPLETE LEGACY FEATURE INVENTORY (`D:\Orange AI\Orange AI Desktop`)

The legacy desktop application was organized into CustomTkinter UI components, a background service bridge, a core intelligence runtime (`brain/`), and a tool execution suite (`tools/`).

### 1.1 Shell & Window Lifecycle
- `gui/app.py` (`OrangeAIApp`): Root application window with custom geometry, icon management (`_set_app_icon`), protocol close handler (`_on_close`), and view-switching manager (`_show_view`).
- `gui/single_instance.py`: Windows Named Mutex `OrangeAI_SingleInstance_Mutex` preventing concurrent process execution.
- `gui/theme.py`: `ThemeManager` with dynamic switching between "dark", "light", and "system" modes, notifying registered view listeners.
- `gui/components/navigation_rail.py`: Left vertical navigation rail with 8 destination buttons (`home`, `chat`, `jobs`, `memory`, `activity`, `permissions`, `tools`, `settings`), active highlight pill, and theme toggle button.

### 1.2 Home & Visual Experience
- `gui/views/home_view.py`: Approved Home visual shell containing top brand mark, personalized welcome greeting (`Welcome Sayan`), faceted 3D orb asset, and floating bottom composer.
- `gui/components/action_cards.py`: 4 pre-configured action cards ("Work on a project", "Analyze files", "Plan my day", "Use my computer") executing direct queries in chat.
- `gui/utils/greeting_helper.py`: Dynamic time-of-day greeting generator ("Good morning", "Good afternoon", "Good evening").

### 1.3 Chat & Conversation Management
- `gui/views/chat_view.py`: Conversation workspace managing active timeline, bridge communication, and status notices.
- `gui/components/message_timeline.py`: Message timeline rendering user bubbles, assistant bubbles with model badges, thinking spinners, tool result cards, and recommendation cards.
- `gui/components/markdown_renderer.py`: Markdown block parser rendering headers (H1-H3), code blocks with syntax styling and 1-click clipboard copy, blockquotes, lists, and bold/italic text.
- `gui/components/tool_result_card.py`: Specialized card for tool outputs featuring tool name, execution status pill, monospace stdout block, collapsible toggle (>10 lines), and 1-click clipboard copy.
- `gui/components/recommendation_card.py`: Proactive card with priority badges (HIGH, MEDIUM, LOW), reasoning explanation, suggested action, evidence expander, Dismiss button (7-day suppression), Snooze button (24-hour deferral), and Execute button.
- `gui/components/composer.py`: Floating input pill with attachment paperclip (placeholder), microphone (placeholder), multiline text entry, Enter-to-send binding, and orange glowing send button.

### 1.4 Assistant Execution & Intelligence
- `main.py` (`process_user_turn`): Primary intelligence entry point orchestrating intent classification, memory extraction/retrieval, router selection, and response formatting.
- `brain/router.py`: 3-tier routing pipeline:
  - L1: Fast Local deterministic tool execution.
  - L2: Cloud inference via Hosted Orange API (`OrangeAPIClient.assist`).
  - L3: Autonomous AgentEngine multi-step execution.
- `brain/intents.py`: Regex and keyword-based intent classification.
- `brain/planner.py`: Multi-step goal decomposition and DAG planning.
- `brain/context_budget.py`: Token budget management for model context injection.

### 1.5 ToolRegistry & System Tools (19 Tools)
- `tools/registry.py`: Central tool repository registering 19 audited tools across 6 categories:
  - **System (7):** `get_time`, `get_date`, `get_cpu_usage`, `get_ram_usage`, `get_disk_usage`, `get_battery`, `is_running_as_admin`.
  - **Files (5):** `list_files`, `read_file`, `edit_file`, `find_file`, `find_folder`.
  - **Processes (3):** `list_processes`, `is_running`, `close_process`.
  - **Apps (2):** `open_app`, `open_folder`.
  - **Planning (1):** `todo_write`.
  - **Command (1):** `run_command` (strict Git containment).
- `gui/views/tools_view.py`: Catalog viewer displaying all 19 tools with category pills, search bar, risk level indicators, and an interactive "Run Tool" button handing off queries to Chat.

### 1.6 Permissions & Security
- `tools/permissions.py`: 3-tier security architecture (`SAFE`, `CONFIRMATION_REQUIRED`, `HIGH_RISK`).
- `gui/components/confirmation_card.py`: Inline warning card prompting explicit user approval with single-decision lock and timeout prevention.
- `gui/views/permissions_view.py`: Policy audit view displaying policy rules, tool categorization, and UAC administrator status.

### 1.7 Memory 2.0 Subsystem
- `brain/memory.py`: Persistent SQLite storage (`memory.db`) supporting structured entity recall, legacy unstructured recall, fact classification, memory statistics, keyword forgetting, and entity retraction.
- `gui/views/memory_view.py`: Memory dashboard displaying statistics cards, category filters (`PROFILE`, `PROJECT`, `TOOL`, `PREFERENCE`, `FACT`, `LEGACY`), keyword search, structured cards with retraction dialog, legacy cards with forget dialog, and an "Add Fact" manual injection form.

### 1.8 Autonomous Agent Jobs
- `brain/jobs/manager.py` & `store.py`: Persistent SQLite job store (`jobs.db`) managing autonomous multi-step goals.
- `gui/views/agent_jobs_view.py`: Management dashboard with status tabs (All, Active, Paused, Pending, Waiting, Completed, Failed), search filter, execution step timeline, and action buttons (`pause`, `resume`, `cancel`, `confirm`).

### 1.9 System Activity & Audit Trail
- `gui/views/activity_view.py`: Diagnostic audit feed aggregating system logs (`orange_ai.log`), job execution step history (`jobs.db`), and conversation turns (`memory.db`) with level filters and keyword search.

### 1.10 Settings & Environment
- `gui/views/settings_view.py`:
  - Appearance: Theme selection (Dark, Light, System).
  - Proactive Assistant: Morning briefing toggle, delivery time input (HH:MM), contextual advisories toggle, advisory cooldown selector (10m, 30m, 1h, 4h).
  - Backend Connection: Editable API URL, "Test Connection" button, status badge.
  - Model Selection: Radio buttons for 4 NVIDIA models (Nemotron 70B, Llama 70B, MiniCPM, Mistral).
  - Storage Paths: Database path, project root, log path.

### 1.11 Proactive Automation & Background Scheduler
- `gui/app.py` (`_start_scheduler`, `_check_morning_briefing`, `_check_idle_recommendations`, `_run_startup_reconciliation`):
  - Background scheduler thread checking reminders.
  - 60-second polling loop verifying if morning briefing is due; synthesizes and injects briefing into chat timeline.
  - 30-second polling loop verifying user inactivity (>600s); dispatches pending high/medium recommendations into chat timeline.
  - Startup reconciliation synchronizing git commits, modified files, and overdue reminders.
- `brain/briefing/`: Complete proactive briefing subsystem (`collector.py`, `synthesizer.py`, `recommendations.py`, `project_health.py`, `event_store.py`).

---

## 2. COMPLETE TAURI FEATURE INVENTORY (`D:\Orange AI\Orange AI Tauri`)

The official Tauri application replaces CustomTkinter with a modern React 18 + Vite 5 frontend and a Tauri 2 (Rust) desktop shell, communicating with the Python intelligence runtime as a managed headless sidecar over JSON-RPC 2.0 stdio pipes.

### 2.1 Shell & Native Lifecycle
- `src-tauri/src/main.rs` & `lib.rs`: Tauri 2 application entry point managing window initialization, plugins, and command routing.
- `src-tauri/src/single_instance.rs`: Native Windows Named Mutex (`Global\OrangeAI_Desktop_Tauri_SingleInstance_Mutex`) with automatic single-instance detection and window focus.
- `src-tauri/src/job_object.rs`: Windows Job Object (`SafeJobObject`) enforcing `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, guaranteeing zero orphan Python processes.
- `src/components/TitleBar.jsx`: Custom Windows title bar with window dragging, minimize, maximize/restore, close buttons, and header theme toggle.
- `src/components/NavigationDrawer.jsx`: Animated left drawer exposing all 8 primary navigation views, theme switcher, and persistent brand orb.

### 2.2 Home & Visual Experience
- `src/components/HomeView.jsx`: Full faithful implementation of the approved Nano Banana visual reference:
  - Personalized welcome greeting (`Welcome Sayan, how can I help today?`).
  - Large faceted 3D orb (`OrbArtwork.jsx`) with multi-stop ambient orange illumination.
  - Brand trigger in top-left (`BrandTrigger.jsx`).
  - Floating bottom composer (`Composer.jsx`).

### 2.3 Chat & Conversation Management
- `src/components/ChatView.jsx`: Active conversation timeline displaying user and assistant message rows with avatar badges, model indicator tag, thinking spinner (`Loader2`), and auto-scroll to bottom.
- `src/components/Composer.jsx`: Bottom composer pill with attachment button, voice mic button, auto-focus input, and glowing orange send button.
- `src/components/ConfirmationModal.jsx`: Modal dialog presenting `CONFIRMATION_REQUIRED` tool prompts with Approve/Deny buttons, bound confirmation IDs, and single-decision lock.

### 2.4 Headless Python Runtime Adapter (`runtime/runtime_adapter.py`)
- Headless JSON-RPC 2.0 stdio bridge over stdin/stdout.
- Exposes 29 RPC methods:
  - System: `system.ping`, `system.health`, `system.shutdown`.
  - Chat: `chat.send`, `chat.history`, `chat.confirm`.
  - Jobs: `jobs.list`, `jobs.status`, `jobs.history`, `jobs.create`, `jobs.start`, `jobs.pause`, `jobs.resume`, `jobs.cancel`, `jobs.confirm`.
  - Memory: `memory.structured`, `memory.legacy`, `memory.stats`, `memory.forget`, `memory.retract`, `memory.remember`.
  - Activity: `activity.get`.
  - Tools: `tools.list`.
  - Permissions: `permissions.audit`.
  - Settings: `settings.get`, `settings.update`.
  - UI Automation: `ui.set_theme`, `ui.toggle_drawer`, `ui.select_view`.
- Synchronous confirmation callback (`_confirmation_prompt_fn`) with 120s safety timeout.

### 2.5 Secondary Workspaces (React Views)
- `src/components/views/AgentJobsView.jsx`: Job list with status filter pills, search bar, collapsible step audit timeline, and actions (Pause, Resume, Cancel, Confirm).
- `src/components/views/MemoryView.jsx`: Memory stats cards, category filter tabs, structured cards with Retract button, legacy cards with Forget button, and an expandable "Add Fact" form calling `memory.remember`.
- `src/components/views/ActivityView.jsx`: Multi-source audit viewer (System Logs, Job Steps, Conversations) with level filtering, keyword search, and live refresh.
- `src/components/views/PermissionsView.jsx`: 3 policy tiers, tool risk classification badges, UAC admin rights status indicator, and search.
- `src/components/views/ToolsView.jsx`: Full 19-tool catalog by category, search bar, risk badges, and interactive "Use in Chat" button executing tools in the chat composer.
- `src/components/views/SettingsView.jsx`: Theme switching cards (Dark/Light), Orange API connection test button and live status badge, L1/L2/L3 security disclosure, and storage path display.

### 2.6 Packaging & Release Infrastructure
- `scripts/build_release_bundle.py` & `scripts/build_runtime.py`: Standalone PyInstaller runtime bundling (`runtime_adapter.exe` + `_internal/`).
- `src-tauri/target/release/bundle/nsis/Orange AI_2.0.0_x64-setup.exe`: Self-contained 134 MB Windows NSIS installer verified on clean environments.

---

## 3. FEATURE PARITY COMPARISON MATRIX

| # | Feature Name | Legacy Source & Function | Legacy User Workflow | Tauri Equivalent | Tauri Source & Method | JSON-RPC / IPC Path | DB / Runtime Dependency | Existing Test Evidence | Parity Classification | Missing Implementation Requirements |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Custom Frameless Title Bar | `gui/app.py` (`OrangeAIApp`) | Drag window, click min/max/close | `TitleBar.jsx` | `TitleBar.jsx` (`minimizeWindow`, etc.) | Rust IPC: `minimize_window`, `toggle_maximize_window`, `close_window` | Windows OS Window Manager | Verified via CDP & visual acceptance suite | **FULL PARITY** | None |
| 2 | Single-Instance Mutex | `gui/single_instance.py` | Detects duplicate launch, focuses existing | `single_instance.rs` | `single_instance.rs` (`acquire_single_instance_mutex`) | Native Windows API `CreateMutexW` | Windows Kernel Object | Verified via second-process spawn test | **FULL PARITY** | None |
| 3 | Dark & Light Theme Switching | `gui/theme.py` (`ThemeManager`) | Toggle between dark and light themes | `ThemeContext.jsx` | `ThemeContext.jsx` (`setTheme`, `toggleTheme`) | React Context + CSS tokens + `settings.update` | `gui_settings.json` | Verified via CDP theme toggle capture | **FULL PARITY** | None |
| 4 | System Theme Auto-Detection | `gui/theme.py` (`_get_system_theme`) | Follows Windows system dark/light mode | None | `ThemeContext.jsx` | Internal React state (defaults to dark) | Windows Registry | Not implemented in React | **PARTIAL PARITY** | Add `window.matchMedia('(prefers-color-scheme: dark)')` listener in `ThemeContext` |
| 5 | Navigation Drawer (8 Views) | `gui/components/navigation_rail.py` | Click rail icon to switch view | `NavigationDrawer.jsx` | `NavigationDrawer.jsx` (`onSelectView`) | React State `activeView` + `ui.select_view` | Memory state | Verified via Phase 4 workspace test suite | **FULL PARITY** | None |
| 6 | Global Keyboard Shortcuts | `gui/app.py` | Ctrl+Shift+T, Ctrl+Shift+D | `ApplicationShell.jsx` | `handleGlobalKeyDown` | Native browser keydown listener | DOM Window | Verified via interactive keyboard tests | **FULL PARITY** | None |
| 7 | Windows Job Object Process Safety | None (monolithic) | Terminating Tkinter killed Python | `job_object.rs` | `SafeJobObject::assign_process` | Win32 Job Object API | Windows Kernel | Verified via process kill stress tests | **FULL PARITY** | Architectural enhancement over legacy |
| 8 | Personalized Greeting & Orb | `gui/views/home_view.py` | Home screen welcome + 3D orb | `HomeView.jsx` | `WelcomeSection.jsx` & `OrbArtwork.jsx` | Pure React / CSS SVG filters | None | Verified via Nano Banana pixel-audit | **FULL PARITY** | None |
| 9 | Action Cards on Home Screen | `gui/components/action_cards.py` | 4 prompt cards on Home screen | None | Deliberately retired | None | None | Verified absent | **LEGACY ONLY** | Deliberately retired to adhere to approved Nano Banana design authority |
| 10 | Floating Bottom Composer | `gui/components/composer.py` | Bottom input pill with Send button | `Composer.jsx` | `Composer.jsx` (`handleSubmit`) | React Form + Enter keydown | None | Verified via hosted chat smoke test | **FULL PARITY** | None |
| 11 | Attachment Paperclip Button | `gui/components/composer.py` | Informational placeholder | `Composer.jsx` | `handleAttachmentClick` | `console.log` placeholder | None | Verified informational placeholder in both | **FULL PARITY** | File upload backend not in legacy scope |
| 12 | Microphone Voice Button | `gui/components/composer.py` | Informational placeholder | `Composer.jsx` | `handleMicClick` | `console.log` placeholder | None | Verified informational placeholder in both | **FULL PARITY** | Voice backend not in legacy scope |
| 13 | Multi-Turn Hosted Chat | `main.py` & `api_client.py` | User sends prompt, gets assistant reply | `ChatView.jsx` | `ApplicationShell.jsx` (`handleSendMessage`) | Rust `send_message` -> RPC `chat.send` | `OrangeAPIClient` (Render) | Verified live inference with Nemotron 70B | **FULL PARITY** | None |
| 14 | Conversation History Recall | `brain/database.py` | Preserves chat turns across sessions | `runtime_adapter.py` | `handle_chat_history` | Rust `call_runtime('chat.history')` | `memory.db` (`conversation_history`) | Verified history load on app mount | **FULL PARITY** | None |
| 15 | Thinking / Busy Indicator | `gui/components/message_timeline.py` | Spinner shown while assistant processes | `ChatView.jsx` | `ChatView.jsx` (`isExecuting` spinner) | React State | None | Verified visual spinner rendering | **FULL PARITY** | None |
| 16 | Markdown Block Rendering | `gui/components/markdown_renderer.py` | Headers, bold, quotes, tables | None | `ChatView.jsx` (renders `msg.text` plain) | None | None | Tested: renders markdown syntax as raw text | **MISSING** | Integrate React Markdown renderer (`react-markdown` / `remark-gfm`) |
| 17 | Code Syntax Highlighting & Copy | `gui/components/markdown_renderer.py` | Formatted code block with copy button | None | `ChatView.jsx` | None | None | Tested: code renders without block styling | **MISSING** | Add syntax highlighter and 1-click clipboard copy button |
| 18 | Tool Result Card Presentation | `gui/components/tool_result_card.py` | Collapsible card, stdout block, copy | None | `ChatView.jsx` | None | None | Tested: tool stdout embedded in text bubble | **MISSING** | Implement `ToolResultCard.jsx` with collapsible body and copy button |
| 19 | Recommendation Card Timeline | `gui/components/recommendation_card.py` | Proactive recommendation card in chat | None | None | None | None | Tested: absent in ChatView | **MISSING** | Implement `RecommendationCard.jsx` in chat timeline |
| 20 | Recommendation Action Controls | `gui/components/recommendation_card.py` | Dismiss (7d), Snooze (24h), Execute | None | None | None | `briefing.db` / `recommendations` | Tested: absent in React | **MISSING** | Add RPC endpoints `recommendations.dismiss`, `snooze`, `execute` |
| 21 | System Tools (7 tools) | `tools/system.py` | Time, date, CPU, RAM, disk, battery, admin | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | `psutil`, Win32 API | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 22 | File Tools (5 tools) | `tools/files.py` | List, read, edit, find file, find folder | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | Filesystem | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 23 | Process Tools (3 tools) | `tools/processes.py` | List processes, is running, close | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | `psutil` | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 24 | Application Tools (2 tools) | `tools/apps.py` | Open application, open folder | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | OS Shell | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 25 | Planning Tool (`todo_write`) | `tools/todo.py` | Update multi-step goal task checklist | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | SQLite memory | Verified in `test_todo_write.py` | **FULL PARITY** | None |
| 26 | Git Command Tool (`run_command`) | `tools/command.py` | Read-only git commands under containment | `runtime_adapter.py` | Invoked via `main.process_user_turn` | RPC `chat.send` -> `Router` -> `ToolRegistry` | Git CLI | Verified in `test_run_command_security.py` | **FULL PARITY** | None |
| 27 | Tool Catalog View | `gui/views/tools_view.py` | Browse tools by category, search | `ToolsView.jsx` | `ToolsView.jsx` (`fetchToolsList`) | Rust `call_runtime('tools.list')` | `ToolRegistry.list_metadata()` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 28 | Interactive Tool 'Use in Chat' | `gui/views/tools_view.py` | Click tool card to prefill chat | `ToolsView.jsx` | `ToolsView.jsx` (`onRunInChat`) | React Callback `onSendMessage` | Application Shell | Verified via interactive test | **FULL PARITY** | None |
| 29 | 3-Tier Security Policy Enforcement | `tools/permissions.py` | SAFE, CONFIRM, HIGH_RISK checks | `runtime_adapter.py` | `check_permission` in Python | Internal Python permissions evaluation | `tools.permissions` | Verified in `test_confirmation_security.py` | **FULL PARITY** | None |
| 30 | Administrator Detection | `tools/system.py` | Detect elevated process rights | `runtime_adapter.py` | `is_running_as_admin()` | RPC `permissions.audit` | Windows Win32 Shell API | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 31 | Interactive Confirmation Modal | `gui/components/confirmation_card.py` | Prompt user before running dangerous tool | `ConfirmationModal.jsx` | `ConfirmationModal.jsx` (`onConfirm`) | Event: `assistant_confirmation_required` -> RPC `chat.confirm` | Threading Event in Python | Verified in `test_confirmation_security.py` | **FULL PARITY** | None |
| 32 | Permissions Policy Audit View | `gui/views/permissions_view.py` | Inspect permission tiers and tools | `PermissionsView.jsx` | `PermissionsView.jsx` (`fetchAudit`) | Rust `call_runtime('permissions.audit')` | `tools.permissions` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 33 | Structured Memory Recall | `brain/memory.py` | View structured facts by category | `MemoryView.jsx` | `MemoryView.jsx` (`getStructuredMemory`) | Rust `call_runtime('memory.structured')` | `memory.db` (`entities`) | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 34 | Legacy Memory Recall | `brain/memory.py` | View legacy unstructured facts | `MemoryView.jsx` | `MemoryView.jsx` (`getLegacyMemory`) | Rust `call_runtime('memory.legacy')` | `memory.db` (`facts`) | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 35 | Memory Stats Dashboard | `brain/memory.py` | Structured, category, legacy counts | `MemoryView.jsx` | `MemoryView.jsx` (`getMemoryStats`) | Rust `call_runtime('memory.stats')` | `memory.db` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 36 | Structured Memory Retraction | `brain/memory.py` | Delete specific entity by category/key | `MemoryView.jsx` | `handleRetractStructured` | Rust `call_runtime('memory.retract')` | `memory.db` (`entities`) | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 37 | Legacy Memory Forgetting | `brain/memory.py` | Delete legacy memories by keyword | `MemoryView.jsx` | `handleForgetLegacy` | Rust `call_runtime('memory.forget')` | `memory.db` (`facts`) | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 38 | Manual Fact Creation ("Add Fact") | `gui/views/memory_view.py` | Enter new fact via dialog/form | `MemoryView.jsx` | `handleSaveFact` | Rust `call_runtime('memory.remember')` | `memory.db` (`remember()`) | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 39 | Agent Job Listing by Status | `gui/views/agent_jobs_view.py` | Filter jobs (All, Active, Paused, etc.) | `AgentJobsView.jsx` | `AgentJobsView.jsx` (`fetchJobsList`) | Rust `call_runtime('jobs.list')` | `jobs.db` (`JobStore`) | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 40 | Agent Job Keyword Search | `gui/views/agent_jobs_view.py` | Search jobs by goal or short ID | `AgentJobsView.jsx` | `filteredJobs` state | Pure client-side filtering | React State | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 41 | Job Execution Step Timeline | `gui/views/agent_jobs_view.py` | View step audit history for a job | `AgentJobsView.jsx` | `toggleHistory` | Rust `call_runtime('jobs.history')` | `jobs.db` (`job_steps`) | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 42 | Agent Job Lifecycle Actions | `gui/views/agent_jobs_view.py` | Pause, resume, cancel job | `AgentJobsView.jsx` | `handlePause`, `handleResume`, `handleCancel` | Rust `call_runtime('jobs.pause' / 'resume' / 'cancel')` | `brain.jobs.JobManager` | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 43 | Agent Job Approval Confirmation | `gui/views/agent_jobs_view.py` | Approve pending confirmation in job | `AgentJobsView.jsx` | `handleConfirm` | Rust `call_runtime('jobs.confirm')` | `brain.jobs.JobManager` | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 44 | System Log Feed (`orange_ai.log`) | `gui/views/activity_view.py` | Read and search diagnostic logs | `ActivityView.jsx` | `ActivityView.jsx` (`fetchActivity`) | Rust `call_runtime('activity.get')` | Filesystem log file | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 45 | Job Step Audit Feed | `gui/views/activity_view.py` | Read all job steps across jobs | `ActivityView.jsx` | `ActivityView.jsx` (`fetchActivity`) | Rust `call_runtime('activity.get')` | `jobs.db` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 46 | Conversation Turn Audit Feed | `gui/views/activity_view.py` | Read all user & assistant turns | `ActivityView.jsx` | `ActivityView.jsx` (`fetchActivity`) | Rust `call_runtime('activity.get')` | `memory.db` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 47 | Activity Log Level Filtering | `gui/views/activity_view.py` | Filter logs by INFO, WARN, ERROR | `ActivityView.jsx` | `levelFilter` state | Pure client-side filtering | React State | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 48 | Activity Search Filter | `gui/views/activity_view.py` | Search across active activity feed | `ActivityView.jsx` | `searchQuery` state | Pure client-side filtering | React State | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 49 | Appearance Settings (Theme) | `gui/views/settings_view.py` | Select Dark or Light theme | `SettingsView.jsx` | `handleSelectTheme` | React Context + RPC `settings.update` | `gui_settings.json` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 50 | API Connectivity Test & Status | `gui/views/settings_view.py` | Click button, inspect ping & health | `SettingsView.jsx` | `handleTestConnection` | Rust `ping` & `get_health` | Hosted API / Python | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 51 | Storage & Data Paths Display | `gui/views/settings_view.py` | View DB path, local app data, PID | `SettingsView.jsx` | `SettingsView.jsx` | Rust `ping` / RPC `system.ping` | `brain.paths` | Verified in CDP Phase 4 test suite | **FULL PARITY** | None |
| 52 | Editable API URL Configuration | `gui/views/settings_view.py` | Modify API URL in settings field | None (read-only display) | `SettingsView.jsx` | Read-only in React; `settings.update` in adapter | `gui_settings.json` | Tested: URL input is not editable in UI | **PARTIAL PARITY** | Add input text field and save button in `SettingsView.jsx` |
| 53 | NVIDIA Model Selection (4 models)| `gui/views/settings_view.py` | Radio cards for Nemotron, Llama, MiniCPM, Mistral | None (informational tiers text) | `SettingsView.jsx` | None in React; `settings.update` in adapter | `gui_settings.json` (`model`) | Tested: UI displays tiers but lacks radio selector | **MISSING** | Add 4-model radio selection card group in `SettingsView.jsx` |
| 54 | Proactive Morning Briefing Controls | `gui/views/settings_view.py` | Toggle briefing + time picker (HH:MM)| None | None | None | `gui_settings.json` (`briefing_enabled`, `briefing_time`) | Tested: absent in React SettingsView | **MISSING** | Add briefing toggle and HH:MM time picker in `SettingsView.jsx` |
| 55 | Contextual Advisory Controls | `gui/views/settings_view.py` | Toggle advisories + cooldown dropdown | None | None | None | `gui_settings.json` (`advisories_enabled`, `advisory_cooldown`) | Tested: absent in React SettingsView | **MISSING** | Add advisory toggle and cooldown dropdown in `SettingsView.jsx` |
| 56 | Scheduler Thread Initialization | `gui/app.py` (`_start_scheduler`) | Starts Python `Scheduler` thread | `runtime_adapter.py` | `main.ensure_initialized()` | Internal Python thread | `brain.scheduler` | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 57 | Reminder Due Event Emission | `gui/app.py` | Emits event when reminder time arrives | `runtime_adapter.py` | `_on_reminder_due` | RPC Event: `scheduler.reminder_due` | `brain.reminders` | Verified in `test_phase4_adapter_methods.py` | **FULL PARITY** | None |
| 58 | Reminder Due UI Notification | `gui/app.py` | Injects reminder message into chat | None | None | Unhandled in React | None | Tested: React ignores `scheduler_reminder_due` | **MISSING** | Add `onEvent('scheduler_reminder_due')` listener in `ApplicationShell.jsx` |
| 59 | Recurring Morning Briefing Loop | `gui/app.py` (`_check_morning_briefing`) | 60s background timer checking due time | None | None | None | `brain.briefing` | Tested: no recurring briefing loop in adapter | **MISSING** | Implement background worker thread in `runtime_adapter.py` |
| 60 | Morning Briefing Chat Delivery | `gui/app.py` | Synthesizes briefing, posts to chat | None | None | None | `synthesizer.py` | Tested: no briefing delivery path | **MISSING** | Emit `assistant.briefing_ready` event over JSON-RPC to chat timeline |
| 61 | Idle Recommendation Evaluator | `gui/app.py` (`_check_idle_recommendations`)| 30s timer checking 10m user inactivity | None | None | None | `recommendations.py` | Tested: no idle tracker in adapter or React | **MISSING** | Implement idle activity tracker and recommendation worker in adapter |
| 62 | Idle Recommendation Chat Delivery | `gui/app.py` | Injects recommendation card into chat | None | None | None | `recommendations.py` | Tested: no recommendation delivery path | **MISSING** | Emit `assistant.recommendation_ready` event over JSON-RPC to chat timeline |
| 63 | Startup Project Reconciliation | `gui/app.py` (`_run_startup_reconciliation`) | Checks git commits, files, reminders | None | None | None | `EventCoordinator` | Tested: reconciliation not triggered on startup | **MISSING** | Trigger `EventCoordinator.trigger_reconciliation()` on runtime startup |
| 64 | Standalone Windows NSIS Installer | None | Tkinter ran from local virtualenv | NSIS Installer EXE | `scripts/build_release_bundle.py` | PyInstaller standalone runtime + Tauri bundle | Windows NSIS | Verified installed app execution on clean host | **FULL PARITY** | Production enhancement over legacy |

---

## 4. LIST OF MISSING CAPABILITIES (12 ITEMS)

The following 12 capabilities were present and operational in the retired CustomTkinter application but are currently absent in the official Tauri application:

### Gap 1: Markdown Block Parser & Rich Text Rendering
- **Legacy Source:** `gui/components/markdown_renderer.py` (`MarkdownRenderer`, `parse_markdown_blocks`)
- **Legacy Behavior:** Parsed assistant messages into structured blocks: Level 1–3 headers, bold/italic text, blockquotes, unordered/ordered lists, and formatted code blocks.
- **Current Tauri State:** `ChatView.jsx` renders `msg.text` inside a simple `<div>` text container (`<div className="chat-message-content">{msg.text}</div>`). Raw markdown characters (`#`, `**`, ` ``` `) are rendered literally without typography hierarchy.
- **Requirement for Parity:** Integrate a lightweight React markdown library (`react-markdown` with `remark-gfm`) inside `ChatView.jsx`.

### Gap 2: Code Block Syntax Highlighting & 1-Click Clipboard Copy
- **Legacy Source:** `gui/components/markdown_renderer.py` (`CodeBlockFrame._on_copy_clicked`)
- **Legacy Behavior:** Rendered programming code in a dark container with language badge, monospace font, and a dedicated "Copy" button that wrote code to the Windows clipboard.
- **Current Tauri State:** Code blocks are rendered as raw inline text.
- **Requirement for Parity:** Add a code block component in React with `navigator.clipboard.writeText` support and syntax styling.

### Gap 3: Tool Result Presentation Card with Collapsible Output
- **Legacy Source:** `gui/components/tool_result_card.py` (`ToolResultCard`)
- **Legacy Behavior:** Dedicated card displaying tool name, status pill (`SUCCESS` / `FAILED`), execution arguments, monospace stdout block, a 1-click clipboard copy button, and an automatic collapse toggle if output exceeded 10 lines.
- **Current Tauri State:** When tools execute, the Python runtime returns plain formatted strings into the assistant's reply text.
- **Requirement for Parity:** Update `ChatView.jsx` to render structured tool execution results using a dedicated `ToolResultCard.jsx` component.

### Gap 4: Recommendation Card in Chat Timeline
- **Legacy Source:** `gui/components/recommendation_card.py` (`RecommendationCard`)
- **Legacy Behavior:** Displayed proactive recommendations in the chat stream with priority badges (`HIGH`, `MEDIUM`, `LOW`), actionable descriptions, and expandable evidence.
- **Current Tauri State:** No recommendation card component exists in `ChatView.jsx`.
- **Requirement for Parity:** Create `RecommendationCard.jsx` in `src/components/` and render it when proactive recommendation events arrive.

### Gap 5: Recommendation Lifecycle Interactive Controls (Dismiss, Snooze, Execute)
- **Legacy Source:** `gui/components/recommendation_card.py` (`_on_dismiss_clicked`, `_on_snooze_clicked`, `_on_handle_clicked`)
- **Legacy Behavior:**
  - Dismiss: Suppresses recommendation in SQLite store for 7 days.
  - Snooze: Defers recommendation for 24 hours.
  - Execute: Automatically dispatches the suggested query or command to the assistant.
- **Current Tauri State:** No RPC endpoints exist in `runtime_adapter.py` for recommendation lifecycle transitions, and no React UI controls exist.
- **Requirement for Parity:** Implement `recommendations.dismiss`, `recommendations.snooze`, and `recommendations.execute` in `runtime_adapter.py` and bind them to interactive buttons in `RecommendationCard.jsx`.

### Gap 6: NVIDIA Model Selection Radio Group (4 Models)
- **Legacy Source:** `gui/views/settings_view.py` (`_build_connection_section`)
- **Legacy Behavior:** Presented radio cards allowing users to choose between the 4 supported NVIDIA models:
  1. `nvidia/llama-3.1-nemotron-70b-instruct` (Default / Reasoning)
  2. `meta/llama-3.1-70b-instruct` (Fast General)
  3. `openbmb/minicpm-v-2_6` (Vision / Multimodal)
  4. `mistralai/mistral-large-2-instruct` (Code & Logic)
  Choice persisted to `gui_settings.json` and governed model routing.
- **Current Tauri State:** `SettingsView.jsx` displays informational text explaining the L1/L2/L3 routing architecture, but completely lacks interactive radio buttons to change the active model.
- **Requirement for Parity:** Add a Model Selection radio group in `SettingsView.jsx` calling `updateSettings({ model: selectedModel })`.

### Gap 7: Proactive Assistant Settings Controls
- **Legacy Source:** `gui/views/settings_view.py` (`_build_proactive_section`)
- **Legacy Behavior:**
  - Morning Briefing Toggle (`briefing_enabled`).
  - Delivery time text entry with validation and Save button (`briefing_time`, e.g. "08:30").
  - Contextual Recommendations Toggle (`advisories_enabled`).
  - Recommendation Cooldown dropdown selector (`advisory_cooldown`: "10m", "30m", "1h", "4h").
- **Current Tauri State:** The Proactive Assistant section is entirely omitted from `SettingsView.jsx`.
- **Requirement for Parity:** Implement the Proactive Settings section in `SettingsView.jsx` connected to `settings.get` and `settings.update`.

### Gap 8: Reminder Due UI Notification Banner / Toast
- **Legacy Source:** `gui/app.py` (`_on_scheduler_reminder_due`, `_deliver_notification_to_chat`)
- **Legacy Behavior:** When a scheduled reminder became due, the app automatically injected an alert into the conversation timeline: `"⏰ Reminder: <message>"`.
- **Current Tauri State:** `runtime_adapter.py` emits `scheduler.reminder_due` and Rust converts it to Tauri event `scheduler_reminder_due`. However, React's `ApplicationShell.jsx` has NO listener registered for this event, so reminders fire silently without notifying the user.
- **Requirement for Parity:** Register an `onEvent('scheduler_reminder_due')` listener in `ApplicationShell.jsx` to append a notification card or toast to the chat timeline.

### Gap 9: Recurring Morning Briefing Background Checker
- **Legacy Source:** `gui/app.py` (`_check_morning_briefing`)
- **Legacy Behavior:** A 60-second periodic timer evaluated whether morning briefings were enabled and whether the current wall-clock time had reached the configured delivery time (`briefing_time`).
- **Current Tauri State:** `runtime_adapter.py` does not contain a morning briefing evaluation timer.
- **Requirement for Parity:** Add a daemon worker thread in `runtime_adapter.py` running the 60s briefing evaluation loop.

### Gap 10: Morning Briefing Synthesis & Chat Delivery
- **Legacy Source:** `gui/app.py` (`_on_morning_briefing_raw_output`, `DailyBriefingCollector`, `synthesizer.py`)
- **Legacy Behavior:** When due, synthesized project health, git changes, pending jobs, and weather/schedule into a briefing and injected it into the chat timeline with delivery acknowledgement tracking.
- **Current Tauri State:** Absent in Tauri.
- **Requirement for Parity:** Hook briefing synthesis into the adapter worker and emit an `assistant.briefing_ready` event over JSON-RPC.

### Gap 11: Idle Recommendation Inactivity Evaluator
- **Legacy Source:** `gui/app.py` (`_check_idle_recommendations`, `_run_idle_recommendation_worker`)
- **Legacy Behavior:** A 30-second timer tracked user keyboard/mouse activity. When idle for > 10 minutes (600 seconds) and unacknowledged recommendations existed in `briefing.db`, evaluated high/medium priority recommendations.
- **Current Tauri State:** No idle inactivity tracking exists in the Tauri frontend or Python runtime.
- **Requirement for Parity:** Implement user interaction timestamp tracking in React and emit idle status, or run an inactivity timer in `runtime_adapter.py`.

### Gap 12: Startup Project Reconciliation
- **Legacy Source:** `gui/app.py` (`_run_startup_reconciliation`, `EventCoordinator`)
- **Legacy Behavior:** On application launch, background worker initiated an initial event reconciliation cycle across Git commit logs, file modification watermarks, and overdue reminders.
- **Current Tauri State:** `runtime_adapter.py` initializes the scheduler but does not invoke `EventCoordinator.trigger_reconciliation()`.
- **Requirement for Parity:** Trigger `EventCoordinator.trigger_reconciliation(reason="startup")` during `main.ensure_initialized()` in `runtime_adapter.py`.

---

## 5. LIST OF PARTIALLY INTEGRATED CAPABILITIES (2 ITEMS)

### Partial 1: System Theme Mode Auto-Detection
- **Legacy Source:** `gui/theme.py` (`_get_system_theme`, Windows Registry query)
- **Current Tauri State:** `ThemeContext.jsx` supports toggling between `'dark'` and `'light'`, and persists the choice to `gui_settings.json`. However, it lacks a `'system'` option that synchronizes with the OS light/dark mode via `window.matchMedia('(prefers-color-scheme: dark)')`.
- **Parity Gap:** Users cannot select "System" mode to have the application automatically track Windows OS dark/light mode schedule.

### Partial 2: Editable API URL Configuration in UI
- **Legacy Source:** `gui/views/settings_view.py` (`_build_connection_section`)
- **Current Tauri State:** The backend adapter (`settings.update`) accepts custom `api_url` parameters. However, `SettingsView.jsx` displays the endpoint inside a static `<code>` block rather than an editable text `<input>`, preventing users from testing local API proxies or staging URLs directly from the UI.
- **Parity Gap:** URL is read-only in the React settings interface.

---

## 6. OBSOLETE CAPABILITIES WITH JUSTIFICATION (1 ITEM)

### Obsolete 1: Home Screen Action Cards
- **Legacy Source:** `gui/components/action_cards.py` (`ActionCardsFrame`)
- **Legacy Behavior:** Displayed 4 large clickable prompt cards on the Home screen ("Work on a project", "Analyze files", "Plan my day", "Use my computer").
- **Classification:** **LEGACY ONLY** (Deliberately Retired)
- **Justification:** The project visual authority for Orange AI Desktop 2.0 is the **approved Nano Banana reference design** (`media_1794590629415_3598d12d.png`). The approved reference mandates a minimalist, distraction-free home experience consisting solely of the top-left brand mark, personalized welcome greeting, large faceted 3D orb with ambient illumination, and a floating bottom composer. Prompt cards were deliberately removed to achieve this aesthetic.
- **Status:** Should NOT be restored to the Home view. If desired, prompt cards can be introduced as an optional drawer or command palette shortcut in future phases, but their absence from Home is intentional and compliant with design authority.

---

## 7. DEPENDENCIES & MIGRATION RISKS

### 7.1 JSON-RPC Stdio IPC Framing & Event Flooding
- **Risk:** High-frequency event emissions (e.g. log streaming or rapid scheduler checks) over standard I/O could saturate the line-buffered pipe between Rust and Python.
- **Mitigation:** Maintain strict line-delimited JSON (`
`) framing with batching for log events. Rust `BufReader.read_until(b'
')` handles lines asynchronously without blocking the tokio event loop.

### 7.2 Windows Job Object vs. Subprocess Spawning
- **Risk:** If Python spawns secondary sub-processes (e.g. via `subprocess.Popen` in `tools/command.py` or `tools/apps.py`), nested processes must inherit the Job Object limits to ensure clean cleanup.
- **Mitigation:** The existing `SafeJobObject` in `src-tauri/src/job_object.rs` sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Windows automatically assigns child processes of assigned parents to the same job object unless `CREATE_BREAKAWAY_FROM_JOB` is explicitly passed.

### 7.3 Multi-Threading Synchronization in Python Runtime Adapter
- **Risk:** Adding background daemon threads for the 60s morning briefing checker, 30s idle recommendation checker, and event reconciliation introduces concurrency with incoming JSON-RPC dispatch calls.
- **Mitigation:** All shared database connections in `brain/database.py` and `brain/jobs/store.py` use SQLite with proper timeout/WAL settings or separate thread connections. Use Python's `threading.Lock` when modifying shared in-memory coordinator state.

### 7.4 Webview React Rendering & Markdown Injection Security
- **Risk:** Rendering raw markdown from LLM outputs could expose the React shell to Cross-Site Scripting (XSS) if HTML tags are not properly sanitized.
- **Mitigation:** Use `react-markdown` with default HTML escaping enabled. Do NOT use `dangerouslySetInnerHTML`. Ensure all links open externally via Tauri's shell plugin or prevent navigation within the main window.

---

## 8. RECOMMENDED IMPLEMENTATION ORDER (STAGE 2 EXECUTION ROADMAP)

To bring Orange AI Desktop 2.0 from its current **79.4% PARTIAL PARITY** to **100% FULL PARITY**, work should be executed in 4 sequenced stages:

```
+---------------------------------------------------------------------------------+
| STAGE 2A: Timeline Rich Cards & Markdown Rendering (Priority: High)             |
| - React Markdown renderer with syntax highlighted code blocks                   |
| - ToolResultCard component with collapsible stdout & clipboard copy             |
| - RecommendationCard component with priority pills & evidence viewer            |
+---------------------------------------------------------------------------------+
                                      |
                                      v
+---------------------------------------------------------------------------------+
| STAGE 2B: Settings View Completion & Model Selector (Priority: High)            |
| - 4-NVIDIA-Model radio selection cards (Nemotron, Llama 70B, MiniCPM, Mistral)  |
| - Proactive Assistant settings (Morning Briefing toggle + time picker)          |
| - Contextual Advisories settings (Toggle + cooldown dropdown)                   |
| - System theme auto-detection & editable API URL input                          |
+---------------------------------------------------------------------------------+
                                      |
                                      v
+---------------------------------------------------------------------------------+
| STAGE 2C: Proactive Automation & Background Workers (Priority: Medium-High)     |
| - Background 60s morning briefing evaluation loop in runtime_adapter.py         |
| - Briefing synthesis & JSON-RPC event delivery (`assistant.briefing_ready`)     |
| - Inactivity / idle recommendation evaluator (10m threshold)                    |
| - Startup event reconciliation trigger in Python runtime                        |
+---------------------------------------------------------------------------------+
                                      |
                                      v
+---------------------------------------------------------------------------------+
| STAGE 2D: Event Routing & Notification Integration (Priority: Medium)           |
| - React event listeners for `scheduler_reminder_due` (chat toast / banner)     |
| - React event listeners for `assistant_briefing_ready`                          |
| - React event listeners for `assistant_recommendation_ready`                    |
| - Recommendation lifecycle RPC endpoints (dismiss, snooze, execute)             |
+---------------------------------------------------------------------------------+
```

---

## 9. COMPREHENSIVE TEST PLAN FOR MISSING & PARTIAL CAPABILITIES

### Test Suite 1: Timeline Rich Cards & Markdown
1. **Markdown Formatting:** Send prompt `"Format a markdown test with H1, bold text, a blockquote, and an unordered list"`.
   - *Assertion:* ChatView renders semantic HTML elements (`<h1>`, `<strong>`, `<blockquote>`, `<ul>`) rather than raw `#` and `*` text.
2. **Code Syntax & Copy:** Send prompt `"Show a python function that calculates fibonacci"`.
   - *Assertion:* Renders inside a styled code block with a visible "Copy" button. Clicking copy populates the clipboard with the exact code snippet.
3. **Tool Result Collapsible Card:** Run tool `list_files` on a directory with > 20 files.
   - *Assertion:* Tool output renders in `ToolResultCard`, collapsed by default (>10 lines), with status badge `SUCCESS`, expand/collapse toggle, and copy button.

### Test Suite 2: Settings View & Model Selection
4. **Model Switching:** In SettingsView, select `mistralai/mistral-large-2-instruct`.
   - *Assertion:* `gui_settings.json` is updated with `"model": "mistralai/mistral-large-2-instruct"`. Subsequent inference requests send the selected model ID in the API payload.
5. **Proactive Settings Persistence:** Toggle morning briefing off, set delivery time to `"09:15"`, and set advisory cooldown to `"1h"`.
   - *Assertion:* Settings update RPC call succeeds. Reopening settings restores the saved configuration.
6. **System Theme Detection:** Switch theme to "System", toggle Windows OS theme between dark and light mode.
   - *Assertion:* Tauri window immediately synchronizes with OS theme without restart.

### Test Suite 3: Proactive Automation & Briefings
7. **Morning Briefing Due Trigger:** Mock the briefing delivery time to the current minute.
   - *Assertion:* Within 60 seconds, `runtime_adapter.py` detects due briefing, synthesizes briefing text, and emits `assistant.briefing_ready`. The briefing appears in the chat timeline.
8. **Idle Recommendation Trigger:** Simulate 605 seconds of inactivity with pending recommendation records in `briefing.db`.
   - *Assertion:* Adapter evaluates recommendations and dispatches `assistant.recommendation_ready`. ChatView renders `RecommendationCard`.
9. **Recommendation Lifecycle:** Click "Dismiss" on a recommendation card.
   - *Assertion:* RPC `recommendations.dismiss` is called. The recommendation is marked dismissed with a 7-day suppression timestamp in `briefing.db`.

### Test Suite 4: Reminders & Scheduler Notifications
10. **Reminder Due Notification:** Create a reminder due in 10 seconds: `"Remind me in 10 seconds to check the build"`.
    - *Assertion:* When the reminder fires in the Python scheduler, Rust emits `scheduler_reminder_due`. React displays an alert banner or chat card: `"⏰ Reminder: check the build"`.

---

## 10. CONCLUSION & NEXT STEPS

The Stage 1 Feature Parity Audit confirms that **Orange AI Desktop 2.0 (Tauri) has achieved a solid 79.4% functional parity** with the retired Tkinter application. The core agent intelligence, permissions, tools, memory, jobs, activity tracing, and desktop shell are fully mature and operating under production-grade safety mechanisms.

The remaining 20.6% gap consists of well-defined proactive automation features, settings controls, and rich card presentation components. With the source-level evidence, architecture mapping, and test plan established in this report, the team is fully prepared to execute Stage 2 implementation upon user authorization.
