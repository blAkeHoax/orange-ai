# ORANGE AI v2.0.0: DEFECT REGISTER & BUG REPORT
**Authoritative Defect Register Before Stage 5 JARVIS Implementation**

**Audit Execution Date:** 2026-11-20  
**Application:** Orange AI Desktop v2.0.0 (Tauri 2 + Python Runtime Sidecar)  
**Workspace:** `D:\Orange AI\Orange AI Tauri`  
**Classification Priorities:**
- **P0:** Data loss, security compromise, or application unusable.
- **P1:** Critical feature failure, severe runtime failure, or major reliability defect.
- **P2:** Functional defect with a workaround or limited impact.
- **P3:** Cosmetic, minor UX, or low-impact defect.

---

## 1. DEFECT SUMMARY TABLE

| Defect ID | Severity | Category | Affected Component | Summary | Status |
|---|---|---|---|---|---|
| **BUG-API-001** | **P1** | Backend Contract | `SettingsView.jsx`, `runtime_adapter.py` | Hosted Orange API model ID mismatch; HTTP 400 on inference | Confirmed |
| **BUG-RT-001** | **P1** | Runtime Reliability | `src-tauri/src/python_runtime.rs` | Silent Python adapter crash; supervisor stays Ready; 120s RPC hang | Confirmed |
| **SEC-001** | **P1** | Security / Defense | `src-tauri/tauri.conf.json` | Content Security Policy (CSP) is explicitly disabled (`null`) | Confirmed |
| **SEC-002** | **P1** | Security / Integrity | `src-tauri/tauri.conf.json` | Tauri Updater configured with empty public key string (`pubkey: ""`) | Confirmed |
| **BUG-API-002** | **P2** | Backend Integration | `runtime_adapter.py`, `synthesizer.py` | Morning briefing remote LLM synthesis fails; permanently degraded to fallback | Confirmed |
| **BUG-FE-001** | **P2** | Frontend Presentation | `src/components/ApplicationShell.jsx` | Corrupted UTF-8 regex mojibake (`ðŸ’¡`) prevents stripping advisory text | Confirmed |
| **BUG-RT-003** | **P2** | Configuration / State | `runtime_adapter.py`, `gui/settings.py` | Split-brain settings storage between AppData and legacy workspace | Confirmed |
| **BUG-DB-001** | **P2** | Database Concurrency | `Orange AI Desktop/brain/memory.py` | Unsynchronized global SQLite connection shared across concurrent threads | Confirmed Risk |
| **BUG-FE-002** | **P2** | Frontend Architecture | `src/components/ApplicationShell.jsx` | Async `useEffect` race leaves orphaned Tauri webview event listeners | Confirmed |
| **SEC-003** | **P2** | Security / Architecture | `src-tauri/src/commands.rs` | Spawns `cmd.exe /C start` to open URLs instead of native ShellExecute | Confirmed |
| **BUG-RT-002** | **P3** | Diagnostics / Logging | `runtime/runtime_adapter.py:75` | False "Desktop workspace path not found" warning when in `sys.path` | Confirmed |
| **BUG-FE-003** | **P3** | User Experience | `src/components/Composer.jsx` | Single-line `<input>` prevents multiline input (Shift+Enter) in chat | Confirmed |
| **BUG-FE-004** | **P3** | User Experience | `src/components/Composer.jsx` | Dead Attachment and Microphone buttons with `console.log` placeholders | Confirmed |
| **BUG-ENV-001**| **P2** | Build Environment | `src-tauri` Cargo MinGW toolchain | `cargo test --lib` fails with MinGW/Clang linker error (`-lgcc`, `-lgcc_eh`) | Confirmed Env |

---

## 2. DETAILED DEFECT SPECIFICATIONS

### BUG-API-001
- **Severity:** P1 (Critical Feature Failure)
- **Affected Component:** Settings & API Client Integration (`SettingsView.jsx:28-56`, `runtime/runtime_adapter.py:128, 346-354`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src\components\views\SettingsView.jsx#L28-L56`
  - `D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py#L128`
  - `D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py#L346-L354`
  - `D:\Orange AI\Orange API\app\services\model_registry.py#L40-L108`
- **Reproduction Steps:**
  1. Launch Orange AI Desktop.
  2. In Settings -> Model Selection, leave the default model (`nvidia/llama-3.1-nemotron-70b-instruct`) or select any of the 4 models (`meta/llama-3.1-70b-instruct`, etc.).
  3. Send any conversational chat message from the Chat view (e.g., "Hello").
- **Expected Behavior:**
  The request routes to the hosted Orange API with a valid model identifier recognized by the server, returning a streaming or complete conversational response.
- **Actual Behavior:**
  The hosted Orange API rejects the request with HTTP 400:
  `{"detail":"Unknown model identifier 'nvidia/llama-3.1-nemotron-70b-instruct'."}`.
  The chat view renders: `Error executing request: Error processing user request: Orange API error (400): Unknown model identifier 'nvidia/llama-3.1-nemotron-70b-instruct'.`
- **Root Cause:**
  Stage 2B introduced a hardcoded four-model roster in `SettingsView.jsx` and wrapped `api_client.assist()` with `_model_aware_assist()` in `runtime_adapter.py` to inject `curr.get("model", DEFAULT_MODEL)`. However, the production hosted Orange API (`https://orange-api-cuuo.onrender.com`) enforces a completely different model registry in `app/services/model_registry.py`:
  - `nvidia/nemotron-3.5-lightning-30b-a3b` (Default, available)
  - `z-ai/glm-5.3-flash` (Available)
  - `openai/gpt-oss-20b` (Unavailable)
  - `google/gemma-4-31b-it` (Unavailable)
  Because none of the desktop's 4 models exist in the hosted backend's registry, every request transmitting a model is unconditionally rejected.
- **Evidence:**
  Direct live HTTP probe against `https://orange-api-cuuo.onrender.com/assist`:
  - `model=None` -> HTTP 200 (uses backend default `nvidia/nemotron-3.5-lightning-30b-a3b`)
  - `model='nvidia/llama-3.1-nemotron-70b-instruct'` -> HTTP 400 `Unknown model identifier`
  - `model='meta/llama-3.1-70b-instruct'` -> HTTP 400 `Unknown model identifier`
  - `model='openbmb/minicpm-v-2_6'` -> HTTP 400 `Unknown model identifier`
  - `model='mistralai/mistral-large-2-instruct'` -> HTTP 400 `Unknown model identifier`
- **Recommended Correction:**
  Align the desktop's model catalog and `DEFAULT_MODEL` with the hosted backend's supported registry (`nvidia/nemotron-3.5-lightning-30b-a3b` as default, `z-ai/glm-5.3-flash` as alternative), or update the hosted backend model registry if 70B models are intended.
- **Regression Test Required:**
  Automated integration test sending real user chat turns through `runtime_adapter.handle_chat_send()` verifying HTTP 200 and valid text return without HTTP 400 errors.

---

### BUG-RT-001
- **Severity:** P1 (Severe Runtime Reliability Defect)
- **Affected Component:** Rust Python Runtime Supervisor (`src-tauri/src/python_runtime.rs`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src-tauri\src\python_runtime.rs#L300-L345`
  - `D:\Orange AI\Orange AI Tauri\src-tauri\src\python_runtime.rs#L430-L450`
  - `D:\Orange AI\Orange AI Tauri\src-tauri\src\python_runtime.rs#L540-L560`
- **Reproduction Steps:**
  1. Start Orange AI Desktop (Rust supervisor launches child `runtime_adapter.exe` and verifies handshake).
  2. Kill the child `runtime_adapter.exe` process via Task Manager or external SIGKILL.
  3. Send a message or trigger any RPC call (`ping`, `send_message`, `get_memory`) from the frontend.
- **Expected Behavior:**
  The supervisor immediately detects child process termination on EOF, transitions `supervisor.status` to `HandshakeStatus::ProcessTerminated`, emits a `runtime_terminated` event to the frontend, fails pending requests immediately with a clear error, and transitions the UI to `RecoveryView` with a "Restart Engine" action.
- **Actual Behavior:**
  The background stdout reader loop in `python_runtime.rs` breaks silently on EOF, logging `[python-stdout] EOF reached`. `supervisor.status` remains in `HandshakeStatus::Ready`. The new request attempts to write to the closed stdin pipe and hangs for the full 120-second timeout. The frontend never shows `RecoveryView`.
- **Root Cause:**
  The stdout/stderr reader tasks in `python_runtime.rs` have no callback or reference to `RuntimeSupervisor` to mutate `status` upon EOF, nor do they drain `pending_requests` with a cancellation error.
- **Evidence:**
  Code inspection of `python_runtime.rs#L305-L350`.
- **Recommended Correction:**
  1. Pass an `Arc<Mutex<HandshakeStatus>>` and a reference to `supervisor` into the stdout reader task.
  2. When `read_until` returns `Ok(0)` (EOF), immediately set `*status = HandshakeStatus::ProcessTerminated`, drain and fail all channels in `pending_requests`, and emit `app_handle.emit("runtime_terminated", json!({"reason": "Child process exited unexpectedly"}))`.
- **Regression Test Required:**
  Unit test that spawns a dummy child process that terminates after handshake and verifies that `supervisor.get_status()` updates to `ProcessTerminated` and in-flight calls reject immediately without waiting 120s.

---

### SEC-001
- **Severity:** P1 (Security / Defense-in-Depth)
- **Affected Component:** Tauri Configuration (`src-tauri/tauri.conf.json`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src-tauri\tauri.conf.json#L28`
- **Reproduction Steps:**
  Inspect `src-tauri/tauri.conf.json`.
- **Expected Behavior:**
  A strict Content Security Policy restricting script execution to `'self'`, allowing only authorized API origins (`https://orange-api-cuuo.onrender.com`), and blocking unsafe inline code and object evaluation.
- **Actual Behavior:**
  `"security": { "csp": null }` is configured, completely disabling CSP enforcement in the WebView2 container.
- **Root Cause:**
  Development placeholder was left unconfigured in release configuration.
- **Evidence:**
  `"security": { "csp": null }` in `tauri.conf.json`.
- **Recommended Correction:**
  Configure a strict CSP policy:
  ```json
  "security": {
    "csp": "default-src 'self'; connect-src 'self' https://orange-api-cuuo.onrender.com; img-src 'self' data: asset:; style-src 'self' 'unsafe-inline'; script-src 'self';"
  }
  ```
- **Regression Test Required:**
  Configuration validation test asserting `csp` is non-null and includes necessary origin restrictions.

---

### SEC-002
- **Severity:** P1 (Security / Update Integrity)
- **Affected Component:** Tauri Auto-Updater Configuration (`src-tauri/tauri.conf.json`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src-tauri\tauri.conf.json#L54-L59`
- **Reproduction Steps:**
  Inspect `tauri.conf.json` lines 54-59.
- **Expected Behavior:**
  Auto-updater requires a valid minisign/ed25519 public key in `plugins.updater.pubkey` to verify the cryptographic signature of any downloaded installer before execution.
- **Actual Behavior:**
  `"pubkey": ""` is empty while the updater endpoint points to a public GitHub releases download URL.
- **Root Cause:**
  Updater plugin was initialized without generating or configuring signing keys.
- **Evidence:**
  ```json
  "plugins": {
    "updater": {
      "pubkey": "",
      "endpoints": [
        "https://github.com/blAkeHoax/orange-ai/releases/latest/download/latest.json"
      ]
    }
  }
  ```
- **Recommended Correction:**
  Generate an ed25519 updater keypair using Tauri CLI (`npm run tauri signer generate`), configure the public key in `tauri.conf.json`, or disable the updater plugin until formal signing infrastructure is established.
- **Regression Test Required:**
  Automated config audit test verifying updater is either disabled or configured with a valid public key.

---

### BUG-API-002
- **Severity:** P2 (Functional Defect / Feature Degradation)
- **Affected Component:** Daily Briefing Synthesizer (`runtime_adapter.py:850-920`, `synthesizer.py`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py#L860-L910`
  - `D:\Orange AI\Orange AI Desktop\brain\briefing\synthesizer.py#L85-L120`
- **Reproduction Steps:**
  1. Trigger morning briefing evaluation via `_evaluate_morning_briefing(date_str)`.
  2. Inspect the resulting `daily_briefings` record in `memory.db`.
- **Expected Behavior:**
  Briefing synthesizer invokes hosted Orange API and persists briefing with `status='success'` and `model_name` reflecting remote foundation model.
- **Actual Behavior:**
  The call fails with HTTP 400 (`Unknown model identifier`), logs `[BRIEFING SYNTHESIZER] Orange API synthesis failed; using deterministic fallback`, and persists record with `status='fallback'` and `model_name='local_deterministic'`.
- **Root Cause:**
  Same root cause as BUG-API-001: briefing synthesizer transmits `DEFAULT_MODEL` (`nvidia/llama-3.1-nemotron-70b-instruct`) which is rejected by the hosted backend.
- **Evidence:**
  Logs from test suite run:
  `[PY-ADAPTER WARNING 2026-11-16 15:19:48,459] Orange API HTTP error 400: Unknown model identifier 'nvidia/llama-3.1-nemotron-70b-instruct'.`
  `[PY-ADAPTER WARNING 2026-11-16 15:19:48,460] [BRIEFING SYNTHESIZER] Orange API synthesis failed; using deterministic fallback`
- **Recommended Correction:**
  Resolve BUG-API-001 by aligning model identifier with the backend registry.
- **Regression Test Required:**
  End-to-end briefing test asserting `status == 'success'` and `model_name != 'local_deterministic'`.

---

### BUG-FE-001
- **Severity:** P2 (Functional Defect / UI Glitch)
- **Affected Component:** React Application Shell (`src/components/ApplicationShell.jsx`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src\components\ApplicationShell.jsx#L144`
  - `D:\Orange AI\Orange AI Desktop\main.py#L574`
- **Reproduction Steps:**
  1. Send a user message that triggers a contextual recommendation from the Python engine.
  2. Inspect the rendered assistant message in the chat timeline.
- **Expected Behavior:**
  The embedded text advisory is stripped from the assistant message bubble because a structured `RecommendationCard` is rendered below it.
- **Actual Behavior:**
  The raw markdown advisory `💡 **Orange AI Advisory** [PRIORITY]: **Title**` remains in the text bubble, AND the `RecommendationCard` renders below it, showing duplicate advisory information.
- **Root Cause:**
  Line 144 in `ApplicationShell.jsx` contains corrupted UTF-8 mojibake:
  `const parts = replyText.split(/\n+ðŸ’¡\s+\*\*Orange AI Advisory\*\*/);`
  The string `ðŸ’¡` is the result of UTF-8 byte sequence `0xF0 0x9F 0x92 0xA1` (emoji `💡`) being decoded as Windows-1252 / ISO-8859-1. Because Python emits authentic UTF-8 `💡`, the regex never matches and does not split.
- **Evidence:**
  Source inspection of `ApplicationShell.jsx#L144`.
- **Recommended Correction:**
  Replace mojibake with unicode escape sequence:
  `const parts = replyText.split(/\n+(?:💡|\u{1F4A1})\s+\*\*Orange AI Advisory\*\*/u);`
- **Regression Test Required:**
  DOM test feeding an assistant reply containing `\n\n💡 **Orange AI Advisory** [HIGH]: **Test**` and asserting the chat bubble does not contain duplicate advisory text.

---

### BUG-RT-003
- **Severity:** P2 (State Synchronization / Split-Brain)
- **Affected Component:** Settings Persistence (`runtime/runtime_adapter.py:178`, `gui/settings.py:19`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py#L178`
  - `D:\Orange AI\Orange AI Desktop\gui\settings.py#L19`
- **Reproduction Steps:**
  1. In the Tauri Settings view, toggle Morning Briefing to Enabled.
  2. Inspect `C:\Users\User\AppData\Local\Orange AI\gui_settings.json`.
  3. Inspect `D:\Orange AI\Orange AI Desktop\gui_settings.json`.
- **Expected Behavior:**
  Both frontend and backend modules read from and write to the same single authoritative settings file in `get_user_data_dir()`.
- **Actual Behavior:**
  Tauri writes to `%LOCALAPPDATA%\Orange AI\gui_settings.json`. But `gui.settings` in `Orange AI Desktop` writes to `D:\Orange AI\Orange AI Desktop\gui_settings.json`. Core Python scheduling routines inspecting `is_morning_briefing_enabled()` read from the desktop directory and see `morning_briefing_enabled: false`.
- **Root Cause:**
  `gui/settings.py` calls `get_project_root() / "gui_settings.json"`, which resolves to the workspace directory in development mode, while `runtime_adapter.py` forces `get_user_data_dir()`.
- **Evidence:**
  Verified disk inspection:
  `C:\Users\User\AppData\Local\Orange AI\gui_settings.json` has `morning_briefing_enabled: false` and theme `dark`.
  `D:\Orange AI\Orange AI Desktop\gui_settings.json` has `theme: light` and `last_briefing_date: null`.
- **Recommended Correction:**
  Ensure `gui/settings.py` strictly uses `get_user_data_dir()` for `get_settings_path()`, guaranteeing that both the Tauri adapter and all core Python routines access the identical file path regardless of runtime mode.
- **Regression Test Required:**
  Test asserting that `settings.update` via RPC immediately reflects in `brain.briefing.settings.is_morning_briefing_enabled()`.

---

### BUG-DB-001
- **Severity:** P2 (Suspected Concurrency Risk)
- **Affected Component:** SQLite Connection Management (`Orange AI Desktop/brain/memory.py:39-160`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Desktop\brain\memory.py#L39-L43`
  - `D:\Orange AI\Orange AI Desktop\brain\memory.py#L124-L160`
- **Reproduction Steps:**
  Trigger simultaneous execution of a conversational chat turn (writing history on `TurnWorker`), background reminder evaluation (reading/writing reminders), and frontend activity polling (`activity.get`) in rapid parallel threads.
- **Expected Behavior:**
  All database operations are serialized safely across threads or use thread-isolated connections.
- **Actual Behavior:**
  `memory.py` caches a single module-level `_conn` object opened with `check_same_thread=False` and shares it across all threads without a mutex lock. Under high concurrent load, cursor re-entrancy conflicts or locked database exceptions can occur.
- **Root Cause:**
  `check_same_thread=False` disables Python's internal thread assertion but does not provide thread safety for concurrent cursor execution on a single SQLite handle.
- **Evidence:**
  Code inspection of `memory.py#L39` (`_conn = None`) and lack of thread locks in `get_connection()`.
- **Recommended Correction:**
  Protect `_conn` access with a re-entrant thread lock (`threading.RLock`), or adopt thread-local storage (`threading.local()`) for database connections.
- **Regression Test Required:**
  Multithreaded stress test running 50 concurrent reader and writer threads against `memory.get_connection()`.

---

### BUG-FE-002
- **Severity:** P2 (Memory Leak / Event Listener Race)
- **Affected Component:** Shell Event Subscriptions (`src/components/ApplicationShell.jsx:110-230`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src\components\ApplicationShell.jsx#L110-L230`
- **Reproduction Steps:**
  Mount and immediately unmount `ApplicationShell` (e.g. during fast tab switching or simulated degraded startup retry).
- **Expected Behavior:**
  All registered Tauri event listeners are cleanly unsubscribed.
- **Actual Behavior:**
  `initRuntime()` is an un-cancelled async function inside `useEffect`. If unmounted before promises resolve, unlisteners pushed to `unlisteners` array after cleanup execution remain permanently active in the Tauri webview event bus.
- **Root Cause:**
  Lack of an `isMounted` flag inside `initRuntime()` to immediately invoke unlisteners if unmounted during promise resolution.
- **Evidence:**
  Code inspection of `ApplicationShell.jsx#L110-L230`.
- **Recommended Correction:**
  Add `let isMounted = true;` in `useEffect`, check `if (!isMounted) return;` after each `await`, and immediately call `u()` if unmounted.
- **Regression Test Required:**
  React component lifecycle unit test simulating rapid mount/unmount and verifying zero dangling listeners.

---

### SEC-003
- **Severity:** P2 (Security Architecture Anti-Pattern)
- **Affected Component:** Shell URL Opener (`src-tauri/src/commands.rs:35-43`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src-tauri\src\commands.rs#L35-L43`
- **Reproduction Steps:**
  Click "Releases" or invoke `open_official_releases`.
- **Expected Behavior:**
  URL is opened via Windows Shell API (`ShellExecuteW`) or Tauri's native `opener` plugin without spawning a command prompt.
- **Actual Behavior:**
  Rust spawns `cmd.exe /C start "" <url>`.
- **Root Cause:**
  Use of command shell process wrapper instead of direct Windows API.
- **Evidence:**
  `std::process::Command::new("cmd").args(["/C", "start", "", url]).spawn()` in `commands.rs#L39`.
- **Recommended Correction:**
  Replace with Tauri's `@tauri-apps/plugin-opener` or direct Win32 `ShellExecuteW`.
- **Regression Test Required:**
  Unit test asserting `open_official_releases` opens external browser without invoking `cmd.exe`.

---

### BUG-RT-002
- **Severity:** P3 (Diagnostic / Log Cleanliness)
- **Affected Component:** Path Resolution Logging (`runtime/runtime_adapter.py:75`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\runtime\runtime_adapter.py#L75-L80`
- **Reproduction Steps:**
  Run any test script that inserts `D:\Orange AI\Orange AI Desktop` into `sys.path` before importing `runtime_adapter`.
- **Expected Behavior:**
  `runtime_adapter` logs that the desktop workspace is present or already in `sys.path`.
- **Actual Behavior:**
  Logs false warning: `[PY-ADAPTER WARNING] Desktop workspace path not found: D:\Orange AI\Orange AI Desktop`.
- **Root Cause:**
  `if os.path.exists(_desktop_workspace) and _desktop_workspace not in sys.path:`
  If the directory exists but IS already in `sys.path`, the condition evaluates to `False`, hitting the `else:` branch which logs `"path not found"`.
- **Evidence:**
  Verbatim output from test runs: `[PY-ADAPTER WARNING 2026-11-20 00:08:11,246] Desktop workspace path not found: D:\Orange AI\Orange AI Desktop`.
- **Recommended Correction:**
  Separate the existence check from the `sys.path` check:
  ```python
  if os.path.exists(_desktop_workspace):
      if _desktop_workspace not in sys.path:
          sys.path.insert(0, _desktop_workspace)
          logger.info("Added desktop workspace to sys.path: %s", _desktop_workspace)
  else:
      logger.warning("Desktop workspace path not found: %s", _desktop_workspace)
  ```
- **Regression Test Required:**
  Import test asserting no warning is logged when path already exists in `sys.path`.

---

### BUG-FE-003 & BUG-FE-004
- **Severity:** P3 (User Experience / Polish)
- **Affected Component:** Composer (`src/components/Composer.jsx:26-55`)
- **File & Line References:**
  - `D:\Orange AI\Orange AI Tauri\src\components\Composer.jsx#L26-L55`
- **Reproduction Steps:**
  1. Attempt to enter a multiline prompt using Shift+Enter.
  2. Click Attachment or Microphone buttons.
- **Expected Behavior:**
  Shift+Enter inserts a newline into the prompt; Attachment opens file picker dialog; Mic toggles audio capture.
- **Actual Behavior:**
  Input field is `<input type="text">` so Shift+Enter does nothing and long text scrolls horizontally. Attachment and Mic only log to browser console.
- **Root Cause:**
  Visual shell placeholders from Stage 2A/2B not upgraded to functional controls.
- **Recommended Correction:**
  Replace `<input>` with auto-resizing `<textarea>` supporting Shift+Enter newlines, and wire attachment dialog to `open_dialog` tool.
- **Regression Test Required:**
  DOM test verifying newline entry on Shift+Enter.

---

### BUG-ENV-001
- **Severity:** P2 (Build Environment / Toolchain)
- **Affected Component:** Rust / MinGW Linker Toolchain (`src-tauri` Cargo build)
- **File & Line References:**
  - `src-tauri/Cargo.toml`
  - System PATH: `x86_64-w64-mingw32-gcc`, `clang-23`, `lld`
- **Reproduction Steps:**
  Run `cargo test --manifest-path "D:\Orange AI\Orange AI Tauri\src-tauri\Cargo.toml" --lib`.
- **Expected Behavior:**
  Rust library unit tests compile and link cleanly under MinGW.
- **Actual Behavior:**
  Linker fails with:
  `lld: error: unable to find library -lgcc_eh`
  `lld: error: unable to find library -lgcc`
  `clang-23: error: linker command failed with exit code 1`
- **Root Cause:**
  The Rust target is `x86_64-pc-windows-gnu` while the active C toolchain on PATH uses a Clang/LLD driver that cannot locate MinGW's static runtime libraries.
- **Recommended Correction:**
  Configure `.cargo/config.toml` to specify the explicit MinGW library search path or switch default host toolchain to `x86_64-pc-windows-msvc`.
- **Regression Test Required:**
  Successful execution of `cargo check --lib` and `cargo test --lib`.
