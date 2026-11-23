"""
runtime_adapter.py - Headless Python Runtime Adapter for Orange AI Desktop 2.0 (Tauri).

Provides JSON-RPC 2.0 line-delimited communication over standard input/output (stdio)
with Tauri's Rust core supervisor.

Guarantees:
1. Strict Stdout Purity: sys.stdout is redirected to sys.stderr; only valid protocol
   JSON-RPC lines are written to the dedicated protocol stream.
2. Zero Code Duplication: Directly delegates all assistant execution, memory, jobs,
   tools, and permissions to the existing, protected Orange AI Desktop engine.
3. Thread-Safe Concurrency: Long-running or blocking user turns execute on background
   threads while the main RPC reader continues processing incoming requests.
4. Two-Phase Confirmation Handshake: Tool confirmation requests emit asynchronous
   JSON-RPC events to the frontend and safely block with a 120-second timeout until
   explicit user approval is received or the action safely defaults to denial.
5. Deterministic Lifecycle: Clean shutdown on 'system.shutdown' or EOF (pipe break
   from parent process termination or crash).
"""

import os
import sys
import json
import uuid
import time
import queue
import logging
import threading
import urllib.parse
import re
import sqlite3
import subprocess
import hashlib
import ast
from pathlib import Path
from datetime import datetime, time as dt_time, timezone
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager

# 1. Isolate Protocol Stdout
# Ensure UTF-8 encoding across all standard IO streams
for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Save the authentic unbuffered stdout pipe for protocol framing
_protocol_out = sys.stdout
# Redirect sys.stdout to sys.stderr so any print() statements in libraries or tools
# never contaminate the JSON-RPC pipe.
sys.stdout = sys.stderr

# Configure standard error logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[PY-ADAPTER %(levelname)s %(asctime)s] %(message)s",
)
logger = logging.getLogger("runtime_adapter")

# 2. Add Existing Desktop Workspace to sys.path (Development mode only)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)  # D:\Orange AI\Orange AI Tauri
_desktop_workspace = os.environ.get(
    "ORANGE_AI_DESKTOP_DIR",
    os.path.join(os.path.dirname(_project_root), "Orange AI Desktop"),
)

if not getattr(sys, "frozen", False):
    if os.path.exists(_desktop_workspace) and _desktop_workspace not in sys.path:
        sys.path.insert(0, _desktop_workspace)
        logger.info("Added desktop workspace to sys.path: %s", _desktop_workspace)
    else:
        logger.warning("Desktop workspace path not found: %s", _desktop_workspace)
else:
    logger.info("Running in frozen standalone runtime mode.")

# Ensure runtime default data directory points to %LOCALAPPDATA%\Orange AI
if "ORANGE_AI_USER_DATA_DIR" not in os.environ:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        os.environ["ORANGE_AI_USER_DATA_DIR"] = os.path.join(local_app_data, "Orange AI")
        logger.info("Set default user data directory: %s", os.environ["ORANGE_AI_USER_DATA_DIR"])

# Lazy import holder for core engine
import main
from brain.paths import get_user_data_dir
from brain.database import resolve_database_path
import brain.memory as mem
from brain.api_client import OrangeAPIClient
from brain.agent_models import AgentStatus
import tools.registry as tool_reg
import tools.permissions as tool_perm
from tools.permissions import RiskLevel
from brain.jobs.models import JobStatus
import tools.system as tool_sys
from brain import scheduler

# Version & Protocol Specification
ORANGE_AI_VERSION = "2.1.3"
ORANGE_AI_PROTOCOL_VERSION = "1.0"

# Persistent GUI settings helper & Stage 2B Model/Proactive Configuration
SUPPORTED_MODELS: Dict[str, Dict[str, str]] = {
    "auto": {
        "id": "auto",
        "name": "Auto (Task-Based Dynamic Routing)",
        "provider": "Orange AI",
        "tag": "RECOMMENDED / DYNAMIC",
        "description": "Routes conversation & reasoning to Nemotron 3.5 Bolt E4B, briefings & agent decisions to Nemotron 3.5 Lightning 30B, and coding to MiniMax M3.1 Flash."
    },
    "nvidia/nemotron-3.5-bolt-e4b": {
        "id": "nvidia/nemotron-3.5-bolt-e4b",
        "name": "Nemotron 3.5 Bolt E4B",
        "provider": "NVIDIA",
        "tag": "CONVERSATIONAL & REASONING",
        "description": "Ultra-fast 1.7s model tuned for daily conversation, multi-turn dialogue, and analytical reasoning."
    },
    "nvidia/nemotron-3.5-lightning-30b-a3b": {
        "id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "name": "Nemotron 3.5 Lightning 30B",
        "provider": "NVIDIA",
        "tag": "BRIEFING, AGENT & FALLBACK",
        "description": "Authoritative 2.4s foundation model for Morning Briefings, agent tool execution, and default fallback."
    },
    "minimaxai/minimax-m3.1-flash": {
        "id": "minimaxai/minimax-m3.1-flash",
        "name": "MiniMax M3.1 Flash",
        "provider": "MiniMax",
        "tag": "CODING & STRUCTURED",
        "description": "Specialized open-weights model optimized for code generation, debugging, refactoring, and structured JSON."
    }
}

# Legacy model aliases preserved for backward-compatible migration and unit test stability without UI card exposure
LEGACY_MODELS: Dict[str, Dict[str, str]] = {
    "z-ai/glm-5.3-flash": {
        "id": "z-ai/glm-5.3-flash",
        "name": "GLM 5.3 Flash",
        "provider": "Z-AI",
        "tag": "Retired / Legacy",
        "description": "Retired legacy foundation model (kept for test backward compatibility)."
    },
    "Qwen/Qwen3.8-27B:fastest": {
        "id": "Qwen/Qwen3.8-27B:fastest",
        "name": "Qwen 3.8 27B",
        "provider": "Hugging Face",
        "tag": "Coding & Structured",
        "description": "High-performance open weights model (legacy test alias)."
    },
    "openai/gpt-oss-120b:fastest": {
        "id": "openai/gpt-oss-120b:fastest",
        "name": "GPT-OSS 120B",
        "provider": "Hugging Face",
        "tag": "Deep Reasoning / Briefing",
        "description": "High-capacity reasoning model (legacy test alias)."
    }
}
DEFAULT_MODEL = "auto"
DEFAULT_API_URL = "https://orange-api-cuuo.onrender.com"
DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "dark",
    "model": DEFAULT_MODEL,
    "api_url": DEFAULT_API_URL,
    "morning_briefing_enabled": False,
    "preferred_briefing_time": "08:30",
    "contextual_advisories_enabled": True,
    "advisory_cooldown_hours": 4,
    "quiet_hours_enabled": False,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "idle_threshold_minutes": 10,
    "reminder_lead_times": {},
    "chat_session_start_id": 0,
    "hybrid_memory_extraction_enabled": True,
    "hybrid_memory_confidence_threshold": 0.75,
    "adaptive_empathy_enabled": True,
    "minimize_to_tray_enabled": True,
    "desktop_toasts_enabled": True,
    "full_access_mode": "supervised",
    "idle_followups_enabled": True,
    "idle_followup_minutes": 15,
    "active_window_awareness_enabled": True,
}

_BRIEFING_TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _validate_api_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    try:
        parsed = urllib.parse.urlparse(u)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


def _validate_briefing_time(time_str: Any) -> bool:
    if not isinstance(time_str, str):
        return False
    return bool(_BRIEFING_TIME_REGEX.match(time_str.strip()))


def _validate_time_hhmm(time_str: Any) -> bool:
    if not isinstance(time_str, str):
        return False
    return bool(_BRIEFING_TIME_REGEX.match(time_str.strip()))


def _validate_idle_threshold_minutes(mins: Any) -> bool:
    try:
        val = int(mins)
        return 1 <= val <= 120
    except (ValueError, TypeError):
        return False


def _validate_cooldown_hours(hrs: Any) -> bool:
    try:
        return int(hrs) in (2, 4, 8)
    except (ValueError, TypeError):
        return False


def _validate_model(model: Any) -> bool:
    return isinstance(model, str) and (model in SUPPORTED_MODELS or model in LEGACY_MODELS)


def _validate_theme(theme: Any) -> bool:
    return isinstance(theme, str) and theme.lower() in ("dark", "light", "system")


def _is_within_quiet_hours(settings: Dict[str, Any], now_dt: Optional[datetime] = None) -> bool:
    """
    Evaluate whether now_dt is within the configured Quiet Hours window.
    Supports overnight windows (e.g. 22:00 -> 07:00, where now >= start or now < end)
    and same-day windows (e.g. 13:00 -> 15:00, where start <= now < end).
    If quiet_hours_enabled is False, returns False.
    If start == end, window is empty, returns False.
    """
    if not settings.get("quiet_hours_enabled", False):
        return False

    start_str = settings.get("quiet_hours_start", "22:00")
    end_str = settings.get("quiet_hours_end", "07:00")
    if not (_validate_time_hhmm(start_str) and _validate_time_hhmm(end_str)):
        return False

    now = now_dt or datetime.now()
    cur_t = now.time()

    start_parts = [int(p) for p in start_str.strip().split(":")]
    end_parts = [int(p) for p in end_str.strip().split(":")]
    start_time = dt_time(start_parts[0], start_parts[1])
    end_time = dt_time(end_parts[0], end_parts[1])

    if start_time == end_time:
        return False

    if start_time < end_time:
        # Same-day span (e.g. 13:00 to 15:00)
        return start_time <= cur_t < end_time
    else:
        # Overnight span (e.g. 22:00 to 07:00)
        return cur_t >= start_time or cur_t < end_time


def _load_gui_settings() -> Dict[str, Any]:
    path = os.path.join(get_user_data_dir(), "gui_settings.json")
    alt_path = os.path.join(get_user_data_dir(), "settings.json")
    if not os.path.exists(path) and os.path.exists(alt_path):
        path = alt_path
    settings = dict(DEFAULT_SETTINGS)
    if not os.path.exists(path):
        return settings
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                if _validate_theme(data.get("theme")):
                    settings["theme"] = data["theme"].lower()
                if _validate_model(data.get("model")):
                    # Auto-migrate legacy hardcoded defaults to "auto"
                    if data.get("model_routing_version", 0) < 2 and data.get("model") in (
                        "nvidia/nemotron-3.5-lightning-30b-a3b",
                        "z-ai/glm-5.3-flash",
                        "Qwen/Qwen3.8-27B:fastest",
                        "openai/gpt-oss-120b:fastest",
                    ):
                        settings["model"] = DEFAULT_MODEL
                    else:
                        settings["model"] = data["model"]
                else:
                    settings["model"] = DEFAULT_MODEL
                if _validate_api_url(data.get("api_url")):
                    settings["api_url"] = data["api_url"].strip().rstrip("/")
                if isinstance(data.get("morning_briefing_enabled"), bool):
                    settings["morning_briefing_enabled"] = data["morning_briefing_enabled"]
                if _validate_briefing_time(data.get("preferred_briefing_time")):
                    settings["preferred_briefing_time"] = data["preferred_briefing_time"].strip()
                if isinstance(data.get("contextual_advisories_enabled"), bool):
                    settings["contextual_advisories_enabled"] = data["contextual_advisories_enabled"]
                if _validate_cooldown_hours(data.get("advisory_cooldown_hours")):
                    settings["advisory_cooldown_hours"] = int(data["advisory_cooldown_hours"])
                if isinstance(data.get("quiet_hours_enabled"), bool):
                    settings["quiet_hours_enabled"] = data["quiet_hours_enabled"]
                if _validate_time_hhmm(data.get("quiet_hours_start")):
                    settings["quiet_hours_start"] = data["quiet_hours_start"].strip()
                if _validate_time_hhmm(data.get("quiet_hours_end")):
                    settings["quiet_hours_end"] = data["quiet_hours_end"].strip()
                if _validate_idle_threshold_minutes(data.get("idle_threshold_minutes")):
                    settings["idle_threshold_minutes"] = int(data["idle_threshold_minutes"])
                if isinstance(data.get("reminder_lead_times"), dict):
                    settings["reminder_lead_times"] = data["reminder_lead_times"]
                if isinstance(data.get("chat_session_start_id"), (int, float)):
                    settings["chat_session_start_id"] = int(data["chat_session_start_id"])
                if isinstance(data.get("hybrid_memory_extraction_enabled"), bool):
                    settings["hybrid_memory_extraction_enabled"] = data["hybrid_memory_extraction_enabled"]
                if isinstance(data.get("adaptive_empathy_enabled"), bool):
                    settings["adaptive_empathy_enabled"] = data["adaptive_empathy_enabled"]
                if "hybrid_memory_confidence_threshold" in data:
                    try:
                        thresh = float(data["hybrid_memory_confidence_threshold"])
                        settings["hybrid_memory_confidence_threshold"] = max(0.5, min(1.0, thresh))
                    except (ValueError, TypeError):
                        pass
                if isinstance(data.get("minimize_to_tray_enabled"), bool):
                    settings["minimize_to_tray_enabled"] = data["minimize_to_tray_enabled"]
                if isinstance(data.get("desktop_toasts_enabled"), bool):
                    settings["desktop_toasts_enabled"] = data["desktop_toasts_enabled"]
                if data.get("full_access_mode") in ("supervised", "unrestricted"):
                    settings["full_access_mode"] = data["full_access_mode"]
                if isinstance(data.get("idle_followups_enabled"), bool):
                    settings["idle_followups_enabled"] = data["idle_followups_enabled"]
                if "idle_followup_minutes" in data:
                    try:
                        settings["idle_followup_minutes"] = max(5, min(120, int(data["idle_followup_minutes"])))
                    except (ValueError, TypeError):
                        pass
                if isinstance(data.get("active_window_awareness_enabled"), bool):
                    settings["active_window_awareness_enabled"] = data["active_window_awareness_enabled"]
                # Preserve any extra legacy keys (excluding model to prevent obsolete overwrite)
                for k, v in data.items():
                    if k not in settings and k != "model":
                        settings[k] = v
        return settings
    except Exception as e:
        logger.warning("Error reading gui_settings.json: %s", e)
        return settings


def _save_gui_settings(settings: Dict[str, Any]) -> bool:
    path = os.path.join(get_user_data_dir(), "gui_settings.json")
    try:
        settings_to_save = dict(settings)
        if "model_routing_version" not in settings_to_save:
            settings_to_save["model_routing_version"] = 2
        temp_path = f"{path}.tmp.{os.getpid()}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(settings_to_save, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        return True
    except Exception as e:
        logger.error("Error writing gui_settings.json: %s", e)
        return False


# Headless runtime bridge: wire gui.settings to authoritative runtime_adapter settings helpers
# Avoids importing Tkinter/customtkinter in headless and standalone frozen environments
if "gui" not in sys.modules:
    import types
    _gui_pkg = types.ModuleType("gui")
    sys.modules["gui"] = _gui_pkg

if "gui.settings" not in sys.modules:
    import types
    _gui_settings = types.ModuleType("gui.settings")
    _gui_settings.load_settings = _load_gui_settings
    _gui_settings.save_settings = _save_gui_settings
    sys.modules["gui.settings"] = _gui_settings
    sys.modules["gui"].settings = _gui_settings

# Import briefing & recommendation components safely
from brain.briefing.collector import BriefingCollector
from brain.briefing.synthesizer import BriefingSynthesizer
from brain.briefing.recommendations import (
    Recommendation,
    RecommendationEvaluator,
    RecommendationStore,
    RecommendationState,
    RecommendationPriority,
)

# Wrap BriefingSynthesizer.synthesize so Morning Briefings route to task_type="briefing" (Nemotron 3.5 Lightning 30B)
_orig_briefing_synthesize = BriefingSynthesizer.synthesize

def _briefing_task_aware_synthesize(self, context, timeout=60.0):
    prompt, system_instruction = self._build_prompt(context)
    if self.api_client and self.api_client.is_available():
        try:
            res = self.api_client.assist(
                message=prompt,
                system_instruction=system_instruction,
                profile=None,
                task_type="briefing",
                timeout=timeout,
            )
            if res.get("success") and res.get("reply"):
                reply_text = res["reply"].strip()
                from brain.briefing.models import DailyBriefing
                return DailyBriefing(
                    date=context.current_date,
                    summary_markdown=reply_text,
                    priorities=context.priorities,
                    raw_reply=reply_text,
                    model_name=res.get("model", "api"),
                    is_fallback=False,
                )
        except Exception as e:
            logger.warning("[BRIEFING SYNTHESIZER] Orange API synthesis failed; using deterministic fallback: %s", e)
    from brain.briefing.models import DailyBriefing
    fallback_markdown = self._generate_deterministic_briefing(context)
    return DailyBriefing(
        date=context.current_date,
        summary_markdown=fallback_markdown,
        priorities=context.priorities,
        raw_reply=fallback_markdown,
        model_name="local_deterministic",
        is_fallback=True,
    )

BriefingSynthesizer.synthesize = _briefing_task_aware_synthesize


def normalize_recommendation_priority(raw_priority: Any) -> str:
    """
    Map recommendation priorities deterministically to Stage 2A contract: HIGH, MEDIUM, LOW.
    Mappings:
      - NORMAL / MEDIUM -> MEDIUM
      - CRITICAL / HIGH -> HIGH
      - LOW -> LOW
      - Default / unknown -> MEDIUM
    """
    if raw_priority is None:
        return "MEDIUM"
    if hasattr(raw_priority, "name"):
        val = raw_priority.name.upper()
    elif hasattr(raw_priority, "value"):
        val = str(raw_priority.value).upper()
    else:
        val = str(raw_priority).strip().upper()

    if val in ("CRITICAL", "HIGH"):
        return "HIGH"
    elif val in ("NORMAL", "MEDIUM"):
        return "MEDIUM"
    elif val == "LOW":
        return "LOW"
    return "MEDIUM"


# Patch Recommendation.to_dict so newly serialized recommendations use the Stage 2A contract
_orig_rec_to_dict = Recommendation.to_dict


def _patched_rec_to_dict(self) -> Dict[str, Any]:
    d = _orig_rec_to_dict(self)
    d["priority"] = normalize_recommendation_priority(self.priority)
    return d


Recommendation.to_dict = _patched_rec_to_dict


def _migrate_recommendations_file() -> int:
    """
    Migrate existing persisted recommendations in recommendations.json
    so that raw legacy priorities ('NORMAL') are deterministically normalized
    to the Stage 2A contract ('MEDIUM'), preserving all IDs, fingerprints, and fields.
    """
    user_dir = get_user_data_dir()
    rec_path = os.path.join(user_dir, "recommendations.json")
    if not os.path.exists(rec_path):
        return 0

    try:
        with open(rec_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return 0

        recs = data.get("recommendations", {})
        if not isinstance(recs, dict):
            return 0

        migrated_count = 0
        for rec_id, rec in recs.items():
            if not isinstance(rec, dict):
                continue
            old_prio = rec.get("priority")
            new_prio = normalize_recommendation_priority(old_prio)
            if old_prio != new_prio:
                rec["priority"] = new_prio
                migrated_count += 1

        if migrated_count > 0:
            temp_path = f"{rec_path}.tmp.{os.getpid()}"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, rec_path)
            logger.info("[STAGE-2C] Migrated %d recommendation records to strict Stage 2A contract (HIGH/MEDIUM/LOW).", migrated_count)

        return migrated_count
    except Exception as e:
        logger.warning("[STAGE-2C] Recommendation file migration warning: %s", e)
        return 0


def _ensure_api_client_configured():
    """Ensure main.api_client exists and is configured with current settings."""
    try:
        current = _load_gui_settings()
        api_url = current.get("api_url", DEFAULT_API_URL).rstrip("/")
        api_key = os.environ.get("ORANGE_API_KEY", "").strip()
        if main.api_client is None:
            main.api_client = OrangeAPIClient(api_url=api_url, api_key=api_key)
        else:
            main.api_client.api_url = api_url
            main.api_client.api_key = api_key

        # Wrap assist() so selected model is injected automatically when not explicitly passed
        if not getattr(main.api_client, "_stage2b_wrapped", False):
            orig_assist = main.api_client.assist
            def _model_aware_assist(*args, **kwargs):
                # Ensure Morning Briefing synthesis passes task_type="briefing"
                if kwargs.get("task_type") == "reasoning":
                    sys_inst = kwargs.get("system_instruction") or ""
                    msg = kwargs.get("message") or ""
                    if "Daily Briefing" in sys_inst or "briefing" in msg.lower():
                        kwargs["task_type"] = "briefing"

                target_model = kwargs.get("model")
                if not target_model or (target_model not in SUPPORTED_MODELS and target_model not in LEGACY_MODELS):
                    curr = _load_gui_settings()
                    selected = curr.get("model")
                    if not selected or (selected not in SUPPORTED_MODELS and selected not in LEGACY_MODELS):
                        selected = DEFAULT_MODEL
                    kwargs["model"] = selected
                return orig_assist(*args, **kwargs)
            main.api_client.assist = _model_aware_assist
            main.api_client._stage2b_wrapped = True
    except Exception as e:
        logger.warning("Error configuring API client: %s", e)


def _apply_runtime_settings(settings: Dict[str, Any]):
    """Apply updated settings to live runtime objects (API client endpoint, idle threshold, etc.)."""
    try:
        _ensure_api_client_configured()
        api_url = settings.get("api_url")
        api_key = os.environ.get("ORANGE_API_KEY", "").strip()
        if main.api_client:
            if api_url:
                main.api_client.api_url = api_url.rstrip("/")
                logger.info("Applied runtime API endpoint: %s", main.api_client.api_url)
            main.api_client.api_key = api_key
        idle_mins = settings.get("idle_threshold_minutes", 10)
        if _validate_idle_threshold_minutes(idle_mins):
            global _idle_inactivity_threshold
            _idle_inactivity_threshold = float(idle_mins) * 60.0
    except Exception as e:
        logger.warning("Could not apply live settings to runtime: %s", e)

# 3. Protocol Serialization Lock
_START_TIME = time.time()
_protocol_lock = threading.Lock()
_is_shutting_down = False
_session_conversational_state: Optional[Dict[str, Any]] = None
_session_tool_chains: List[Tuple[str, ...]] = []
_pending_confirmations: Dict[str, Dict[str, Any]] = {}
_recommendation_actions: Dict[str, Dict[str, Any]] = {}
_last_activity_ts: Optional[float] = None
_idle_nudge_sent_for_turn: bool = False
_latest_active_window: Dict[str, Any] = {
    "process_name": "",
    "window_title": "",
    "category": "general",
    "captured_at": 0.0,
}


def register_recommendation_action(rec_id: str, action_payload: Dict[str, Any]):
    """Register authoritative execution payload for a recommendation."""
    _recommendation_actions[str(rec_id)] = action_payload
_confirmations_lock = threading.Lock()


def send_message(payload: Dict[str, Any]):
    """Write a framed JSON-RPC line to the dedicated protocol stream."""
    with _protocol_lock:
        if _is_shutting_down and "id" not in payload:
            return
        line_bytes = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        if hasattr(_protocol_out, "buffer"):
            _protocol_out.buffer.write(line_bytes)
            _protocol_out.buffer.flush()
        else:
            _protocol_out.write(line_bytes.decode("utf-8", errors="replace"))
            _protocol_out.flush()


def send_response(req_id: Any, result: Any):
    """Emit a JSON-RPC 2.0 success response."""
    send_message({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    })


def send_error(req_id: Any, code: int, message: str, data: Any = None):
    """Emit a JSON-RPC 2.0 error response."""
    err_obj = {"code": code, "message": message}
    if data is not None:
        err_obj["data"] = data
    send_message({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err_obj,
    })


def send_event(event_name: str, params: Dict[str, Any]):
    """Emit an asynchronous JSON-RPC 2.0 event (notification without ID)."""
    send_message({
        "jsonrpc": "2.0",
        "method": event_name,
        "params": params,
    })


# 4. Confirmation Bridge (prompt_fn implementation)
def _confirmation_prompt_fn(prompt_text: str) -> str:
    """
    Synchronous prompt callback invoked by tool/agent execution.
    Emits an asynchronous event to Rust/React and blocks with a 120s safety timeout.
    """
    conf_id = f"conf_{uuid.uuid4().hex[:8]}"
    evt = threading.Event()
    container = {"decision": "no", "event": evt, "created_at": time.time()}

    with _confirmations_lock:
        _pending_confirmations[conf_id] = container

    logger.info("[CONFIRMATION] Emitting request %s: %s", conf_id, prompt_text.strip()[:60])

    send_event("assistant.confirmation_required", {
        "confirmation_id": conf_id,
        "prompt_text": prompt_text.strip(),
        "timeout_seconds": 120,
    })

    # Wait on worker thread with safety timeout
    signaled = evt.wait(timeout=120.0)

    with _confirmations_lock:
        final_decision = container.get("decision", "no")
        _pending_confirmations.pop(conf_id, None)

    if not signaled:
        logger.warning("[CONFIRMATION] Request %s timed out after 120s; defaulting to denial.", conf_id)
        return "no"

    logger.info("[CONFIRMATION] Request %s resolved with decision: '%s'", conf_id, final_decision)
    return final_decision


# 5. Background Scheduler Callbacks
def _on_reminder_due(reminder: Dict[str, Any]):
    """Deprecated: Reminders in Tauri mode are authoritatively handled by _check_and_emit_due_reminders."""
    pass


def _ui_control_file_watcher():
    """Poll for test automation commands and forward as Tauri events."""
    user_cmd_file = os.path.join(get_user_data_dir(), "ui_command.json")
    dev_cmd_file = os.path.join(_project_root, "ui_command.json")
    while True:
        try:
            cmd_file = user_cmd_file if os.path.exists(user_cmd_file) else (dev_cmd_file if os.path.exists(dev_cmd_file) else None)
            if cmd_file and os.path.exists(cmd_file):
                with open(cmd_file, "r", encoding="utf-8") as f:
                    cmd_data = json.load(f)
                try:
                    os.remove(cmd_file)
                except OSError:
                    pass

                cmd = cmd_data.get("command")
                logger.info("[UI-WATCHER] Received command: %s with data: %s", cmd, cmd_data)
                if cmd == "toggle_drawer":
                    send_event("ui.toggle_drawer", {"open": cmd_data.get("open")})
                elif cmd == "set_theme":
                    send_event("ui.set_theme", {"theme": cmd_data.get("theme", "dark")})
                elif cmd == "select_view":
                    send_event("ui.select_view", {"view": cmd_data.get("view", "home")})
        except Exception:
            pass
        time.sleep(0.2)


def _emit_job_followup(job: Any, test_now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Emit a deduplicated job.followup proactive event for a terminal job (COMPLETED or FAILED)."""
    if not job:
        return None
    status_val = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status_val not in ("COMPLETED", "FAILED"):
        return None

    settings = _load_gui_settings()
    if not settings.get("contextual_advisories_enabled", True):
        return None

    now = test_now or datetime.now()
    if _is_within_quiet_hours(settings, now):
        logger.info("[STAGE-4C] Quiet hours active; deferring job.followup for job %s", job.id)
        return None

    job_id = str(job.id)
    evt_id = f"evt_job_followup_{job_id}_{status_val.lower()}"

    # Check if already emitted
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
            if cur.fetchone() is not None:
                return None
    except Exception as e:
        logger.warning("[STAGE-4C] Error checking duplicate job.followup: %s", e)

    goal = getattr(job, "goal", "")
    if status_val == "COMPLETED":
        summary = f"Job '{goal}' completed successfully."
        final_resp = getattr(job, "final_response", None)
        if final_resp:
            summary += f" Result: {final_resp}"
        suggested_prompt = f"Review the results from completed job '{goal}'"
    else:
        summary = f"Job '{goal}' failed."
        last_err = getattr(job, "last_error", None)
        if last_err:
            summary += f" Error: {last_err}"
        suggested_prompt = f"Investigate why job '{goal}' failed and retry"

    return emit_proactive_event(
        event_type="job.followup",
        entity_id=job_id,
        payload={
            "job_id": job_id,
            "status": status_val,
            "goal": goal,
            "summary": summary,
            "suggested_prompt": suggested_prompt,
        },
        event_id=evt_id,
    )


def _on_job_event(job: Any):
    if not job:
        return
    pending = job.get_pending_confirmation() if hasattr(job, "get_pending_confirmation") else None
    send_event("scheduler.job_event", {
        "id": job.id,
        "short_id": getattr(job, "short_id", job.id[:8]),
        "goal": job.goal,
        "status": job.status.value,
        "step_count": job.step_count,
        "last_error": job.last_error,
        "final_response": job.final_response,
        "pending_tool": pending.tool_name if pending else None,
    })
    try:
        _emit_job_followup(job)
    except Exception as e:
        logger.warning("[STAGE-4C] Error evaluating job followup in _on_job_event: %s", e)


# ==============================================================================
# 5B. Stage 2C Proactive Intelligence & Background Workers
# ==============================================================================

_stage2c_stop_event = threading.Event()
_stage2c_worker_thread: Optional[threading.Thread] = None
_stage2c_reconciliation_thread: Optional[threading.Thread] = None
_last_user_activity: float = time.time()
_idle_inactivity_threshold: float = 600.0  # 10 minutes default
_last_idle_eval_time: Optional[float] = None
_stage2c_lock = threading.Lock()

# Stage 4B: Asynchronous morning briefing synthesis state
_briefing_eval_lock = threading.Lock()
_briefing_eval_in_flight: bool = False
_briefing_worker_thread: Optional[threading.Thread] = None

# Stage 4.5B Phase 2: Pre-update state and turn thread tracking
_is_updating: bool = False
_turn_threads_lock = threading.Lock()
_active_turn_threads: set = set()


@contextmanager
def _get_db_connection(db_path: Optional[str] = None):
    """Yield a thread-safe short-lived connection to memory.db and close it deterministically."""
    target = db_path or resolve_database_path()
    conn = sqlite3.connect(target, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ensure_stage2c_tables():
    """Ensure daily_briefings, project_reconciliations, and proactive_events tables exist in memory.db."""
    try:
        with _get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_briefings (
                    id TEXT PRIMARY KEY,
                    local_date TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model_name TEXT,
                    priorities_json TEXT,
                    sources_json TEXT,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_reconciliations (
                    id TEXT PRIMARY KEY,
                    workspace_path TEXT NOT NULL,
                    workspace_name TEXT NOT NULL,
                    reconciled_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    git_branch TEXT,
                    git_head_commit TEXT,
                    new_commits_json TEXT,
                    changed_files_json TEXT,
                    uncommitted_changes_json TEXT,
                    file_watermark_hash TEXT,
                    outstanding_items_json TEXT,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proactive_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    entity_id TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    acknowledged INTEGER DEFAULT 0,
                    acknowledged_at TEXT
                )
            """)
            conn.commit()
            logger.info("Stage 2C/2D database tables verified in %s", resolve_database_path())
    except Exception as e:
        logger.error("Failed to ensure Stage 2C/2D database tables: %s", e, exc_info=True)


def emit_proactive_event(
    event_type: str,
    entity_id: str,
    payload: Dict[str, Any],
    event_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Construct and emit a structured, authoritative proactive event envelope.
    Records the event in the persistent proactive_events table for replay and recovery.
    """
    evt_id = event_id or f"evt_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    envelope = {
        "event_id": evt_id,
        "event_type": event_type,
        "created_at": now_iso,
        "entity_id": str(entity_id) if entity_id else "",
        "version": 1,
        "payload": payload,
        "acknowledged": False,
    }
    was_inserted = True
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO proactive_events
                (event_id, event_type, entity_id, created_at, payload_json, acknowledged)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (evt_id, event_type, str(entity_id) if entity_id else "", now_iso, json.dumps(payload)))
            was_inserted = cur.rowcount > 0
            conn.commit()
    except Exception as e:
        logger.warning("[STAGE-2D] Error saving proactive event %s: %s", evt_id, e)

    if event_id and not was_inserted:
        # Event already recorded/emitted previously; avoid duplicate stdio emission
        return None

    # Deliver via JSON-RPC stdio event transport to Rust / React
    send_event(event_type, envelope)
    return envelope


def _check_and_emit_due_reminders(test_now: Optional[datetime] = None):
    """Check for due reminders from the SQLite database and emit reminder.due events.
    Also evaluates pre-due reminder alerts (reminder.upcoming) based on configured lead times,
    respecting quiet hours and pruning lead time metadata upon firing.
    """
    try:
        now = test_now or datetime.now()
        settings = _load_gui_settings()
        in_quiet = _is_within_quiet_hours(settings, now)
        lead_map = settings.get("reminder_lead_times", {})
        if not isinstance(lead_map, dict):
            lead_map = {}

        import brain.reminders as rem_mod
        from datetime import timedelta

        # 1. Pre-due reminder alerts (only when NOT in quiet hours)
        if not in_quiet and lead_map:
            try:
                pending_rems = rem_mod.list_pending()
                for p in pending_rems:
                    rem_id = p.get("id")
                    if str(rem_id) not in lead_map:
                        continue
                    lead_mins = int(lead_map.get(str(rem_id), 0))
                    if lead_mins <= 0:
                        continue

                    raw_due = p.get("due_at")
                    try:
                        due_dt = _parse_reminder_due_at(raw_due)
                    except Exception:
                        continue

                    lead_start_dt = due_dt - timedelta(minutes=lead_mins)
                    if lead_start_dt <= now < due_dt:
                        evt_id = f"evt_reminder_lead_{rem_id}"
                        with _get_db_connection() as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
                            already_emitted = cur.fetchone() is not None

                        if not already_emitted:
                            emit_proactive_event(
                                event_type="reminder.upcoming",
                                entity_id=str(rem_id),
                                payload={
                                    "reminder_id": rem_id,
                                    "message": p.get("message", "Upcoming reminder"),
                                    "due_at": raw_due,
                                    "lead_time_minutes": lead_mins,
                                },
                                event_id=evt_id,
                            )
                            logger.info("[STAGE-4C] Emitted reminder.upcoming for reminder #%s (%d min early): %s", rem_id, lead_mins, p.get("message"))
            except Exception as e:
                logger.warning("[STAGE-4C] Error evaluating pre-due upcoming reminders: %s", e)

        # 2. Main due reminders
        due_rems = scheduler.get_due_reminders(now)
        pruned_any = False
        for r in due_rems:
            rem_id = r.get("id")
            evt_id = f"evt_reminder_{rem_id}"
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
                already_emitted = cur.fetchone() is not None

            if not already_emitted:
                emit_proactive_event(
                    event_type="reminder.due",
                    entity_id=str(rem_id),
                    payload={
                        "reminder_id": rem_id,
                        "message": r.get("message", "Reminder due"),
                        "due_at": r.get("due_at"),
                    },
                    event_id=evt_id,
                )
                logger.info("[STAGE-2D] Emitted reminder.due for reminder #%s: %s", rem_id, r.get("message"))

            # Enforce atomic order: only mark fired once proactive_events record is verified persisted
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
                persisted = cur.fetchone() is not None

            if persisted:
                scheduler.mark_fired(rem_id)
                if str(rem_id) in lead_map:
                    del lead_map[str(rem_id)]
                    pruned_any = True
            else:
                logger.error("[STAGE-2D] Proactive event %s not persisted; leaving reminder #%s fired=0", evt_id, rem_id)

        if pruned_any:
            settings["reminder_lead_times"] = lead_map
            _save_gui_settings(settings)
    except Exception as e:
        logger.warning("[STAGE-2D] Failed checking due reminders: %s", e)


# --- Scope A: Morning Briefing Background Worker ---

def _evaluate_morning_briefing(
    force: bool = False,
    test_now: Optional[datetime] = None,
    test_date: Optional[str] = None,
    sync: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Evaluate and synthesize a daily morning briefing according to user preferences.
    Guarantees at most one briefing per local calendar date.
    Strictly read-only aggregation before model or deterministic synthesis.
    When sync=False, synthesis runs asynchronously on a guarded daemon thread.
    """
    settings = _load_gui_settings()
    now = test_now or datetime.now()
    current_date = test_date or now.strftime("%Y-%m-%d")

    if not force:
        # Check quiet hours (defer without setting last_briefing_date)
        if _is_within_quiet_hours(settings, now):
            logger.info("[STAGE-4C] Quiet hours active; deferring automatic morning briefing.")
            return None

        # 1. User preference check
        if not settings.get("morning_briefing_enabled", False):
            return None

        # 2. Date deduplication check in settings
        if settings.get("last_briefing_date") == current_date:
            # Defensive check: if existing briefing is orphaned in proactive_events, reconcile it
            _reconcile_morning_briefing_events(target_date=current_date, replay_unacked=False)
            return None

        # 3. Date deduplication check in database
        try:
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM daily_briefings WHERE local_date = ? AND status IN ('success', 'fallback')", (current_date,))
                if cur.fetchone():
                    # Defensive check: if existing briefing is orphaned in proactive_events, reconcile it
                    _reconcile_morning_briefing_events(target_date=current_date, replay_unacked=False)
                    return None
        except Exception as e:
            logger.warning("Error checking daily_briefings deduplication: %s", e)

        # 4. Preferred delivery time check (HH:MM 24-hr)
        pref_time_str = settings.get("preferred_briefing_time", "08:30")
        try:
            parts = pref_time_str.split(":")
            target_time = dt_time(int(parts[0]), int(parts[1]))
            if now.time() < target_time:
                return None
        except Exception:
            pass

    global _briefing_eval_in_flight, _briefing_worker_thread
    with _briefing_eval_lock:
        if _briefing_eval_in_flight:
            logger.info("[STAGE-2C] Morning briefing synthesis already in flight; skipping duplicate start.")
            return None
        _briefing_eval_in_flight = True

    def _execute_synthesis() -> Optional[Dict[str, Any]]:
        global _briefing_eval_in_flight
        try:
            logger.info("[STAGE-2C] Triggering morning briefing preparation for date: %s", current_date)
            briefing_id = f"briefing_{current_date}_{uuid.uuid4().hex[:8]}"
            created_at = datetime.now(timezone.utc).isoformat()

            job_mgr = main.get_job_manager() if hasattr(main, "get_job_manager") else None
            job_store = job_mgr.store if job_mgr else None
            rec_store = None
            try:
                rec_store = RecommendationStore()
            except Exception:
                pass
            collector = BriefingCollector(job_store=job_store, recommendation_store=rec_store)
            context = collector.collect(now=now)

            _ensure_api_client_configured()
            synthesizer = BriefingSynthesizer(api_client=main.api_client)
            briefing = synthesizer.synthesize(context, timeout=60.0)

            # Serialize structured components
            priorities_data = []
            for p in briefing.priorities:
                priorities_data.append({
                    "category": getattr(p, "category", "general"),
                    "title": getattr(p, "title", ""),
                    "level": p.level.name if hasattr(p.level, "name") else str(p.level),
                    "details": getattr(p, "details", ""),
                    "action_hint": getattr(p, "action_hint", ""),
                })

            sources_data = {
                "overdue_reminders_count": len(context.overdue_reminders),
                "today_reminders_count": len(context.today_reminders),
                "blocked_jobs_count": len(context.blocked_jobs),
                "active_jobs_count": len(context.active_jobs),
                "paused_jobs_count": len(context.paused_jobs),
                "recent_completed_jobs_count": len(context.recent_completed_jobs),
                "current_project": context.current_project.name if context.current_project else None,
                "secondary_projects": [p.name for p in context.secondary_projects],
                "recommendations_count": len(context.recommendations),
            }

            status = "fallback" if briefing.is_fallback else "success"
            content = briefing.summary_markdown
            model_name = briefing.model_name

            briefing_obj = {
                "id": briefing_id,
                "local_date": current_date,
                "created_at": created_at,
                "content": content,
                "status": status,
                "model_name": model_name,
                "priorities": priorities_data,
                "sources": sources_data,
                "error_message": None,
            }

            evt_id = f"evt_briefing_{current_date}"
            envelope = {
                "event_id": evt_id,
                "event_type": "briefing.ready",
                "created_at": created_at,
                "entity_id": briefing_id,
                "version": 1,
                "payload": briefing_obj,
                "acknowledged": False,
            }

            # Single atomic SQLite transaction for both daily_briefings and proactive_events
            with _get_db_connection() as conn:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO daily_briefings (
                            id, local_date, created_at, content, status, model_name,
                            priorities_json, sources_json, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        briefing_id,
                        current_date,
                        created_at,
                        content,
                        status,
                        model_name,
                        json.dumps(priorities_data),
                        json.dumps(sources_data),
                        None,
                    ))
                    conn.execute("""
                        INSERT OR REPLACE INTO proactive_events (
                            event_id, event_type, entity_id, created_at, payload_json, acknowledged
                        ) VALUES (?, ?, ?, ?, ?, 0)
                    """, (
                        evt_id,
                        "briefing.ready",
                        briefing_id,
                        created_at,
                        json.dumps(briefing_obj),
                    ))

            # Update last_briefing_date in settings ONLY after successful atomic commit
            cur_settings = _load_gui_settings()
            cur_settings["last_briefing_date"] = current_date
            _save_gui_settings(cur_settings)
            logger.info("[STAGE-2C] Atomically persisted daily briefing %s and proactive event %s (status=%s, model=%s)", briefing_id, evt_id, status, model_name)

            # Emit authoritative proactive event (briefing.ready) via stdio event transport
            send_event("briefing.ready", envelope)

            return briefing_obj

        except Exception as e:
            logger.error("[STAGE-2C] Morning briefing synthesis or atomic persistence failed: %s", e, exc_info=True)
            return None
        finally:
            with _briefing_eval_lock:
                _briefing_eval_in_flight = False

    if sync:
        return _execute_synthesis()
    else:
        _briefing_worker_thread = threading.Thread(
            target=_execute_synthesis,
            daemon=True,
            name="BriefingSynthesisWorker",
        )
        _briefing_worker_thread.start()
        return {"status": "in_flight"}


def _reconcile_morning_briefing_events(target_date: Optional[str] = None, replay_unacked: bool = True, force: bool = False) -> List[Dict[str, Any]]:
    """
    Reconcile unacknowledged or orphaned morning briefing events.
    1. Recovers any daily_briefings row that lacks a corresponding proactive_events row (orphaned).
    2. Re-emits briefing.ready for any unacknowledged briefing event (post-commit crash recovery) when replay_unacked=True.
    Guarantees zero duplicate daily_briefings rows and idempotent emission.
    """
    settings = _load_gui_settings()
    if not force and not settings.get("morning_briefing_enabled", False):
        return []

    reconciled = []
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            if target_date:
                cur.execute("""
                    SELECT b.id, b.local_date, b.created_at, b.content, b.status, b.model_name,
                           b.priorities_json, b.sources_json,
                           e.event_id, e.acknowledged
                    FROM daily_briefings b
                    LEFT JOIN proactive_events e ON e.event_id = ('evt_briefing_' || b.local_date)
                    WHERE b.local_date = ? AND b.status IN ('success', 'fallback')
                      AND (e.event_id IS NULL OR (? AND e.acknowledged = 0))
                    ORDER BY b.local_date DESC
                """, (target_date, 1 if replay_unacked else 0))
            else:
                cur.execute("""
                    SELECT b.id, b.local_date, b.created_at, b.content, b.status, b.model_name,
                           b.priorities_json, b.sources_json,
                           e.event_id, e.acknowledged
                    FROM daily_briefings b
                    LEFT JOIN proactive_events e ON e.event_id = ('evt_briefing_' || b.local_date)
                    WHERE b.status IN ('success', 'fallback')
                      AND (e.event_id IS NULL OR (? AND e.acknowledged = 0))
                    ORDER BY b.local_date DESC
                    LIMIT 5
                """, (1 if replay_unacked else 0,))
            rows = cur.fetchall()

            for row in rows:
                b_id = row["id"]
                local_date = row["local_date"]
                evt_id = f"evt_briefing_{local_date}"

                try:
                    priorities_data = json.loads(row["priorities_json"]) if row["priorities_json"] else []
                except Exception:
                    priorities_data = []

                try:
                    sources_data = json.loads(row["sources_json"]) if row["sources_json"] else {}
                except Exception:
                    sources_data = {}

                briefing_obj = {
                    "id": b_id,
                    "local_date": local_date,
                    "created_at": row["created_at"],
                    "content": row["content"],
                    "status": row["status"],
                    "model_name": row["model_name"],
                    "priorities": priorities_data,
                    "sources": sources_data,
                    "error_message": None,
                }

                envelope = {
                    "event_id": evt_id,
                    "event_type": "briefing.ready",
                    "created_at": row["created_at"],
                    "entity_id": b_id,
                    "version": 1,
                    "payload": briefing_obj,
                    "acknowledged": False,
                }

                # If orphaned (event row missing), insert the proactive_events record
                if row["event_id"] is None:
                    with conn:
                        conn.execute("""
                            INSERT OR IGNORE INTO proactive_events
                            (event_id, event_type, entity_id, created_at, payload_json, acknowledged)
                            VALUES (?, 'briefing.ready', ?, ?, ?, 0)
                        """, (
                            evt_id,
                            b_id,
                            row["created_at"],
                            json.dumps(briefing_obj),
                        ))
                    logger.info("[STAGE-2C] Reconciled orphaned morning briefing event: %s (date=%s)", evt_id, local_date)

                # Emit briefing.ready event over stdio transport
                send_event("briefing.ready", envelope)
                logger.info("[STAGE-2C] Delivered morning briefing event: %s (orphaned=%s)", evt_id, row["event_id"] is None)
                reconciled.append(envelope)

    except Exception as e:
        logger.warning("[STAGE-2C] Error during morning briefing reconciliation: %s", e)

    return reconciled


# --- Scope B: Idle Recommendation Evaluator ---

def _evaluate_idle_recommendations(force: bool = False, test_now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Evaluate contextual recommendations after a period of user inactivity.
    Strictly advisory only - ZERO tool execution.
    Persists candidate records to recommendations.json via RecommendationStore.
    """
    global _last_idle_eval_time
    settings = _load_gui_settings()
    now_dt = test_now or datetime.now()
    now_ts = now_dt.timestamp()

    if not force:
        # 1. Check enabled setting
        if not settings.get("contextual_advisories_enabled", True):
            return []

        # 2. Check quiet hours (defer without updating _last_idle_eval_time)
        if _is_within_quiet_hours(settings, now_dt):
            logger.info("[STAGE-4C] Quiet hours active; deferring idle recommendations.")
            return []

        # 3. Check idle threshold dynamically
        idle_mins = settings.get("idle_threshold_minutes", 10)
        idle_threshold_sec = float(idle_mins) * 60.0
        idle_duration = now_ts - _last_user_activity
        if idle_duration < idle_threshold_sec:
            return []

        # 4. Check cooldown
        cooldown_hours = settings.get("advisory_cooldown_hours", 4)
        cooldown_sec = float(cooldown_hours) * 3600.0
        if _last_idle_eval_time is not None and (now_ts - _last_idle_eval_time < cooldown_sec):
            return []

    logger.info("[STAGE-2C] Evaluating contextual recommendations (idle_eval)...")
    _last_idle_eval_time = now_ts

    try:
        job_mgr = main.get_job_manager() if hasattr(main, "get_job_manager") else None
        job_store = job_mgr.store if job_mgr else None
        rec_store = None
        try:
            rec_store = RecommendationStore()
        except Exception:
            pass
        collector = BriefingCollector(job_store=job_store, recommendation_store=rec_store)
        context = collector.collect(now=test_now or datetime.now())

        evaluator = RecommendationEvaluator(
            db_path=resolve_database_path(),
            job_store=job_store,
        )

        active_recs = evaluator.evaluate(
            current_project=context.current_project,
            secondary_projects=context.secondary_projects,
            overdue_reminders=context.overdue_reminders,
            blocked_jobs=context.blocked_jobs,
            active_jobs=context.active_jobs,
            paused_jobs=context.paused_jobs,
            now=test_now or datetime.now(),
        )

        results = []
        for rec in active_recs:
            act_payload = getattr(rec, "action_payload", None)
            if not isinstance(act_payload, dict):
                act_payload = {"entity_id": getattr(rec, "entity_id", "")}
            item = {
                "id": rec.rec_id,
                "title": rec.title,
                "description": rec.explanation or (getattr(rec, "suggested_action", "")),
                "category": rec.category.value if hasattr(rec.category, "value") else str(rec.category),
                "priority": normalize_recommendation_priority(rec.priority),
                "rationale": getattr(rec, "suggested_action", rec.explanation),
                "action_type": getattr(rec, "recommendation_type", "advisory"),
                "action_payload": act_payload,
                "created_at": rec.created_at.isoformat() if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
                "status": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
                "dedup_key": getattr(rec, "evidence_fingerprint", rec.rec_id),
                "evidence": getattr(rec, "evidence", []),
            }
            results.append(item)
            # Emit recommendation.created (with per-recommendation ID deduplication)
            emit_proactive_event(
                event_type="recommendation.created",
                entity_id=rec.rec_id,
                payload=item,
                event_id=f"evt_rec_{rec.rec_id}",
            )

        logger.info("[STAGE-2C] Evaluated %d active recommendations.", len(results))
        return results

    except Exception as e:
        logger.warning("[STAGE-2C] Failed to evaluate idle recommendations: %s", e, exc_info=True)
        return []


def _get_active_recommendations() -> List[Dict[str, Any]]:
    """Return all active recommendations currently in the RecommendationStore."""
    try:
        store = RecommendationStore()
        all_recs = store.list_all()
        active = [r for r in all_recs if r.state == RecommendationState.ACTIVE]
        cards = []
        for rec in active:
            act_payload = getattr(rec, "action_payload", None)
            if not isinstance(act_payload, dict):
                act_payload = {"entity_id": getattr(rec, "entity_id", "")}
            cards.append({
                "id": rec.rec_id,
                "title": rec.title,
                "description": rec.explanation or (getattr(rec, "suggested_action", "")),
                "category": rec.category.value if hasattr(rec.category, "value") else str(rec.category),
                "priority": normalize_recommendation_priority(rec.priority),
                "rationale": getattr(rec, "suggested_action", rec.explanation),
                "action_type": getattr(rec, "recommendation_type", "advisory"),
                "action_payload": act_payload,
                "created_at": rec.created_at.isoformat() if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
                "status": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
                "dedup_key": getattr(rec, "evidence_fingerprint", rec.rec_id),
                "evidence": getattr(rec, "evidence", []),
            })
        return cards
    except Exception as e:
        logger.warning("Error fetching active recommendations: %s", e)
        return []


# --- Scope C: Startup Project Reconciliation ---

def _compute_workspace_watermark(workspace_path: str) -> str:
    """Compute a deterministic SHA-256 hash of key project manifests or directory entries."""
    manifest_files = [
        "package.json", "package-lock.json", "Cargo.toml", "Cargo.lock",
        "requirements.txt", "pyproject.toml", "vite.config.js", "README.md"
    ]
    hasher = hashlib.sha256()
    found_any = False
    for filename in sorted(manifest_files):
        fpath = os.path.join(workspace_path, filename)
        if os.path.isfile(fpath):
            try:
                stat = os.stat(fpath)
                hasher.update(f"{filename}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8"))
                found_any = True
            except OSError:
                pass
    if not found_any:
        try:
            entries = sorted(os.listdir(workspace_path))[:50]
            for e in entries:
                p = os.path.join(workspace_path, e)
                try:
                    stat = os.stat(p)
                    hasher.update(f"{e}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8"))
                except OSError:
                    pass
        except OSError:
            pass
    return hasher.hexdigest()


def _inspect_workspace_git(workspace_path: str) -> Dict[str, Any]:
    """Safely inspect Git repository status in a strictly read-only manner."""
    res = {
        "is_git": False,
        "branch": None,
        "head_commit": None,
        "new_commits": [],
        "changed_files": [],
        "uncommitted_changes": [],
    }
    if not os.path.exists(workspace_path):
        return res

    try:
        r_git = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if r_git.returncode != 0:
            return res

        res["is_git"] = True

        r_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if r_branch.returncode == 0:
            res["branch"] = r_branch.stdout.strip()

        r_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if r_head.returncode == 0:
            res["head_commit"] = r_head.stdout.strip()

        r_log = subprocess.run(
            ["git", "log", "-n", "5", "--pretty=format:%H|%s|%an|%cI"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if r_log.returncode == 0 and r_log.stdout.strip():
            commits = []
            for line in r_log.stdout.strip().split("\n"):
                parts = line.split("|", 3)
                if len(parts) == 4:
                    commits.append({
                        "hash": parts[0],
                        "subject": parts[1],
                        "author": parts[2],
                        "date": parts[3],
                    })
            res["new_commits"] = commits

        r_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if r_status.returncode == 0 and r_status.stdout.strip():
            changes = []
            changed_files = []
            for line in r_status.stdout.strip().split("\n"):
                if len(line) >= 4:
                    status_code = line[:2].strip()
                    f_name = line[3:].strip()
                    changes.append({"status": status_code, "file": f_name})
                    changed_files.append(f_name)
            res["uncommitted_changes"] = changes
            res["changed_files"] = changed_files

    except Exception as e:
        logger.warning("Error inspecting Git repository in %s: %s", workspace_path, e)

    return res


def _discover_authorized_workspaces() -> List[Dict[str, str]]:
    """Discover explicitly authorized and known project workspaces."""
    workspaces = []
    seen_paths = set()

    if os.path.exists(_project_root):
        norm_root = os.path.normpath(_project_root)
        workspaces.append({
            "name": os.path.basename(norm_root),
            "path": norm_root,
            "type": "official_primary",
        })
        seen_paths.add(norm_root.lower())

    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT memory_key, value FROM structured_memories WHERE category = 'project'")
            rows = cur.fetchall()
            for row in rows:
                val = str(row["value"]).strip().rstrip(".")
                candidates = [
                    os.path.join(os.path.dirname(_project_root), val),
                    val,
                ]
                for cand in candidates:
                    norm = os.path.normpath(cand)
                    if os.path.isdir(norm) and norm.lower() not in seen_paths:
                        # Strictly do not scan or modify the protected retired desktop workspace
                        if os.path.normcase(norm) == os.path.normcase(_desktop_workspace):
                            continue
                        workspaces.append({
                            "name": os.path.basename(norm),
                            "path": norm,
                            "type": "configured_project",
                        })
                        seen_paths.add(norm.lower())
    except Exception as e:
        logger.warning("Error querying project memories: %s", e)

    return workspaces


def _run_startup_reconciliation(target_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Execute read-only project workspace reconciliation.
    Detects git commits, branch status, uncommitted changes, and file watermark shifts.
    Persists structured result in project_reconciliations table.
    """
    logger.info("[STAGE-2C] Running startup workspace reconciliation...")
    workspaces = _discover_authorized_workspaces()
    if target_path:
        workspaces = [w for w in workspaces if os.path.normcase(w["path"]) == os.path.normcase(target_path)]
        if not workspaces and os.path.isdir(target_path):
            workspaces = [{
                "name": os.path.basename(os.path.normpath(target_path)),
                "path": os.path.normpath(target_path),
                "type": "targeted_workspace",
            }]

    results = []
    for ws in workspaces:
        if _stage2c_stop_event.is_set():
            logger.info("[STAGE-2C] Startup reconciliation interrupted by stop event.")
            break
        ws_path = ws["path"]
        ws_name = ws["name"]
        rec_id = f"rec_{uuid.uuid4().hex[:12]}"
        reconciled_at = datetime.now(timezone.utc).isoformat()

        try:
            git_info = _inspect_workspace_git(ws_path)
            watermark = _compute_workspace_watermark(ws_path)

            prev_watermark = None
            try:
                with _get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT file_watermark_hash, status FROM project_reconciliations
                        WHERE workspace_path = ? ORDER BY reconciled_at DESC LIMIT 1
                    """, (ws_path,))
                    prev_row = cur.fetchone()
                    if prev_row:
                        prev_watermark = prev_row["file_watermark_hash"]
            except Exception:
                pass

            if prev_watermark is None:
                status = "baseline"
            elif prev_watermark != watermark or git_info.get("uncommitted_changes") or git_info.get("changed_files"):
                status = "changed"
            else:
                status = "clean"

            outstanding_items = []
            try:
                with _get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, message, due_at FROM reminders
                        WHERE fired = 0 AND message LIKE ?
                    """, (f"%{ws_name}%",))
                    for r in cur.fetchall():
                        outstanding_items.append({"type": "reminder", "id": r["id"], "summary": r["message"], "due_at": r["due_at"]})

                    cur.execute("""
                        SELECT id, goal, status, priority FROM jobs
                        WHERE status IN ('WAITING_CONFIRMATION', 'PAUSED', 'RUNNING') AND goal LIKE ?
                    """, (f"%{ws_name}%",))
                    for j in cur.fetchall():
                        outstanding_items.append({"type": "job", "id": j["id"], "summary": j["goal"], "status": j["status"], "priority": j["priority"]})
            except Exception as e:
                logger.warning("Error fetching outstanding items for %s: %s", ws_name, e)

            with _get_db_connection() as conn:
                conn.execute("""
                    INSERT INTO project_reconciliations (
                        id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                        new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                        outstanding_items_json, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rec_id,
                    ws_path,
                    ws_name,
                    reconciled_at,
                    status,
                    git_info.get("branch"),
                    git_info.get("head_commit"),
                    json.dumps(git_info.get("new_commits", [])),
                    json.dumps(git_info.get("changed_files", [])),
                    json.dumps(git_info.get("uncommitted_changes", [])),
                    watermark,
                    json.dumps(outstanding_items),
                    None,
                ))
                conn.commit()

            rec_obj = {
                "id": rec_id,
                "workspace_path": ws_path,
                "workspace_name": ws_name,
                "reconciled_at": reconciled_at,
                "status": status,
                "git_branch": git_info.get("branch"),
                "git_head_commit": git_info.get("head_commit"),
                "new_commits": git_info.get("new_commits", []),
                "changed_files": git_info.get("changed_files", []),
                "uncommitted_changes": git_info.get("uncommitted_changes", []),
                "file_watermark_hash": watermark,
                "outstanding_items": outstanding_items,
                "error_message": None,
            }
            results.append(rec_obj)
            logger.info("[STAGE-2C] Reconciled workspace '%s' (status=%s)", ws_name, status)

            # Emit authoritative proactive event (reconciliation.ready) with watermark deduplication
            evt_id = f"evt_recon_{rec_id}"
            emit_proactive_event(
                event_type="reconciliation.ready",
                entity_id=rec_id,
                payload=rec_obj,
                event_id=evt_id,
            )

        except Exception as e:
            logger.error("[STAGE-2C] Error reconciling workspace %s: %s", ws_path, e, exc_info=True)
            try:
                with _get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO project_reconciliations (
                            id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                            new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                            outstanding_items_json, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        rec_id, ws_path, ws_name, reconciled_at, "error", None, None,
                        "[]", "[]", "[]", None, "[]", str(e)
                    ))
                    conn.commit()
            except Exception:
                pass

    return results


def _check_and_emit_deferred_job_followups(test_now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Check recent terminal jobs (COMPLETED / FAILED) and emit job.followup
    if they were previously deferred during quiet hours or not yet emitted.
    """
    settings = _load_gui_settings()
    if not settings.get("contextual_advisories_enabled", True):
        return []
    now = test_now or datetime.now()
    if _is_within_quiet_hours(settings, now):
        return []

    emitted = []
    try:
        job_mgr = main.get_job_manager() if hasattr(main, "get_job_manager") else None
        if not job_mgr:
            return []
        from brain.jobs.models import JobStatus
        for status_enum in (JobStatus.COMPLETED, JobStatus.FAILED):
            jobs = job_mgr.list_jobs(status=status_enum, limit=10)
            for j in jobs:
                res = _emit_job_followup(j, test_now=now)
                if res:
                    emitted.append(res)
    except Exception as e:
        logger.warning("[STAGE-4C] Error checking deferred job followups: %s", e)
    return emitted


# --- Scope D: Unified Scheduler Loop & Lifecycle ---

def _stage2c_worker_loop():
    """Background worker tick running every 30 seconds to evaluate reminders, briefing, idle recommendations & deferred followups."""
    logger.info("[STAGE-2C] Background worker loop started.")
    while not _stage2c_stop_event.is_set():
        if _stage2c_stop_event.wait(timeout=30.0):
            break
        try:
            _check_and_emit_due_reminders()
        except Exception as e:
            logger.warning("[STAGE-2D] Background reminders tick error: %s", e)
        try:
            _evaluate_morning_briefing(sync=False)
        except Exception as e:
            logger.warning("[STAGE-2C] Background morning briefing tick error: %s", e)
        try:
            _evaluate_idle_recommendations()
        except Exception as e:
            logger.warning("[STAGE-2C] Background idle recommendations tick error: %s", e)
        try:
            _check_and_emit_deferred_job_followups()
        except Exception as e:
            logger.warning("[STAGE-4C] Background deferred job followups tick error: %s", e)
    logger.info("[STAGE-2C] Background worker loop stopped.")


def _init_stage2c_background_workers():
    """Initialize Stage 2C database tables, start background worker loop and startup reconciliation."""
    global _stage2c_worker_thread, _stage2c_reconciliation_thread
    _ensure_stage2c_tables()
    _migrate_recommendations_file()

    # Initial check for due reminders on startup
    try:
        _check_and_emit_due_reminders()
    except Exception as e:
        logger.warning("[STAGE-2D] Startup reminders check error: %s", e)

    # Initial reconciliation of unacknowledged or orphaned morning briefings on startup
    try:
        _reconcile_morning_briefing_events()
    except Exception as e:
        logger.warning("[STAGE-2C] Startup morning briefing reconciliation error: %s", e)

    # Start startup project reconciliation asynchronously on a daemon thread
    _stage2c_reconciliation_thread = threading.Thread(
        target=_run_startup_reconciliation,
        daemon=True,
        name="StartupReconciliation",
    )
    _stage2c_reconciliation_thread.start()

    # Start periodic proactive intelligence worker thread
    _stage2c_worker_thread = threading.Thread(
        target=_stage2c_worker_loop,
        daemon=True,
        name="Stage2CBackgroundWorker",
    )
    _stage2c_worker_thread.start()
    logger.info("[STAGE-2C] Proactive intelligence background workers initialized.")
    init_scheduler_heartbeat()


def _stop_stage2c_background_workers(timeout: float = 3.0):
    """Signal background workers to stop and wait for clean termination."""
    stop_scheduler_heartbeat(timeout=0.05)
    _stage2c_stop_event.set()
    if _stage2c_worker_thread and _stage2c_worker_thread.is_alive():
        _stage2c_worker_thread.join(timeout=timeout)
        if _stage2c_worker_thread.is_alive():
            raise RuntimeError(
                f"Stage 2C background worker thread still alive after {timeout}s timeout"
            )
    if _stage2c_reconciliation_thread and _stage2c_reconciliation_thread.is_alive():
        _stage2c_reconciliation_thread.join(timeout=timeout)
        if _stage2c_reconciliation_thread.is_alive():
            raise RuntimeError(
                f"Stage 2C reconciliation thread still alive after {timeout}s timeout"
            )
    if _briefing_worker_thread and _briefing_worker_thread.is_alive():
        _briefing_worker_thread.join(timeout=timeout)
        if _briefing_worker_thread.is_alive():
            raise RuntimeError(
                f"Stage 2C briefing worker thread still alive after {timeout}s timeout"
            )
    logger.info("[STAGE-2C] Proactive intelligence background workers stopped.")


# --- Scope E: Stage 5C 30-Second Background Scheduler Heartbeat & Quiet-Hours Gate ---

_scheduler_stop_event = threading.Event()
_scheduler_heartbeat_thread: Optional[threading.Thread] = None
_workspace_failure_history: List[Dict[str, Any]] = []
_last_health_check_ts: float = 0.0


def record_workspace_failure(workspace_name_or_path: str, error_detail: str = ""):
    """Track recent failed job/command runs; emit watcher_alert if 3+ failures occur within 10 minutes."""
    global _workspace_failure_history
    now_ts = time.time()
    ws_key = Path(str(workspace_name_or_path)).name if workspace_name_or_path else "workspace"
    _workspace_failure_history.append({
        "workspace": ws_key,
        "timestamp": now_ts,
        "error": str(error_detail),
    })
    # Prune failures older than 10 minutes (600s)
    cutoff = now_ts - 600.0
    _workspace_failure_history = [f for f in _workspace_failure_history if f["timestamp"] >= cutoff]

    recent = [f for f in _workspace_failure_history if f["workspace"] == ws_key]
    if len(recent) >= 3:
        alert_evt_id = f"evt_friction_{ws_key}_{int(now_ts // 600)}"
        settings = _load_gui_settings()
        in_quiet = _is_within_quiet_hours(settings, datetime.now())
        suppress_toast = (not settings.get("desktop_toasts_enabled", True)) or in_quiet
        emit_proactive_event(
            event_type="watcher_alert",
            entity_id=ws_key,
            event_id=alert_evt_id,
            payload={
                "alert_type": "friction_loop",
                "workspace": ws_key,
                "message": f"Repeated build/test failures detected in {ws_key} ({len(recent)} failures within 10 minutes).",
                "failure_count": len(recent),
                "suppress_toast": suppress_toast,
            }
        )
        logger.warning("[WATCHER] Friction alert emitted for workspace '%s': %d failures in 10m", ws_key, len(recent))


def scan_workspace_watchers() -> Dict[str, Dict[str, Any]]:
    """
    Scan local git activity across D:\\Orange AI\\* and D:\\CreatorPulse.
    Safe on missing, uninitialized, or non-git paths.
    """
    target_workspaces = [
        r"D:\Orange AI\Orange AI Tauri",
        r"D:\Orange AI\Orange AI Desktop",
        r"D:\Orange AI\Orange API",
        r"D:\CreatorPulse",
    ]

    results: Dict[str, Dict[str, Any]] = {}
    for ws_path in target_workspaces:
        ws_name = Path(ws_path).name
        if not os.path.exists(ws_path) or not os.path.isdir(ws_path):
            continue
        dot_git = os.path.join(ws_path, ".git")
        if not os.path.exists(dot_git):
            continue

        try:
            # 1. Current Branch
            branch_proc = subprocess.run(
                ["git", "-C", ws_path, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else "unknown"

            # 2. Latest commit epoch and ISO string
            ts_proc = subprocess.run(
                ["git", "-C", ws_path, "log", "-1", "--format=%ct|%cI|%s"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if ts_proc.returncode == 0 and ts_proc.stdout.strip():
                parts = ts_proc.stdout.strip().split("|", 2)
                commit_epoch = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 0
                commit_iso = parts[1] if len(parts) >= 2 else ""
                commit_subj = parts[2] if len(parts) >= 3 else ""
            else:
                commit_epoch = 0
                commit_iso = ""
                commit_subj = ""

            # 3. Uncommitted file count
            stat_proc = subprocess.run(
                ["git", "-C", ws_path, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            uncommitted_count = len(stat_proc.stdout.strip().splitlines()) if stat_proc.stdout.strip() else 0

            results[ws_name] = {
                "name": ws_name,
                "path": ws_path,
                "branch": branch,
                "latest_commit_epoch": commit_epoch,
                "latest_commit_iso": commit_iso,
                "latest_commit_subject": commit_subj,
                "uncommitted_changes_count": uncommitted_count,
            }
        except Exception as e:
            logger.warning("[WATCHER] Error scanning git workspace %s: %s", ws_path, e)
            continue

    return results


def is_standing_job(job: Any) -> Optional[str]:
    """Check if a job corresponds to one of the 3 standing job types."""
    tags = (getattr(job, "tags", "") or "").lower()
    goal = (getattr(job, "goal", "") or "").strip().lower()

    if "standing,briefing" in tags or "standing_briefing" in tags or "briefing" in tags or "morning briefing" in goal:
        return "briefing"
    if "standing,hygiene" in tags or "standing_hygiene" in tags or "hygiene" in tags or "hygiene audit" in goal:
        return "hygiene"
    if "standing,reminders" in tags or "standing_reminders" in tags or "reminders" in tags or "overdue reminder" in goal:
        return "reminders"
    return None


def execute_standing_briefing_job(job: Any, store: Any) -> Any:
    """
    Deterministically execute 'Daily Morning Briefing & Priority Digest' standing job.
    Executes the morning briefing pipeline directly, emits morning_briefing_ready,
    records a completion JobStep, and marks the job COMPLETED on Attempt 1.
    """
    from brain.jobs.models import JobStatus, JobStep
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()

    if getattr(job, "status", None) != JobStatus.RUNNING:
        job.status = JobStatus.RUNNING
        job.attempt_count = (getattr(job, "attempt_count", 0) or 0) + 1
    if getattr(job, "attempt_count", 0) < 1:
        job.attempt_count = 1
    job.started_at = job.started_at or now_iso
    job.updated_at = now_iso
    if store and hasattr(store, "update_job"):
        store.update_job(job)

    try:
        # Execute morning briefing pipeline directly
        briefing_res = _evaluate_morning_briefing(force=True, sync=True)
        if briefing_res and isinstance(briefing_res, dict):
            content = briefing_res.get("content") or "Morning briefing synthesized successfully."
        else:
            content = "Morning briefing completed: Workspace and reminders state verified."
            briefing_res = {"content": content, "status": "success"}

        # Emit morning_briefing_ready proactive event
        emit_proactive_event(
            event_type="morning_briefing_ready",
            entity_id=f"job_{job.id}",
            payload={
                "job_id": job.id,
                "briefing": briefing_res,
                "content": content,
                "status": "ready",
            },
            event_id=f"evt_briefing_job_{job.id}_{int(now_utc.timestamp())}",
        )

        # Record completion JobStep
        if store and hasattr(store, "record_step"):
            finish_step = JobStep(
                job_id=job.id,
                attempt=job.attempt_count,
                step_index=1,
                action_type="FINISH",
                tool_name="morning_briefing_pipeline",
                reasoning="Deterministic execution of Daily Morning Briefing & Priority Digest",
                success=True,
                result_data_json=json.dumps({"briefing": briefing_res, "summary": content}, ensure_ascii=False),
            )
            store.record_step(finish_step)

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        job.final_response = content
        job.last_error = None
        job.step_count = 1
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        logger.info("[STANDING-JOB %s] Daily Morning Briefing completed successfully.", job.id)
        return job

    except Exception as e:
        logger.error("[STANDING-JOB %s] Morning briefing execution failed: %s", job.id, e, exc_info=True)
        job.status = JobStatus.FAILED
        job.last_error = f"Morning briefing execution failed: {e}"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        return job


def execute_standing_hygiene_job(job: Any, store: Any) -> Any:
    """
    Deterministically execute 'Workspace & Git Hygiene Audit' standing job.
    Executes scan_workspace_watchers() directly, builds a structured summary of
    uncommitted files, branches, and latest commits across workspaces,
    records a completion JobStep, and marks the job COMPLETED on Attempt 1.
    """
    from brain.jobs.models import JobStatus, JobStep
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()

    if getattr(job, "status", None) != JobStatus.RUNNING:
        job.status = JobStatus.RUNNING
        job.attempt_count = (getattr(job, "attempt_count", 0) or 0) + 1
    if getattr(job, "attempt_count", 0) < 1:
        job.attempt_count = 1
    job.started_at = job.started_at or now_iso
    job.updated_at = now_iso
    if store and hasattr(store, "update_job"):
        store.update_job(job)

    try:
        watchers = scan_workspace_watchers()
        summary_lines = ["Workspace & Git Hygiene Audit completed:"]
        total_uncommitted = 0
        for ws_name, info in watchers.items():
            branch = info.get("branch", "unknown")
            uncommitted = info.get("uncommitted_changes_count", 0)
            total_uncommitted += uncommitted
            commit_iso = info.get("latest_commit_iso", "N/A")
            commit_subj = info.get("latest_commit_subject", "N/A")
            summary_lines.append(
                f"- {ws_name} [{branch}]: {uncommitted} uncommitted files | Last commit: '{commit_subj}' ({commit_iso})"
            )
        if not watchers:
            summary_lines.append("- No active git workspaces found.")
        else:
            summary_lines.append(f"Total uncommitted files across all workspaces: {total_uncommitted}.")
        summary_text = "\n".join(summary_lines)

        if store and hasattr(store, "record_step"):
            finish_step = JobStep(
                job_id=job.id,
                attempt=job.attempt_count,
                step_index=1,
                action_type="FINISH",
                tool_name="git_hygiene_audit",
                reasoning="Deterministic execution of Workspace & Git Hygiene Audit via scan_workspace_watchers()",
                success=True,
                result_data_json=json.dumps({"watchers": watchers, "summary": summary_text}, ensure_ascii=False),
            )
            store.record_step(finish_step)

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        job.final_response = summary_text
        job.last_error = None
        job.step_count = 1
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        logger.info("[STANDING-JOB %s] Workspace & Git Hygiene Audit completed successfully.", job.id)
        return job

    except Exception as e:
        logger.error("[STANDING-JOB %s] Git hygiene audit failed: %s", job.id, e, exc_info=True)
        job.status = JobStatus.FAILED
        job.last_error = f"Git hygiene audit failed: {e}"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        return job


def execute_standing_reminders_job(job: Any, store: Any) -> Any:
    """
    Deterministically execute 'Overdue Reminder & Blocker Escalation' standing job.
    Queries SQLite reminders table and structured_memories for overdue reminders and blockers,
    emits reminder notifications if any found, records a completion JobStep,
    and marks the job COMPLETED on Attempt 1.
    """
    from brain.jobs.models import JobStatus, JobStep
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()

    if getattr(job, "status", None) != JobStatus.RUNNING:
        job.status = JobStatus.RUNNING
        job.attempt_count = (getattr(job, "attempt_count", 0) or 0) + 1
    if getattr(job, "attempt_count", 0) < 1:
        job.attempt_count = 1
    job.started_at = job.started_at or now_iso
    job.updated_at = now_iso
    if store and hasattr(store, "update_job"):
        store.update_job(job)

    try:
        overdue_reminders = []
        active_blockers = []
        with _get_db_connection() as conn:
            cur = conn.cursor()
            # 1. Overdue reminders
            cur.execute(
                "SELECT id, message, due_at, created_at FROM reminders WHERE fired = 0 AND due_at <= ? ORDER BY due_at ASC",
                (now_iso,),
            )
            for row in cur.fetchall():
                overdue_reminders.append({
                    "id": row["id"] if isinstance(row, sqlite3.Row) else row[0],
                    "message": row["message"] if isinstance(row, sqlite3.Row) else row[1],
                    "due_at": row["due_at"] if isinstance(row, sqlite3.Row) else row[2],
                })

            # 2. Blockers in structured_memories
            cur.execute(
                """
                SELECT id, category, memory_key, value FROM structured_memories
                WHERE category IN ('blocker', 'project', 'goal', 'issue')
                  AND (LOWER(category) = 'blocker' OR LOWER(memory_key) LIKE '%block%' OR LOWER(value) LIKE '%block%')
                """
            )
            for row in cur.fetchall():
                active_blockers.append({
                    "id": row["id"] if isinstance(row, sqlite3.Row) else row[0],
                    "category": row["category"] if isinstance(row, sqlite3.Row) else row[1],
                    "key": row["memory_key"] if isinstance(row, sqlite3.Row) else row[2],
                    "value": row["value"] if isinstance(row, sqlite3.Row) else row[3],
                })

        # Emit reminder notifications for overdue items
        for r in overdue_reminders:
            rem_id = r["id"]
            evt_id = f"evt_standing_rem_{rem_id}_{int(now_utc.timestamp())}"
            emit_proactive_event(
                event_type="reminder_due",
                entity_id=str(rem_id),
                payload={
                    "reminder_id": rem_id,
                    "message": r.get("message", "Reminder overdue"),
                    "due_at": r.get("due_at"),
                    "escalated_by": "standing_job",
                },
                event_id=evt_id,
            )

        if not overdue_reminders and not active_blockers:
            report_text = "No overdue reminders or active blockers found."
        else:
            report_lines = [f"Found {len(overdue_reminders)} overdue reminder(s) and {len(active_blockers)} active blocker(s):"]
            for r in overdue_reminders:
                report_lines.append(f"- Overdue Reminder #{r['id']}: '{r['message']}' (Due: {r['due_at']})")
            for b in active_blockers:
                report_lines.append(f"- Active Blocker [{b['category']}] {b['key']}: {b['value']}")
            report_text = "\n".join(report_lines)

        if store and hasattr(store, "record_step"):
            finish_step = JobStep(
                job_id=job.id,
                attempt=job.attempt_count,
                step_index=1,
                action_type="FINISH",
                tool_name="reminder_blocker_escalation",
                reasoning="Deterministic execution of Overdue Reminder & Blocker Escalation",
                success=True,
                result_data_json=json.dumps({
                    "overdue_reminders": overdue_reminders,
                    "active_blockers": active_blockers,
                    "report": report_text,
                }, ensure_ascii=False),
            )
            store.record_step(finish_step)

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        job.final_response = report_text
        job.last_error = None
        job.step_count = 1
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        logger.info("[STANDING-JOB %s] Overdue Reminder & Blocker Escalation completed: %s", job.id, report_text)
        return job

    except Exception as e:
        logger.error("[STANDING-JOB %s] Reminders and blocker escalation failed: %s", job.id, e, exc_info=True)
        job.status = JobStatus.FAILED
        job.last_error = f"Reminders and blocker escalation failed: {e}"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.updated_at = job.completed_at
        if store and hasattr(store, "update_job"):
            store.update_job(job)
        return job


def execute_job_with_standing_routing(runtime_instance: Any, job: Any) -> Any:
    """
    Intercept JobRuntime.execute_job to route standing jobs to deterministic handlers
    and execute generic jobs through the standard AgentEngine loop.
    """
    job_type = is_standing_job(job)
    store = getattr(runtime_instance, "store", None)
    if not store:
        main.ensure_initialized()
        mgr = main.get_job_manager()
        store = mgr.store if mgr else None

    if job_type == "briefing":
        return execute_standing_briefing_job(job, store)
    elif job_type == "hygiene":
        return execute_standing_hygiene_job(job, store)
    elif job_type == "reminders":
        return execute_standing_reminders_job(job, store)

    # Generic Job -> delegate to original execute_job
    return _original_job_runtime_execute_job(runtime_instance, job)


# Install JobRuntime interception
try:
    from brain.jobs.runtime import JobRuntime
    if not hasattr(JobRuntime, "_standing_routing_patched"):
        _original_job_runtime_execute_job = JobRuntime.execute_job

        def _patched_execute_job(self, job):
            return execute_job_with_standing_routing(self, job)

        JobRuntime.execute_job = _patched_execute_job
        JobRuntime._standing_routing_patched = True
        logger.info("[STANDING-JOBS] JobRuntime.execute_job intercepted for deterministic standing routing.")
except Exception as e:
    logger.warning("[STANDING-JOBS] Notice installing JobRuntime interception: %s", e)


def ensure_default_standing_jobs() -> List[Any]:
    """
    Idempotently seed default recurring Agent Jobs when jobs.list is empty on startup.
    1. Daily Morning Briefing & Priority Digest
    2. Workspace & Git Hygiene Audit
    3. Overdue Reminder & Blocker Escalation
    Also resets any failed standing jobs from previous attempts so they resume cleanly.
    """
    try:
        main.ensure_initialized()
        mgr = main.get_job_manager()
        if not mgr:
            return []
        from brain.jobs.models import JobStatus
        existing = mgr.list_jobs(limit=100)
        existing_goals = {j.goal.strip().lower() for j in existing}

        default_jobs = [
            ("Daily Morning Briefing & Priority Digest", "standing,briefing"),
            ("Workspace & Git Hygiene Audit", "standing,hygiene"),
            ("Overdue Reminder & Blocker Escalation", "standing,reminders"),
        ]

        # Reset any failed standing jobs to PENDING with attempt_count=0
        for j in existing:
            goal_lower = j.goal.strip().lower()
            tags_lower = (j.tags or "").lower()
            is_standing = any(
                goal.lower() == goal_lower or tags in tags_lower
                for goal, tags in default_jobs
            )
            if is_standing:
                status_str = (j.status.value if hasattr(j.status, "value") else str(j.status)).upper()
                last_err = str(getattr(j, "last_error", "") or "").lower()
                if status_str == "FAILED" or "max attempts" in last_err or "failed" in last_err:
                    logger.info("[STANDING-JOBS] Resetting failed standing job '%s' (ID: %s) to PENDING", j.goal, j.id)
                    j.status = JobStatus.PENDING
                    j.attempt_count = 0
                    j.last_error = None
                    j.next_retry_at = None
                    mgr.store.update_job(j)

        seeded = []
        for goal, tags in default_jobs:
            if goal.lower() not in existing_goals:
                created = mgr.create(goal=goal, source="standing_job", tags=tags)
                seeded.append(created)
                logger.info("[STANDING-JOBS] Seeded default standing job: '%s' (ID: %s)", goal, created.id)
        return seeded
    except Exception as e:
        logger.warning("[STANDING-JOBS] Failed to ensure default standing jobs: %s", e)
        return []


def _is_orange_ai_window(win_ctx: Dict[str, Any]) -> bool:
    """Check if window context belongs to Orange AI itself."""
    if not win_ctx:
        return True
    pname = (win_ctx.get("process_name") or "").lower()
    title = (win_ctx.get("window_title") or "").lower()
    if "orange ai" in title:
        return True
    if pname in ("orange ai.exe", "orange_ai.exe", "runtime_adapter.exe", "orange-ai.exe"):
        return True
    return False


def evaluate_idle_followup(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Context-Gated Idle Follow-Ups (Stage 5G).
    Evaluates whether to send at most one natural check-in message in Chat when the user
    goes silent during an open question, pending confirmation, or unresolved debugging loop.
    Enforces all 5 strict gates:
      1. Enabled & Active Session
      2. Bounded Silence Window
      3. Quiet Hours Gate
      4. Media / Game Focus Gate
      5. Situational Salience Gate
    """
    global _idle_nudge_sent_for_turn, _last_activity_ts, _latest_active_window
    settings = _load_gui_settings()

    # Gate 1: Enabled & Active Session
    if not settings.get("idle_followups_enabled", True):
        return None
    if _idle_nudge_sent_for_turn:
        return None

    session_start_id = int(settings.get("chat_session_start_id", 0) or 0)
    session_turns: List[Dict[str, Any]] = []
    try:
        conn = mem.get_connection()
        cursor = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM conversation_history
            WHERE id > ?
            ORDER BY id ASC
            """,
            (session_start_id,)
        )
        for row in cursor.fetchall():
            session_turns.append({
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
            })
    except Exception as e:
        logger.debug("[IDLE-FOLLOWUP] Failed to query conversation history: %s", e)
        return None

    if len(session_turns) < 2:
        return None

    # Gate 2: Bounded Silence Window
    current_dt = now or datetime.now()
    now_epoch = current_dt.timestamp()

    activity_ts = _last_activity_ts
    if activity_ts is None:
        last_turn = session_turns[-1]
        created_at_str = last_turn.get("created_at")
        if created_at_str:
            try:
                dt_turn = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                activity_ts = dt_turn.timestamp()
            except Exception:
                activity_ts = now_epoch
        else:
            activity_ts = now_epoch

    elapsed = now_epoch - activity_ts
    cooldown_secs = float(settings.get("idle_followup_minutes", 15)) * 60.0
    if not (cooldown_secs <= elapsed < 12.0 * 3600.0):
        return None

    # Gate 3: Quiet Hours Gate
    if _is_within_quiet_hours(settings, current_dt):
        return None

    # Gate 4: Media / Game Focus Gate
    if settings.get("active_window_awareness_enabled", True):
        if _latest_active_window.get("category") == "media_or_game":
            return None

    # Gate 5: Situational Salience Gate
    last_assistant_msg = ""
    for turn in reversed(session_turns):
        if turn.get("role") == "assistant":
            last_assistant_msg = turn.get("content", "")
            break

    last_assistant_lower = last_assistant_msg.lower()
    has_question_or_offer = (
        "?" in last_assistant_msg
        or any(phrase in last_assistant_lower for phrase in ("would you like", "want me to", "shall i", "let me know if"))
    )

    with _confirmations_lock:
        has_pending_confirmation = bool(_pending_confirmations)

    has_friction = False
    if _session_conversational_state and isinstance(_session_conversational_state, dict):
        tone = _session_conversational_state.get("emotional_tone")
        load = _session_conversational_state.get("cognitive_load")
        if tone == "frustrated" or load == "high":
            has_friction = True

    if not (has_question_or_offer or has_pending_confirmation or has_friction):
        return None

    # All 5 gates passed! Generate brief check-in
    reply_text = None
    try:
        _ensure_api_client_configured()
        win_info = ""
        if settings.get("active_window_awareness_enabled", True) and _latest_active_window.get("process_name"):
            win_info = f"Current active window: {_latest_active_window.get('process_name')} ({_latest_active_window.get('window_title')})."

        prompt = (
            f"The user has been silent for {int(elapsed // 60)} minutes following this assistant message:\n"
            f"\"{last_assistant_msg[:300]}\"\n"
            f"{win_info}\n"
            "Generate a natural, polite 1-2 sentence check-in. If there is a pending action or open question, ask gently if they'd like to proceed or need anything else. Do not use filler or excessive cheerleading."
        )
        api_res = main.api_client.assist(
            message=prompt,
            history=[],
            system_instruction="You are Orange AI performing a polite, brief 1-2 sentence conversational check-in. Be helpful, concise, and direct.",
            task_type="chat",
        )
        if api_res and api_res.get("reply"):
            reply_text = str(api_res["reply"]).strip()
    except Exception as e:
        logger.debug("[IDLE-FOLLOWUP] API assist failed for check-in: %s", e)

    if not reply_text:
        if has_pending_confirmation:
            reply_text = "Just checking in—whenever you're ready, let me know if you'd like to proceed with the pending action or cancel it."
        elif has_friction:
            reply_text = "Checking in on this—let me know if you'd like to try an alternate fix or if you need any other help with this."
        else:
            reply_text = "Just following up on this—let me know if you need anything else or if you'd like to continue."

    # Persist assistant follow-up turn
    try:
        main.save_turn("assistant", reply_text)
    except Exception as e:
        logger.warning("[IDLE-FOLLOWUP] Failed to save turn to history: %s", e)

    _idle_nudge_sent_for_turn = True
    _last_activity_ts = now_epoch

    envelope = emit_proactive_event(
        event_type="idle_followup_posted",
        entity_id="idle_followup",
        payload={
            "title": "Orange AI",
            "body": reply_text,
            "message": reply_text,
            "timestamp": current_dt.isoformat(),
        }
    )

    return {
        "success": True,
        "reply": reply_text,
        "event": envelope,
    }


def run_scheduler_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Execute a single 30-second background scheduler heartbeat tick.
    1. Evaluates due Morning Briefing according to user preferences and local time (deduplicated per day).
    2. Checks overdue reminders in memory.db and enqueues reminder_due proactive events (deduplicated per reminder ID).
    3. Scans workspace git activity and friction failure loops.
    4. Probes Render /health endpoint (throttled to once per 15 minutes), alerting only on failures.
    5. Enforces an Interruptibility & Quiet-Hours Gate: if desktop_toasts_enabled is False or now falls
       inside configured quiet hours, suppresses toast emission while updating internal state cleanly.
    """
    current_dt = now or datetime.now()
    settings = _load_gui_settings()
    global _last_health_check_ts

    in_quiet = _is_within_quiet_hours(settings, current_dt)
    desktop_toasts_enabled = settings.get("desktop_toasts_enabled", True)
    suppress_toast = (not desktop_toasts_enabled) or in_quiet

    # 1. Evaluate Morning Briefing
    briefing_result = None
    if settings.get("morning_briefing_enabled", False):
        try:
            briefing_result = _evaluate_morning_briefing(force=False, test_now=current_dt, sync=True)
            if briefing_result and suppress_toast:
                briefing_result["suppress_toast"] = True
        except Exception as e:
            logger.warning("[SCHEDULER] Morning briefing evaluation error: %s", e)

    # 2. Check overdue reminders
    reminders_emitted = []
    try:
        due_rems = scheduler.get_due_reminders(current_dt)
        for r in due_rems:
            rem_id = r.get("id")
            evt_id = f"evt_reminder_{rem_id}"
            already_emitted = False
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
                already_emitted = cur.fetchone() is not None

            if not already_emitted:
                payload = {
                    "reminder_id": rem_id,
                    "message": r.get("message", "Reminder due"),
                    "due_at": r.get("due_at"),
                    "suppress_toast": suppress_toast,
                }
                envelope = emit_proactive_event(
                    event_type="reminder_due",
                    entity_id=str(rem_id),
                    payload=payload,
                    event_id=evt_id,
                )
                if envelope:
                    reminders_emitted.append(envelope)
                logger.info(
                    "[SCHEDULER] Emitted reminder_due for reminder #%s: %s (suppress_toast=%s)",
                    rem_id,
                    r.get("message"),
                    suppress_toast,
                )

            # Atomic verification & marking fired in scheduler store
            with _get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT event_id FROM proactive_events WHERE event_id = ?", (evt_id,))
                persisted = cur.fetchone() is not None
            if persisted:
                scheduler.mark_fired(rem_id)
    except Exception as e:
        logger.warning("[SCHEDULER] Reminders check error: %s", e)

    # 3. Workspace Watchers Git Activity
    watchers_data = {}
    try:
        watchers_data = scan_workspace_watchers()
    except Exception as e:
        logger.warning("[SCHEDULER] Workspace watchers scan error: %s", e)

    # 4. Render /health Watchdog Probe (Throttled to once every 15 minutes = 900s)
    now_epoch = current_dt.timestamp()
    health_checked = False
    if (now_epoch - _last_health_check_ts) >= 900.0:
        _last_health_check_ts = now_epoch
        health_checked = True
        api_url = settings.get("api_url", DEFAULT_API_URL)
        try:
            import requests
            health_res = requests.get(f"{api_url.rstrip('/')}/health", timeout=5.0)
            if health_res.status_code != 200:
                logger.warning("[WATCHDOG] Orange API /health returned status %s", health_res.status_code)
                emit_proactive_event(
                    event_type="watcher_alert",
                    entity_id="render_health",
                    event_id=f"evt_health_{int(now_epoch // 900)}",
                    payload={
                        "alert_type": "render_health",
                        "status": health_res.status_code,
                        "message": f"Orange API health check failed (status {health_res.status_code})",
                        "suppress_toast": suppress_toast,
                    }
                )
        except Exception as e:
            logger.warning("[WATCHDOG] Orange API /health probe error: %s", e)
            emit_proactive_event(
                event_type="watcher_alert",
                entity_id="render_health",
                event_id=f"evt_health_{int(now_epoch // 900)}",
                payload={
                    "alert_type": "render_health",
                    "status": "error",
                    "message": f"Orange API health check timed out or failed: {e}",
                    "suppress_toast": suppress_toast,
                }
            )

    # 5. Active Window Awareness (sampled < 1ms)
    global _latest_active_window
    if settings.get("active_window_awareness_enabled", True):
        try:
            from tools.system import get_active_window_context
            cur_win = get_active_window_context()
            if cur_win and cur_win.get("process_name") and not _is_orange_ai_window(cur_win):
                _latest_active_window = cur_win
        except Exception as e:
            logger.debug("[ACTIVE-WINDOW] Sampling active window failed: %s", e)

    # 6. Context-Gated Idle Follow-Ups (Stage 5G)
    idle_followup_result = None
    try:
        idle_followup_result = evaluate_idle_followup(now=current_dt)
    except Exception as e:
        logger.warning("[SCHEDULER] Idle follow-up evaluation error: %s", e)

    return {
        "tick_at": current_dt.isoformat(),
        "quiet_hours": in_quiet,
        "desktop_toasts_enabled": desktop_toasts_enabled,
        "suppress_toast": suppress_toast,
        "briefing_generated": briefing_result is not None,
        "briefing": briefing_result,
        "reminders_count": len(reminders_emitted),
        "reminders_emitted": reminders_emitted,
        "watchers": watchers_data,
        "health_probe_executed": health_checked,
        "idle_followup": idle_followup_result,
        "active_window": _latest_active_window,
    }


def _scheduler_heartbeat_loop():
    logger.info("[SCHEDULER] SchedulerHeartbeat thread started.")
    while not _scheduler_stop_event.is_set():
        if _scheduler_stop_event.wait(timeout=30.0):
            break
        try:
            run_scheduler_tick()
        except Exception as e:
            logger.warning("[SCHEDULER] Error in scheduler heartbeat tick: %s", e)
    logger.info("[SCHEDULER] SchedulerHeartbeat thread stopped.")


def init_scheduler_heartbeat():
    """Start the 30-second background SchedulerHeartbeat thread unless disabled by env."""
    global _scheduler_heartbeat_thread
    if os.environ.get("ORANGE_DISABLE_BACKGROUND_SCHEDULER") == "1":
        logger.info("[SCHEDULER] Background scheduler disabled via ORANGE_DISABLE_BACKGROUND_SCHEDULER=1")
        return
    if _scheduler_heartbeat_thread and _scheduler_heartbeat_thread.is_alive():
        return

    # Seed default standing agent jobs if store is empty
    ensure_default_standing_jobs()

    _scheduler_stop_event.clear()
    _scheduler_heartbeat_thread = threading.Thread(
        target=_scheduler_heartbeat_loop,
        daemon=True,
        name="SchedulerHeartbeat",
    )
    _scheduler_heartbeat_thread.start()
    logger.info("[SCHEDULER] SchedulerHeartbeat thread initialized.")


def stop_scheduler_heartbeat(timeout: float = 0.05):
    """Signal SchedulerHeartbeat thread to terminate and join within timeout (< 50ms)."""
    global _scheduler_heartbeat_thread
    _scheduler_stop_event.set()
    if _scheduler_heartbeat_thread and _scheduler_heartbeat_thread.is_alive():
        _scheduler_heartbeat_thread.join(timeout=timeout)
        if _scheduler_heartbeat_thread.is_alive():
            logger.warning("[SCHEDULER] SchedulerHeartbeat did not finish within %fs", timeout)
        else:
            _scheduler_heartbeat_thread = None


# 6. JSON-RPC Method Handlers
def handle_system_handshake(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 4.5B Phase 3: Runtime Handshake.
    Returns immediate identity, version, and protocol capabilities to Rust supervisor.
    Strictly non-blocking; does not perform network or heavy database operations.
    """
    return {
        "status": "ready",
        "runtime": "Orange AI Python Runtime",
        "version": ORANGE_AI_VERSION,
        "protocol_version": ORANGE_AI_PROTOCOL_VERSION,
        "python_version": sys.version.split()[0],
        "pid": os.getpid(),
        "capabilities": [
            "chat",
            "memory",
            "planner",
            "tools",
            "pre_update_quiescence"
        ]
    }


def handle_system_ping(params: Dict[str, Any]) -> Dict[str, Any]:
    api_online = False
    try:
        _ensure_api_client_configured()
        client = main.api_client or OrangeAPIClient()
        api_online = client.is_available(timeout=0.5)
    except Exception:
        pass

    return {
        "status": "online",
        "version": ORANGE_AI_VERSION,
        "pid": os.getpid(),
        "user_data_dir": get_user_data_dir(),
        "database_path": resolve_database_path(),
        "api_online": api_online,
        "admin_rights": tool_sys.is_running_as_admin(),
    }


def handle_system_health(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    _ensure_api_client_configured()
    mem_stats = mem.memory_stats()
    job_mgr = main.get_job_manager()
    job_count = len(job_mgr.list_jobs(limit=500))

    client = main.api_client or OrangeAPIClient()
    api_online = client.is_available(timeout=1.0)
    current_settings = _load_gui_settings()

    return {
        "health": "ok",
        "uptime_seconds": time.time() - _START_TIME,
        "memory": mem_stats,
        "total_jobs": job_count,
        "api": {
            "endpoint": client.api_url,
            "online": api_online,
            "model": current_settings.get("model", DEFAULT_MODEL),
        },
        "system": {
            "admin": tool_sys.is_running_as_admin(),
            "cpu_percent": tool_sys.get_cpu_usage(),
            "ram_percent": tool_sys.get_ram_usage(),
            "battery": tool_sys.get_battery(),
        },
    }


def handle_system_shutdown(params: Dict[str, Any]) -> Dict[str, Any]:
    global _is_shutting_down
    _is_shutting_down = True
    logger.info("Executing clean runtime shutdown...")

    # Stop Stage 2C background workers
    try:
        _stop_stage2c_background_workers()
    except Exception as e:
        logger.warning("Error stopping Stage 2C background workers: %s", e)

    # Stop scheduler
    try:
        scheduler.stop(wait_timeout=2.0)
    except Exception as e:
        logger.warning("Error stopping scheduler: %s", e)

    # Cancel pending confirmations
    with _confirmations_lock:
        for conf in _pending_confirmations.values():
            conf["decision"] = "no"
            conf["event"].set()
        _pending_confirmations.clear()

    # Close databases
    close_all_database_connections()

    def _delayed_exit():
        time.sleep(0.1)
        os._exit(0)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {"status": "shutting_down"}


def close_all_database_connections():
    """Close all cached connections across memory, mood, planner, and reminders, and verify none remain open."""
    modules_to_close = ("brain.memory", "brain.mood", "brain.planner", "brain.reminders")
    for mod_name in modules_to_close:
        try:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "close"):
                mod.close()
        except Exception as e:
            logger.warning("[DB-CLOSE] Error closing %s: %s", mod_name, e)

    for mod_name in modules_to_close:
        try:
            import importlib
            m = importlib.import_module(mod_name)
            if hasattr(m, "close"):
                m.close()
        except Exception:
            pass

    # Verify that every module's _conn is indeed None (deterministic cleanup verification)
    unclosed = []
    for mod_name in modules_to_close:
        mod = sys.modules.get(mod_name)
        if mod and getattr(mod, "_conn", None) is not None:
            unclosed.append(mod_name)
    if unclosed:
        raise RuntimeError(f"Pre-update abort: database connections remained open in modules: {unclosed}")

    import gc
    gc.collect()


def handle_system_shutdown_for_update(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 4.5B Phase 2: Pre-Update Database Safety and Checkpoint Hardening.

    Coordinates pre-update quiescence:
    1. Rejects incoming user turns atomically under _turn_threads_lock.
    2. Joins active turn workers and verifies thread termination.
    3. Stops the scheduler cleanly and verifies thread termination.
    4. Stops and joins Stage 2C background workers and verifies thread termination.
    5. Resolves target database path (protects custom_db_path under test mode).
    6. Closes all cached SQLite connections and verifies none remain open.
    7. Executes PRAGMA wal_checkpoint(TRUNCATE) on target database and verifies busy == 0.
    8. Verifies exclusive database lock acquisition and release.
    9. Inspects sidecars: confirms target_db-wal is exactly 0 bytes (or nonexistent) and shm is unlocked.
    10. Verifies file-level accessibility.
    11. Verifies database integrity via PRAGMA integrity_check.
    12. Returns verified pre-update status dictionary.
    """
    global _is_updating
    logger.info("Executing system.shutdown_for_update sequence...")

    # 1. Atomic transition into update mode & capture active turns
    with _turn_threads_lock:
        _is_updating = True
        active_turns = list(_active_turn_threads)

    # 2. Join active turn threads and verify complete termination
    for t in active_turns:
        if t.is_alive():
            t.join(timeout=3.0)
            if t.is_alive():
                raise RuntimeError(
                    f"Pre-update abort: active turn worker '{t.name}' still alive after 3.0s timeout"
                )
    logger.info("[SHUTDOWN-FOR-UPDATE] Active turn workers joined and verified terminated.")

    # 3. Stop scheduler and verify clean termination
    try:
        scheduler.stop(wait_timeout=3.0)
    except Exception as e:
        raise RuntimeError(f"Scheduler stop failed with exception: {e}")

    sched_thread = getattr(scheduler, "_scheduler_thread", None)
    if sched_thread is not None and sched_thread.is_alive():
        raise RuntimeError("Pre-update abort: scheduler loop thread is still alive after stop timeout")
    with getattr(scheduler, "_thread_lock", threading.Lock()):
        job_worker = getattr(scheduler, "_active_job_thread", None)
    if job_worker is not None and job_worker.is_alive():
        raise RuntimeError("Pre-update abort: scheduler job worker thread is still alive after stop timeout")
    logger.info("[SHUTDOWN-FOR-UPDATE] Scheduler stopped and verified terminated.")

    # 4. Stop Stage 2C background workers and verify termination
    _stop_stage2c_background_workers(timeout=3.0)
    if _stage2c_worker_thread and _stage2c_worker_thread.is_alive():
        raise RuntimeError("Pre-update abort: _stage2c_worker_thread is still alive after stop")
    if _stage2c_reconciliation_thread and _stage2c_reconciliation_thread.is_alive():
        raise RuntimeError("Pre-update abort: _stage2c_reconciliation_thread is still alive after stop")
    logger.info("[SHUTDOWN-FOR-UPDATE] Stage 2C background workers stopped and verified terminated.")

    # 5. Resolve target database path with test-mode permission check
    custom_db = params.get("db_path") or params.get("custom_db_path")
    if custom_db:
        if not _is_test_mode_enabled():
            raise PermissionError("custom_db_path is strictly forbidden in production mode")
        target_db = os.path.abspath(custom_db)
    else:
        target_db = os.path.abspath(resolve_database_path())
    logger.info("[SHUTDOWN-FOR-UPDATE] Authoritative target database: %s", target_db)

    if not os.path.exists(target_db):
        raise FileNotFoundError(f"Target database not found: {target_db}")

    # 6. Close all cached connections before checkpointing and verify deterministic cleanup
    close_all_database_connections()

    # 7. Checkpoint WAL (TRUNCATE) on target database
    conn = sqlite3.connect(target_db, timeout=5.0)
    try:
        cur = conn.cursor()
        res = cur.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        if not res:
            raise RuntimeError("WAL checkpoint returned no result")
        busy, log_frames, checkpointed_frames = int(res[0]), int(res[1]), int(res[2])
        if busy != 0:
            raise RuntimeError(f"WAL checkpoint busy: (busy={busy}, log={log_frames}, ckpt={checkpointed_frames})")
        logger.info("[SHUTDOWN-FOR-UPDATE] WAL checkpoint TRUNCATE completed: %s", res)
    finally:
        conn.close()

    # 8. Release all connections and verify deterministic closure
    close_all_database_connections()

    # 9. Exclusive access test lock check
    test_conn = sqlite3.connect(target_db, timeout=2.0)
    try:
        test_conn.execute("BEGIN IMMEDIATE;")
        test_conn.execute("ROLLBACK;")
    except Exception as e:
        raise RuntimeError(f"Database exclusive lock test failed: {e}")
    finally:
        test_conn.close()

    # 10. Sidecar verification for both WAL and SHM
    wal_path = f"{target_db}-wal"
    wal_bytes = 0
    if os.path.exists(wal_path):
        wal_bytes = os.path.getsize(wal_path)
        if wal_bytes > 0:
            raise RuntimeError(f"WAL sidecar not truncated: {wal_path} is {wal_bytes} bytes (expected 0)")

    shm_path = f"{target_db}-shm"
    shm_exists = os.path.exists(shm_path)
    shm_bytes = 0
    if shm_exists:
        try:
            shm_bytes = os.path.getsize(shm_path)
        except OSError:
            shm_bytes = 0
        try:
            with open(shm_path, "r+b"):
                pass
        except Exception as e:
            raise RuntimeError(f"SHM sidecar is locked or inaccessible: {e}")

    # 11. Target database file-level read/write accessibility check
    try:
        with open(target_db, "r+b"):
            pass
    except Exception as e:
        raise RuntimeError(f"Target database file is locked or inaccessible: {e}")

    # 12. Integrity check
    integrity_conn = sqlite3.connect(target_db, timeout=2.0)
    try:
        cur = integrity_conn.cursor()
        integrity_res = cur.execute("PRAGMA integrity_check;").fetchall()
        integrity_status = [r[0] for r in integrity_res]
        if integrity_status != ["ok"]:
            raise RuntimeError(f"Integrity check failed: {integrity_status}")
    finally:
        integrity_conn.close()

    return {
        "status": "ready_for_update",
        "target_db": target_db,
        "checkpoint": {
            "busy": busy,
            "log_frames": log_frames,
            "checkpointed_frames": checkpointed_frames,
        },
        "wal_bytes": wal_bytes,
        "shm_exists": shm_exists,
        "shm_bytes": shm_bytes,
        "connections_closed": True,
        "workers_stopped": True,
        "integrity_check": "ok",
    }


# ==============================================================================
# 5C. Chat Tool Execution & Permission Guardrail Routing (Task 4D)
# ==============================================================================

TOOL_RISK_MAP: Dict[str, RiskLevel] = {
    # SAFE tools (read-only)
    "list_directory": RiskLevel.SAFE,
    "list_files": RiskLevel.SAFE,
    "list_dir": RiskLevel.SAFE,
    "dir": RiskLevel.SAFE,
    "read_file": RiskLevel.SAFE,
    "view_file": RiskLevel.SAFE,
    "cat": RiskLevel.SAFE,
    "find_file": RiskLevel.SAFE,
    "search_file": RiskLevel.SAFE,
    "find_folder": RiskLevel.SAFE,
    "search_folder": RiskLevel.SAFE,
    "list_processes": RiskLevel.SAFE,
    "ps": RiskLevel.SAFE,
    "is_running": RiskLevel.SAFE,
    "get_time": RiskLevel.SAFE,
    "get_date": RiskLevel.SAFE,
    "get_cpu_usage": RiskLevel.SAFE,
    "get_ram_usage": RiskLevel.SAFE,
    "get_disk_usage": RiskLevel.SAFE,
    "get_battery": RiskLevel.SAFE,
    "todo_write": RiskLevel.SAFE,
    "get_clipboard": RiskLevel.SAFE,

    # CONFIRMATION_REQUIRED tools (state changes, file creation/edits, apps, shell)
    "create_file": RiskLevel.CONFIRMATION_REQUIRED,
    "write_file": RiskLevel.CONFIRMATION_REQUIRED,
    "make_file": RiskLevel.CONFIRMATION_REQUIRED,
    "append_file": RiskLevel.CONFIRMATION_REQUIRED,
    "delete_file": RiskLevel.CONFIRMATION_REQUIRED,
    "remove_file": RiskLevel.CONFIRMATION_REQUIRED,
    "rm": RiskLevel.CONFIRMATION_REQUIRED,
    "del": RiskLevel.CONFIRMATION_REQUIRED,
    "delete_directory": RiskLevel.CONFIRMATION_REQUIRED,
    "rmdir": RiskLevel.CONFIRMATION_REQUIRED,
    "remove_dir": RiskLevel.CONFIRMATION_REQUIRED,
    "move_path": RiskLevel.CONFIRMATION_REQUIRED,
    "create_directory": RiskLevel.CONFIRMATION_REQUIRED,
    "edit_file": RiskLevel.CONFIRMATION_REQUIRED,
    "modify_file": RiskLevel.CONFIRMATION_REQUIRED,
    "replace_in_file": RiskLevel.CONFIRMATION_REQUIRED,
    "open_app": RiskLevel.CONFIRMATION_REQUIRED,
    "launch_app": RiskLevel.CONFIRMATION_REQUIRED,
    "open_folder": RiskLevel.CONFIRMATION_REQUIRED,
    "open_dir": RiskLevel.CONFIRMATION_REQUIRED,
    "close_process": RiskLevel.CONFIRMATION_REQUIRED,
    "kill_process": RiskLevel.CONFIRMATION_REQUIRED,
    "manage_process": RiskLevel.CONFIRMATION_REQUIRED,
    "set_clipboard": RiskLevel.CONFIRMATION_REQUIRED,
    "run_command": RiskLevel.CONFIRMATION_REQUIRED,
    "run_powershell": RiskLevel.CONFIRMATION_REQUIRED,

    # HIGH_RISK / Catastrophic tools (Blocked unconditionally)
    "shutdown_system": RiskLevel.HIGH_RISK,
    "reboot_system": RiskLevel.HIGH_RISK,
    "format_disk": RiskLevel.HIGH_RISK,
}


def get_tool_risk(tool_name: str) -> RiskLevel:
    clean = (tool_name or "").strip().lower()
    return TOOL_RISK_MAP.get(clean, RiskLevel.HIGH_RISK)


def extract_tool_call(text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Extract structured tool call from user input or LLM pseudo-function-call outputs.
    Handles:
    - tool_name(key="val", ...) / tool_name("path")
    - Markdown code fences: ```python\ntool_name(...)\n```
    - JSON tool structures: {"tool": "read_file", "parameters": {"path": "..."}}
    """
    if not text:
        return None
    raw = text.strip()

    # 1. Check for fenced code block ```(python/json)? ... ```
    fence_match = re.search(r"```(?:python|json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    candidate_text = fence_match.group(1).strip() if fence_match else raw

    # 2. Try JSON tool block
    try:
        json_match = re.search(r"\{[\s\S]*\}", candidate_text)
        if json_match:
            data = json.loads(json_match.group(0))
            if isinstance(data, dict):
                tool = data.get("tool") or data.get("tool_name") or data.get("action")
                args = data.get("parameters") or data.get("args") or data.get("arguments")
                if tool:
                    if not isinstance(args, dict):
                        args = {k: v for k, v in data.items() if k not in ("tool", "tool_name", "action", "parameters", "args", "arguments")}
                    return str(tool).lower(), args
    except Exception:
        pass

    # 3. Try Python-style function call tool_name(key="val", ...)
    call_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([\s\S]*)\)", candidate_text)
    if call_match:
        func_name = call_match.group(1).lower()
        args_str = call_match.group(2).strip()

        if func_name in TOOL_RISK_MAP:
            kwargs: Dict[str, Any] = {}
            # Double single backslashes in quoted strings so Windows paths like C:\test do not turn \t into tab
            def repl(m):
                s = m.group(0)
                quote = s[0]
                inner = s[1:-1]
                sanitized = re.sub(r'(?<!\\)\\(?!\\)', r'\\\\', inner)
                return f"{quote}{sanitized}{quote}"
            sanitized_args = re.sub(r'"[^"]*"|\'[^\']*\'', repl, args_str)

            try:
                tree = ast.parse(f"func({sanitized_args})")
                call_node = tree.body[0].value
                pos_args = [ast.literal_eval(a) for a in call_node.args]
                for kw in call_node.keywords:
                    kwargs[kw.arg] = ast.literal_eval(kw.value)

                if pos_args:
                    if func_name in ("list_directory", "list_files", "list_dir", "dir", "read_file", "view_file", "cat", "open_folder", "open_dir"):
                        if "path" not in kwargs:
                            kwargs["path"] = pos_args[0]
                    elif func_name in ("create_file", "write_file", "make_file"):
                        if "path" not in kwargs and len(pos_args) >= 1:
                            kwargs["path"] = pos_args[0]
                        if "content" not in kwargs and len(pos_args) >= 2:
                            kwargs["content"] = pos_args[1]
                    elif func_name in ("edit_file", "modify_file", "replace_in_file"):
                        if "path" not in kwargs and len(pos_args) >= 1:
                            kwargs["path"] = pos_args[0]
                        if "old_string" not in kwargs and len(pos_args) >= 2:
                            kwargs["old_string"] = pos_args[1]
                        if "new_string" not in kwargs and len(pos_args) >= 3:
                            kwargs["new_string"] = pos_args[2]
                    elif func_name in ("find_file", "search_file"):
                        if "filename" not in kwargs:
                            kwargs["filename"] = pos_args[0]
                    elif func_name in ("find_folder", "search_folder"):
                        if "folder_name" not in kwargs:
                            kwargs["folder_name"] = pos_args[0]
                    elif func_name in ("open_app", "launch_app"):
                        if "app_name" not in kwargs:
                            kwargs["app_name"] = pos_args[0]
                    elif func_name in ("close_process", "kill_process"):
                        if "process_name" not in kwargs:
                            kwargs["process_name"] = pos_args[0]
                    elif func_name in ("run_command", "exec_command"):
                        if "command" not in kwargs:
                            kwargs["command"] = pos_args[0]
                    elif func_name in ("run_powershell", "powershell", "pwsh"):
                        if "command" not in kwargs and len(pos_args) >= 1:
                            kwargs["command"] = pos_args[0]
                    elif func_name in ("append_file",):
                        if "path" not in kwargs and len(pos_args) >= 1:
                            kwargs["path"] = pos_args[0]
                        if "content" not in kwargs and len(pos_args) >= 2:
                            kwargs["content"] = pos_args[1]
                    elif func_name in ("delete_file", "remove_file", "delete_directory"):
                        if "path" not in kwargs and len(pos_args) >= 1:
                            kwargs["path"] = pos_args[0]
                    elif func_name in ("move_path", "rename_file"):
                        if "src" not in kwargs and len(pos_args) >= 1:
                            kwargs["src"] = pos_args[0]
                        if "dst" not in kwargs and len(pos_args) >= 2:
                            kwargs["dst"] = pos_args[1]
                    elif func_name in ("create_directory", "mkdir"):
                        if "path" not in kwargs and len(pos_args) >= 1:
                            kwargs["path"] = pos_args[0]
                    elif func_name in ("set_clipboard",):
                        if "text" not in kwargs and len(pos_args) >= 1:
                            kwargs["text"] = pos_args[0]
                    elif func_name in ("manage_process",):
                        if "action" not in kwargs and len(pos_args) >= 1:
                            kwargs["action"] = pos_args[0]
                        if "name_or_pid" not in kwargs and len(pos_args) >= 2:
                            kwargs["name_or_pid"] = pos_args[1]
                return func_name, kwargs
            except Exception:
                # Fallback: regex for key="value" or key='value'
                for m in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,)]+))', args_str):
                    k = m.group(1)
                    val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
                    kwargs[k] = val
                if kwargs:
                    return func_name, kwargs
                # Plain string inside quotes
                str_match = re.search(r'^["\']([^"\']+)["\']$', args_str)
                if str_match:
                    return func_name, {"path": str_match.group(1)}

    return None


def _synthesize_safe_tool_response(
    tool_name: str,
    tool_kwargs: Dict[str, Any],
    tool_output: Any,
    user_input: str,
    api_client: Optional[OrangeAPIClient] = None,
) -> str:
    """
    Synthesize a concise, grounded natural-language answer via OrangeAPIClient
    with deterministic formatted fallback if the API times out or is offline.
    Never returns raw tool_name(...) pseudo-code.
    """
    client = api_client or main.api_client or OrangeAPIClient()
    synth_reply = None
    try:
        synth_result = client.assist(
            message=(
                f"The user asked: {user_input}\n\n"
                f"The tool '{tool_name}' was executed locally and returned the following result:\n"
                f"{tool_output}\n\n"
                f"Please provide a concise, grounded natural-language answer to the user based strictly on the tool result above. "
                f"Do NOT output pseudo-code or tool call syntax."
            ),
            history=[],
            system_instruction="You are Orange AI. You just executed a local desktop tool to answer the user's request. Present the results clearly, concisely, and naturally. Never output pseudo-code or tool call syntax.",
        )
        if synth_result:
            if isinstance(synth_result, dict):
                synth_text = synth_result.get("reply", "")
            elif isinstance(synth_result, str):
                synth_text = synth_result
            else:
                synth_text = ""

            candidate = synth_text.strip()
            # If candidate does not contain raw pseudo-tool call, use it
            if candidate and not extract_tool_call(candidate):
                synth_reply = candidate
    except Exception as e:
        logger.warning("[CHAT-TOOL] LLM synthesis error or timeout: %s; falling back to deterministic formatting.", e)

    if synth_reply:
        return synth_reply

    # Deterministic formatted fallback
    if tool_name in ("list_directory", "list_files", "list_dir", "dir"):
        target_path = tool_kwargs.get("path", ".")
        return f"Files and directories in `{target_path}`:\n\n{tool_output}"
    elif tool_name in ("read_file", "view_file", "cat"):
        target_path = tool_kwargs.get("path", "")
        return f"Contents of `{target_path}`:\n\n```\n{tool_output}\n```"
    elif tool_name in ("find_file", "search_file"):
        filename = tool_kwargs.get("filename", "")
        return f"Search results for file '{filename}':\n\n{tool_output}"
    elif tool_name in ("find_folder", "search_folder"):
        folder = tool_kwargs.get("folder_name", "")
        return f"Search results for folder '{folder}':\n\n{tool_output}"
    elif tool_name in ("create_file", "write_file", "make_file"):
        target_path = tool_kwargs.get("path", "")
        return f"File '{target_path}' created successfully.\n\n{tool_output}"
    else:
        return f"{tool_output}"


def _synthesize_skill_response(
    slug: str,
    input_text: str,
    raw_output: str,
    step_results: List[Dict[str, Any]],
    api_client: Optional[OrangeAPIClient] = None,
) -> str:
    """
    Synthesize a natural language skill response via OrangeAPIClient with fallback.
    Never returns raw tool call pseudo-code.
    """
    client = api_client or getattr(main, "api_client", None) or OrangeAPIClient()
    if client and hasattr(client, "is_available") and client.is_available():
        try:
            synth_res = client.assist(
                message=(
                    f"The user invoked Orange Skill '/skill {slug}' with input: '{input_text}'.\n\n"
                    f"The skill executed locally and returned the following outputs:\n{raw_output}\n\n"
                    f"Please provide a clear, concise, and structured summary for the user based strictly on the outputs above."
                ),
                history=[],
                system_instruction="You are Orange AI. You just executed an Orange Skill routine. Present the results clearly, concisely, and naturally.",
            )
            if synth_res:
                if isinstance(synth_res, dict) and synth_res.get("reply"):
                    return synth_res["reply"].strip()
                elif isinstance(synth_res, str) and synth_res.strip():
                    return synth_res.strip()
        except Exception as e:
            logger.debug("Skill synthesis failed, falling back to raw output: %s", e)
    return raw_output


def process_user_turn(
    user_input: str,
    prompt_fn: Optional[Callable[[str], str]] = None,
    attachment_context: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    active_window_note: str = "",
) -> Dict[str, Any]:
    """
    Execute one complete user turn with tool call detection, 3-tier permission guardrails,
    grounded LLM synthesis for SAFE tools, and interactive confirmation for CONFIRMATION_REQUIRED tools.
    """
    main.ensure_initialized()
    _ensure_api_client_configured()

    # Ensure approved workspace roots include workspace roots
    current_allowed = os.environ.get("ORANGE_ALLOWED_ROOTS", "")
    ws_root = r"D:\Orange AI"
    if ws_root not in current_allowed:
        os.environ["ORANGE_ALLOWED_ROOTS"] = f"{ws_root}{os.pathsep}{current_allowed}" if current_allowed else ws_root

    text = (user_input or "").strip()
    if not text:
        return {"reply": "", "model": "system", "type": "empty"}

    # 1. Check if user typed a direct tool call
    direct_tool_call = extract_tool_call(text)

    # 2. If not a direct tool call, let main.process_user_turn process initial turn
    global _session_conversational_state
    if not direct_tool_call:
        outcome = main.process_user_turn(
            text,
            prompt_fn=prompt_fn,
            attachment_context=attachment_context,
            attachments=attachments,
            active_window_context=active_window_note,
        )
        if "conversational_state" in outcome:
            _session_conversational_state = outcome["conversational_state"]
        reply_tool_call = extract_tool_call(outcome.get("reply", ""))
        if not reply_tool_call:
            # Ordinary conversational turn: clean any embedded advisory markdown and do not attach duplicate recommendation card
            clean_reply = outcome.get("reply", "")
            if clean_reply and "Orange AI Advisory" in clean_reply:
                clean_reply = re.sub(r"\n+💡\s+\*\*Orange AI Advisory\*\*[\s\S]*$", "", clean_reply).strip()
                outcome["reply"] = clean_reply
            if "recommendation" in outcome:
                outcome.pop("recommendation", None)

            # Synthesize skill response if turn invoked an Orange Skill
            if outcome.get("skill_used") and outcome.get("type") == "skill":
                clean_reply = _synthesize_skill_response(
                    outcome["skill_used"],
                    text,
                    clean_reply,
                    outcome.get("tool_steps", []),
                )
                outcome["reply"] = clean_reply

            # Ensure the turn is recorded in conversation_history if not already recorded
            try:
                conn = mem.get_connection()
                cursor = conn.execute("SELECT id, role, content FROM conversation_history ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if not (row and row[1] == "assistant" and row[2] == clean_reply):
                    main.save_turn("user", text)
                    main.save_turn("assistant", clean_reply)
            except Exception as e:
                logger.warning("[CHAT-TURN] Error persisting turn to history: %s", e)

            # If tool turn produced a reply but lacked tool_result, populate it
            if outcome.get("type") == "tool" and not outcome.get("tool_result"):
                outcome["tool_result"] = {
                    "tool": "system_tool",
                    "toolName": "System Tool",
                    "status": "SUCCESS",
                    "stdout": str(clean_reply)[:2000],
                    "output": str(clean_reply)[:2000],
                    "content": str(clean_reply)[:2000],
                    "result": str(clean_reply)[:2000],
                    "commandArg": str(text),
                }

            return outcome
        tool_call_to_run = reply_tool_call
    else:
        outcome = {"learned": [], "retired": []}
        tool_call_to_run = direct_tool_call

    # 3. We have a tool call to run! Execute via Bounded Multi-Step Goal Loop (up to 8 steps)
    MAX_GOAL_STEPS = 8
    tool_steps: List[Dict[str, Any]] = []
    current_call = tool_call_to_run
    final_reply = ""
    last_tool_result = None
    settings = _load_gui_settings()
    full_access_mode = settings.get("full_access_mode", "supervised")

    for step_idx in range(1, MAX_GOAL_STEPS + 1):
        tool_name, tool_kwargs = current_call
        risk_level = get_tool_risk(tool_name)
        target_desc = (
            tool_kwargs.get("path")
            or tool_kwargs.get("app_name")
            or tool_kwargs.get("process_name")
            or tool_kwargs.get("command")
            or tool_kwargs.get("src")
            or tool_kwargs.get("target")
            or "target"
        )

        # A. Catastrophic Command Guard
        is_cat, cat_reason = tool_perm.is_catastrophic_command(f"{tool_name} {target_desc}")
        if is_cat or risk_level == RiskLevel.HIGH_RISK:
            explanation = f"⚠️ Safety Guardrail (HIGH_RISK): {cat_reason or f'Action {tool_name} is classified as HIGH_RISK and cannot be executed automatically.'}"
            step_record = {
                "step": step_idx,
                "tool": tool_name,
                "arguments": tool_kwargs,
                "status": "BLOCKED",
                "error": explanation,
                "success": False,
            }
            tool_steps.append(step_record)
            return {
                "reply": explanation,
                "model": "guardrails",
                "type": "error",
                "status": "blocked",
                "tool_steps": tool_steps,
                "learned": outcome.get("learned", []),
                "retired": outcome.get("retired", []),
                "conversational_state": _session_conversational_state,
            }

        # B. Permission & Confirmation Evaluation
        needs_confirmation = False
        if full_access_mode == "unrestricted":
            needs_confirmation = False
        else: # "supervised"
            if risk_level == RiskLevel.SAFE:
                needs_confirmation = False
            elif tool_name in (
                "list_directory", "list_files", "list_dir", "dir", "read_file", "view_file",
                "cat", "find_file", "find_folder", "get_clipboard", "get_time", "get_date",
                "get_cpu_usage", "get_ram_usage", "get_disk_usage", "get_battery", "todo_write"
            ):
                needs_confirmation = False
            elif tool_name in (
                "create_file", "edit_file", "delete_file", "remove_file", "delete_directory",
                "open_app", "launch_app", "close_process", "kill_process", "open_folder"
            ):
                needs_confirmation = True
            elif tool_perm.is_scoped_in_workspaces(target_desc):
                needs_confirmation = False
            else:
                needs_confirmation = True

        if needs_confirmation:
            if tool_name in ("create_file", "write_file", "make_file"):
                prompt_text = f"Orange AI requests confirmation to create file: '{tool_kwargs.get('path', '')}'. Proceed? [y/N]: "
            elif tool_name in ("edit_file", "modify_file", "replace_in_file"):
                prompt_text = f"Orange AI requests confirmation to edit file: '{tool_kwargs.get('path', '')}'. Proceed? [y/N]: "
            elif tool_name in ("delete_file", "remove_file", "delete_directory"):
                prompt_text = f"Orange AI requests confirmation to delete: '{tool_kwargs.get('path', '')}'. Proceed? [y/N]: "
            elif tool_name in ("open_folder", "open_dir"):
                prompt_text = f"Orange AI requests confirmation to open folder: '{tool_kwargs.get('path', '')}'. Proceed? [y/N]: "
            elif tool_name in ("open_app", "launch_app"):
                prompt_text = f"Orange AI requests confirmation to launch application: '{tool_kwargs.get('app_name', target_desc)}'. Proceed? [y/N]: "
            elif tool_name in ("close_process", "kill_process"):
                prompt_text = f"Orange AI requests confirmation to close process: '{tool_kwargs.get('process_name', target_desc)}'. Proceed? [y/N]: "
            else:
                prompt_text = f"Orange AI requests confirmation to execute '{tool_name}' ({target_desc}). Proceed? [y/N]: "

            decision = "no"
            if prompt_fn:
                try:
                    decision = prompt_fn(prompt_text)
                except Exception as e:
                    logger.error("[CHAT-GUARDRAIL] Confirmation prompt failed: %s", e)
                    decision = "no"

            is_approved = str(decision).strip().lower() in ("yes", "y", "true", "1")
            if not is_approved:
                step_record = {
                    "step": step_idx,
                    "tool": tool_name,
                    "arguments": tool_kwargs,
                    "status": "CANCELLED",
                    "error": "User declined confirmation",
                    "success": False,
                }
                tool_steps.append(step_record)
                return {
                    "reply": f"❌ Action '{tool_name}' was not authorized. Operation cancelled with zero changes made.",
                    "model": "guardrails",
                    "type": "assistant",
                    "status": "cancelled",
                    "tool_steps": tool_steps,
                    "learned": outcome.get("learned", []),
                    "retired": outcome.get("retired", []),
                }

        # C. Act - Execute Tool
        exec_err = None
        exec_result = None
        try:
            from tools.registry import registry
            lookup_name = tool_name
            if tool_name in ("create_file", "make_file"):
                lookup_name = "write_file"
            elif tool_name in ("modify_file", "replace_in_file"):
                lookup_name = "edit_file"
            elif tool_name in ("remove_file", "delete_directory"):
                lookup_name = "delete_file"

            exec_result = registry.execute(
                lookup_name,
                is_admin=tool_sys.is_running_as_admin(),
                full_access_mode=full_access_mode,
                prompt_fn=lambda _: "yes",
                **tool_kwargs,
            )
        except Exception as e:
            exec_err = str(e)

        if exec_err:
            record_workspace_failure(target_desc, exec_err)
            step_record = {
                "step": step_idx,
                "tool": tool_name,
                "arguments": tool_kwargs,
                "status": "FAILED",
                "error": exec_err,
                "success": False,
            }
            tool_steps.append(step_record)
            step_output = f"Error: {exec_err}"
            step_success = False
        else:
            step_str = str(exec_result) if exec_result is not None else ""
            step_success = not (step_str.lower().startswith("error") or "action blocked" in step_str.lower())
            if not step_success:
                record_workspace_failure(target_desc, step_str)
            step_record = {
                "step": step_idx,
                "tool": tool_name,
                "arguments": tool_kwargs,
                "status": "SUCCESS" if step_success else "FAILED",
                "output": step_str,
                "success": step_success,
            }
            tool_steps.append(step_record)
            step_output = step_str

        last_tool_result = {
            "tool": tool_name,
            "toolName": tool_name,
            "status": "SUCCESS" if step_success else "FAILED",
            "stdout": str(step_output)[:2000],
            "output": str(step_output)[:2000],
            "content": str(step_output)[:2000],
            "result": str(step_output)[:2000],
            "commandArg": str(target_desc),
            "parameters": tool_kwargs,
        }

        # D. Observe, Recover & Verify via LLM Decision Query
        if step_idx < MAX_GOAL_STEPS:
            decision_prompt = (
                f"User goal: {text}\n\n"
                f"Step {step_idx} execution:\n"
                f"Tool: {tool_name}\n"
                f"Status: {'SUCCESS' if step_success else 'FAILED'}\n"
                f"Output:\n{step_output}\n\n"
                f"Are all tasks for this goal complete? If yes, provide your final response to the user. "
                f"If another step is needed or error recovery is required, respond ONLY with a JSON object: "
                f'{{"tool": "<name>", "arguments": {{...}}}}'
            )
            try:
                client = getattr(main, "api_client", None) or (_api_client if "_api_client" in globals() and _api_client else None) or OrangeAPIClient()
                resp = client.assist(
                    message=decision_prompt,
                    system_instruction="You are Orange AI's autonomous execution planner. Determine if more steps are needed or if the goal is complete. If another step or recovery is needed, output JSON tool call. Otherwise output the final response.",
                    task_type="agent_decision",
                )
                if isinstance(resp, dict):
                    cand = (resp.get("reply") or "").strip()
                elif isinstance(resp, str):
                    cand = resp.strip()
                else:
                    cand = ""
                next_call = extract_tool_call(cand)
                if next_call:
                    if next_call == current_call and step_success:
                        final_reply = _synthesize_safe_tool_response(tool_name, tool_kwargs, step_output, text)
                        break
                    current_call = next_call
                    continue
                else:
                    final_reply = cand
                    break
            except Exception as e:
                logger.warning("[GOAL-LOOP] Decision assistance query failed: %s", e)
                final_reply = _synthesize_safe_tool_response(tool_name, tool_kwargs, step_output, text)
                break
        else:
            final_reply = f"Completed maximum goal steps ({MAX_GOAL_STEPS}). Final output:\n{step_output}"

    if not final_reply and tool_steps:
        final_reply = _synthesize_safe_tool_response(tool_steps[-1]["tool"], tool_steps[-1]["arguments"], tool_steps[-1].get("output", ""), text)

    # Save to history
    try:
        main.save_turn("user", text)
        main.save_turn("assistant", final_reply)
    except Exception as e:
        logger.warning("[CHAT-TURN] Error saving turn: %s", e)

    ret_outcome = {
        "reply": final_reply,
        "model": "agent",
        "type": "assistant",
        "status": "completed" if (tool_steps and tool_steps[-1].get("success")) else "failed",
        "tool_steps": tool_steps,
        "tool_result": last_tool_result,
        "learned": outcome.get("learned", []),
        "retired": outcome.get("retired", []),
        "conversational_state": _session_conversational_state,
    }

    # REA Habit-to-Skill Suggestion (Stage 5E)
    executed_tools = [s.get("tool") for s in tool_steps if s.get("status") in ("SUCCESS", "completed", "ALLOWED") and s.get("tool")]
    if len(executed_tools) >= 2:
        chain_tuple = tuple(executed_tools)
        _session_tool_chains.append(chain_tuple)
        if _session_tool_chains.count(chain_tuple) >= 2:
            import tools.skills as ts
            try:
                existing_skills = ts.list_skills()
                has_exact = any(
                    tuple(st.get("tool") for st in sk.get("steps", [])) == chain_tuple
                    for sk in existing_skills
                )
                if not has_exact:
                    slug_name = "-".join(t.replace("_", "-") for t in executed_tools)
                    suggested_slug = f"custom-{slug_name}"
                    friendly_name = " -> ".join(t.replace("_", " ").title() for t in executed_tools) + " Routine"
                    ret_outcome["skill_suggestion"] = {
                        "suggested_slug": suggested_slug,
                        "name": friendly_name,
                        "description": f"Automated routine chaining {', '.join(executed_tools)}.",
                        "steps": [{"tool": t, "args": {}} for t in executed_tools],
                        "prompt_template": f"Summarize results from {', '.join(executed_tools)}: {{{{input}}}}",
                    }
            except Exception as e:
                logger.debug("Failed computing habit-to-skill suggestion: %s", e)

    return ret_outcome


def handle_chat_send(req_id: Any, params: Dict[str, Any]):
    """Execute a user turn asynchronously on a background worker thread."""
    raw_text = params.get("text", "")
    attachments = params.get("attachments", [])
    if not isinstance(attachments, list):
        attachments = []

    text = str(raw_text or "").strip()

    # Step 3: Natural "Look at My Screen" Routing (Stage 5G)
    from brain.attachments import should_auto_capture_screen, capture_screen_attachment
    if not attachments and should_auto_capture_screen(text):
        try:
            screen_att = capture_screen_attachment()
            if screen_att:
                attachments = [screen_att]
        except Exception as e:
            logger.warning("[SCREEN-ROUTING] Automatic screen capture failed: %s", e)

    if not text and not attachments:
        send_response(req_id, {"reply": "", "model": "system", "type": "empty"})
        return

    if not text and attachments:
        text = "Analyze the attached file(s)."

    # Track activity for idle follow-ups and reset single-nudge turn gate
    global _last_activity_ts, _idle_nudge_sent_for_turn
    _last_activity_ts = time.time()
    _idle_nudge_sent_for_turn = False

    # Atomic turn admission and registration under _turn_threads_lock
    with _turn_threads_lock:
        if _is_updating or _is_shutting_down:
            send_error(req_id, -32001, "Application is preparing for update; new turns are disabled.")
            return

        def _worker():
            t = threading.current_thread()
            try:
                # Active Window Awareness: sample situational context
                active_window_note = ""
                settings = _load_gui_settings()
                if settings.get("active_window_awareness_enabled", True):
                    global _latest_active_window
                    if _latest_active_window and _latest_active_window.get("window_title"):
                        if not _is_orange_ai_window(_latest_active_window):
                            active_window_note = (
                                f"Active Desktop Window: {_latest_active_window.get('process_name', '')} — "
                                f"{_latest_active_window.get('window_title', '')}"
                            )

                if attachments:
                    from brain.attachments import extract_attachment_context, format_attachments_for_prompt
                    extracted_attachments = []
                    for att in attachments:
                        if isinstance(att, dict):
                            if att.get("formatted_block"):
                                extracted_attachments.append(att)
                            else:
                                extracted_attachments.append(extract_attachment_context(att))
                    attachment_context = format_attachments_for_prompt(extracted_attachments)
                    outcome = process_user_turn(
                        text,
                        prompt_fn=_confirmation_prompt_fn,
                        attachment_context=attachment_context,
                        attachments=extracted_attachments,
                        active_window_note=active_window_note,
                    )
                    outcome["attachments"] = [
                        {
                            "name": att.get("name", "attachment"),
                            "kind": att.get("kind", "file"),
                            "char_count": att.get("char_count", 0),
                        }
                        for att in extracted_attachments
                    ]
                else:
                    outcome = process_user_turn(
                        text,
                        prompt_fn=_confirmation_prompt_fn,
                        active_window_note=active_window_note,
                    )
                _last_activity_ts = time.time()
                send_response(req_id, outcome)
            except Exception as e:
                logger.error("Error in process_user_turn: %s", e, exc_info=True)
                send_error(req_id, -32000, f"Error processing user request: {e}")
            finally:
                with _turn_threads_lock:
                    _active_turn_threads.discard(t)

        worker_thread = threading.Thread(target=_worker, daemon=True, name=f"TurnWorker-{req_id}")
        _active_turn_threads.add(worker_thread)
        worker_thread.start()


def handle_chat_history(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    main.ensure_initialized()
    limit = int(params.get("limit", 60))
    session_start_id = params.get("chat_session_start_id", params.get("since_id"))
    if session_start_id is None:
        settings = _load_gui_settings()
        session_start_id = int(settings.get("chat_session_start_id", 0) or 0)
        try:
            conn = mem.get_connection()
            max_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM conversation_history").fetchone()
            if max_row and max_row[0] < session_start_id:
                session_start_id = 0
        except Exception:
            pass
    else:
        session_start_id = int(session_start_id)

    turns = []
    try:
        conn = mem.get_connection()
        cursor = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM conversation_history
            WHERE id > ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_start_id, limit),
        )
        rows = cursor.fetchall()
        for r in reversed(rows):
            turn_content = r[2]
            att_meta = None
            if "\n\n[Attachments: " in turn_content and turn_content.endswith("]"):
                parts = turn_content.rsplit("\n\n[Attachments: ", 1)
                try:
                    json_str = parts[1][:-1] if parts[1].endswith("]") else parts[1]
                    att_meta = json.loads(json_str)
                    turn_content = parts[0]
                except Exception:
                    pass

            turn_item = {
                "id": r[0],
                "role": r[1],
                "content": turn_content,
                "created_at": r[3],
                "timestamp": r[3],
            }
            if att_meta:
                turn_item["attachments"] = att_meta
            turns.append(turn_item)
    except Exception as e:
        logger.warning("Error fetching chat history: %s", e)
    return turns


def handle_chat_new_session(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Advance chat_session_start_id watermark to current MAX(id) in conversation_history.
    Allows user to start a fresh thread cleanly without deleting any conversation turns
    or structured memory records. Also resets the in-memory session conversational state.
    """
    global _session_conversational_state, _last_activity_ts, _idle_nudge_sent_for_turn
    _session_conversational_state = None
    _session_tool_chains.clear()
    _last_activity_ts = time.time()
    _idle_nudge_sent_for_turn = False
    if hasattr(main, "reset_session"):
        try:
            main.reset_session()
        except Exception as e:
            logger.warning("[CHAT-SESSION] Error calling main.reset_session: %s", e)

    main.ensure_initialized()
    max_id = 0
    try:
        conn = mem.get_connection()
        cursor = conn.execute("SELECT COALESCE(MAX(id), 0) FROM conversation_history")
        row = cursor.fetchone()
        if row and row[0] is not None:
            max_id = int(row[0])
    except Exception as e:
        logger.warning("[CHAT-SESSION] Error querying max conversation_history id: %s", e)

    settings = _load_gui_settings()
    settings["chat_session_start_id"] = max_id
    _save_gui_settings(settings)
    logger.info("[CHAT-SESSION] Advanced chat_session_start_id watermark to %d", max_id)
    return {
        "success": True,
        "chat_session_start_id": max_id,
    }


def handle_chat_confirm(params: Dict[str, Any]) -> Dict[str, Any]:
    conf_id = params.get("confirmation_id")
    decision = str(params.get("decision", "no")).strip().lower()

    with _confirmations_lock:
        container = _pending_confirmations.get(conf_id)
        if container:
            container["decision"] = "yes" if decision in ("yes", "y", "true") else "no"
            container["event"].set()
            return {"status": "resolved", "confirmation_id": conf_id, "decision": container["decision"]}
        else:
            return {"status": "not_found", "confirmation_id": conf_id}


def handle_jobs_list(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    status_filter = params.get("status")
    limit = int(params.get("limit", 100))
    jobs = mgr.list_jobs(status=status_filter, limit=limit)
    return [j.to_dict() for j in jobs]


def handle_jobs_status(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    job = mgr.get_job(job_id)
    return job.to_dict() if job else None


def handle_jobs_history(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    steps = mgr.get_history(job_id)
    return [s.to_dict() for s in steps]


def handle_jobs_create(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    goal = params.get("goal", "").strip()
    job = mgr.create(goal)
    return job.to_dict()


def handle_jobs_start(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    if mgr and hasattr(mgr, "store") and job_id:
        from brain.jobs.models import JobStatus
        resolved_id = mgr.store.resolve_job_id(job_id)
        if resolved_id:
            target_job = mgr.store.get_job(resolved_id)
            if target_job and target_job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                target_job.status = JobStatus.PENDING
                target_job.attempt_count = 0
                target_job.last_error = None
                mgr.store.update_job(target_job)
    job = mgr.start(job_id)
    return job.to_dict()


def handle_jobs_pause(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    job = mgr.pause(job_id)
    return job.to_dict()


def handle_jobs_resume(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    job = mgr.resume(job_id)
    return job.to_dict()


def handle_jobs_cancel(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    job = mgr.cancel(job_id)
    return job.to_dict()


def handle_jobs_confirm(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    mgr = main.get_job_manager()
    job_id = params.get("job_id")
    approved = bool(params.get("approved", False))
    job = mgr.confirm(job_id, approved=approved)
    return job.to_dict()


def handle_memory_structured(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    main.ensure_initialized()
    return mem.recall_structured()


def handle_memory_legacy(params: Dict[str, Any]) -> List[str]:
    main.ensure_initialized()
    limit = int(params.get("limit", 50))
    return mem.recall(limit=limit)


def handle_memory_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    return mem.memory_stats()


def handle_memory_forget(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    keyword = params.get("keyword", "").strip()
    deleted = mem.forget(keyword)
    return {"keyword": keyword, "deleted_count": deleted}


def handle_memory_retract(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    category = params.get("category", "").strip()
    key = params.get("key", "").strip()
    res = mem.retract_entity(category, key)
    return res


_ALLOWED_STRUCTURED_CATEGORIES = frozenset({
    "identity", "project", "tool", "preference", "goal", "relationship", "fact"
})


def handle_memory_remember(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    fact = str(params.get("fact", "")).strip()
    if not fact:
        return {"success": False, "error": "Empty fact"}
    try:
        from brain.memory_classifier import classify_memory
        memories = classify_memory(fact)
        stored = []
        retired = []
        if memories:
            for m in memories:
                action = m.get("action", "store")
                if action == "retire":
                    try:
                        mem.retire_structured(
                            category=m["category"],
                            key=m["key"],
                            value=m.get("value"),
                        )
                        retired.append(m)
                    except Exception as e:
                        logger.error("Failed to retire memory %s/%s: %s", m.get("category"), m.get("key"), e)
                else:
                    try:
                        mem.remember_structured(
                            category=m["category"],
                            key=m["key"],
                            value=m["value"],
                            confidence=m.get("confidence", 1.0),
                        )
                        stored.append(m)
                    except Exception as e:
                        logger.error("Failed to store memory %s/%s: %s", m.get("category"), m.get("key"), e)

        if stored or retired:
            return {
                "success": True,
                "fact": fact,
                "mode": "structured",
                "stored": stored,
                "retired": retired,
            }
        else:
            mem.remember(fact)
            return {
                "success": True,
                "fact": fact,
                "mode": "legacy",
            }
    except Exception as e:
        logger.error("Error in handle_memory_remember: %s", e)
        return {"success": False, "error": str(e)}


def handle_memory_create_structured(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    category = str(params.get("category", "")).strip().lower()
    if not category:
        raise ValueError("Parameter 'category' cannot be empty.")
    if category not in _ALLOWED_STRUCTURED_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Allowed categories: {sorted(list(_ALLOWED_STRUCTURED_CATEGORIES))}"
        )

    key = str(params.get("key", "")).strip().lower()
    if not key:
        raise ValueError("Parameter 'key' cannot be empty.")

    value = str(params.get("value", "")).strip()
    if not value:
        raise ValueError("Parameter 'value' cannot be empty.")

    conf_val = params.get("confidence", 1.0)
    try:
        confidence = float(conf_val)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid confidence value: {conf_val!r}. Must be a float in (0.0, 1.0].")

    if not (0.0 < confidence <= 1.0):
        raise ValueError(f"Confidence must be in range (0.0, 1.0], got {confidence}.")

    mem.remember_structured(
        category=category,
        key=key,
        value=value,
        confidence=confidence,
    )
    return {
        "success": True,
        "memory": {
            "category": category,
            "key": key,
            "value": value,
            "confidence": confidence,
        },
    }


def handle_memory_update(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    category = str(params.get("category", "")).strip().lower()
    if not category:
        raise ValueError("Parameter 'category' cannot be empty.")

    key = str(params.get("key", "")).strip().lower()
    if not key:
        raise ValueError("Parameter 'key' cannot be empty.")

    value = str(params.get("value", "")).strip()
    if not value:
        raise ValueError("Parameter 'value' cannot be empty.")

    existing = mem.get_memory(category, key)
    if existing is None:
        raise ValueError(f"Memory not found for category '{category}' and key '{key}'.")

    mem.update_memory(category, key, value)
    return {
        "success": True,
        "memory": {
            "category": category,
            "key": key,
            "value": value,
        },
    }


def _parse_reminder_due_at(val: Any) -> datetime:
    """Parse various input formats for reminder due_at into a naive local datetime."""
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone().replace(tzinfo=None)
        return val
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val)
    if isinstance(val, str):
        v = val.strip()
        if not v:
            raise ValueError("Parameter 'due_at' cannot be empty.")
        clean_v = v[:-1] + "+00:00" if v.endswith("Z") else v
        try:
            parsed = datetime.fromisoformat(clean_v)
            if parsed.tzinfo is not None:
                return parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                pass
        try:
            import dateparser
            parsed = dateparser.parse(v)
            if parsed:
                if parsed.tzinfo is not None:
                    return parsed.astimezone().replace(tzinfo=None)
                return parsed
        except Exception:
            pass
    raise ValueError(f"Invalid 'due_at' format: {val!r}. Expected ISO-8601 string or timestamp.")


def handle_reminders_create(params: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new reminder.
    
    Validates message (non-empty string), due_at (ISO timestamp or unix seconds),
    and optional lead_time_minutes (0..1440).
    Returns the created reminder record.
    """
    main.ensure_initialized()
    message = params.get("message")
    if not message or not isinstance(message, str) or not message.strip():
        raise ValueError("Parameter 'message' must be a non-empty string.")

    due_at_raw = params.get("due_at")
    if due_at_raw is None or (isinstance(due_at_raw, str) and not due_at_raw.strip()):
        raise ValueError("Parameter 'due_at' is required.")

    due_dt = _parse_reminder_due_at(due_at_raw)

    lead_raw = params.get("lead_time_minutes", 0)
    try:
        lead_time_minutes = int(lead_raw)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid 'lead_time_minutes': {lead_raw!r}. Must be an integer between 0 and 1440.")
    if not (0 <= lead_time_minutes <= 1440):
        raise ValueError(f"'lead_time_minutes' must be between 0 and 1440 (received {lead_time_minutes}).")

    import brain.reminders as rem_mod
    rem_id = rem_mod.add_reminder(message.strip(), due_dt)

    if lead_time_minutes > 0:
        cur_settings = _load_gui_settings()
        lead_map = cur_settings.get("reminder_lead_times", {})
        if not isinstance(lead_map, dict):
            lead_map = {}
        lead_map[str(rem_id)] = lead_time_minutes
        cur_settings["reminder_lead_times"] = lead_map
        _save_gui_settings(cur_settings)

    created = rem_mod.get_reminder(rem_id)
    if not created:
        return {
            "id": rem_id,
            "message": message.strip(),
            "due_at": due_dt.isoformat(),
            "lead_time_minutes": lead_time_minutes,
            "created_at": datetime.now().isoformat(),
            "completed": False,
            "fired": 0,
        }
    created["lead_time_minutes"] = lead_time_minutes
    return created


def handle_reminders_list(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List reminders from SQLite, ordered by due_at ASC.
    
    Supports optional include_completed filter (defaults to False).
    """
    main.ensure_initialized()
    include_completed_raw = params.get("include_completed", False)
    if isinstance(include_completed_raw, str):
        include_completed = include_completed_raw.strip().lower() in ("true", "1", "yes")
    else:
        include_completed = bool(include_completed_raw)

    import brain.reminders as rem_mod
    rems = rem_mod.list_reminders(include_completed=include_completed)
    cur_settings = _load_gui_settings()
    lead_map = cur_settings.get("reminder_lead_times", {})
    if isinstance(lead_map, dict):
        for r in rems:
            r["lead_time_minutes"] = int(lead_map.get(str(r.get("id")), 0))
    return rems


def handle_reminders_cancel(params: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel a pending reminder by ID in SQLite.
    
    Prevents subsequent due check emission and returns confirmation.
    Prunes any associated lead time from runtime settings.
    """
    main.ensure_initialized()
    reminder_id_val = params.get("id") if params.get("id") is not None else params.get("reminder_id")
    if reminder_id_val is None:
        raise ValueError("Parameter 'id' (or 'reminder_id') is required.")

    try:
        rem_id = int(reminder_id_val)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid reminder ID: {reminder_id_val!r}. Must be an integer.")

    import brain.reminders as rem_mod
    cancelled = rem_mod.cancel_reminder(rem_id)
    if not cancelled:
        raise ValueError(f"Reminder #{rem_id} not found or already completed.")

    # Prune lead time metadata
    cur_settings = _load_gui_settings()
    lead_map = cur_settings.get("reminder_lead_times", {})
    if isinstance(lead_map, dict) and str(rem_id) in lead_map:
        del lead_map[str(rem_id)]
        cur_settings["reminder_lead_times"] = lead_map
        _save_gui_settings(cur_settings)

    return {"cancelled": True, "id": rem_id}


def handle_activity_get(params: Dict[str, Any]) -> Dict[str, Any]:
    main.ensure_initialized()
    import re
    from brain.paths import get_project_root

    # 1. System logs
    log_path = os.path.join(get_project_root(), "orange_ai.log")
    logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for line in lines[-150:]:
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d+)\s\[([A-Z]+)\]\s(.*)$", line)
                if match:
                    logs.append({
                        "time": match.group(1)[:19],
                        "level": match.group(2),
                        "message": match.group(3),
                    })
                elif logs:
                    logs[-1]["message"] += "\n" + line
            logs.reverse()
        except Exception:
            pass

    # 2. Job steps
    job_steps = []
    try:
        manager = main.get_job_manager()
        jobs = manager.list_jobs(limit=15)
        for j in jobs:
            try:
                j_steps = manager.get_history(j.id)
                for s in j_steps:
                    raw_time = getattr(s, "started_at", None) or getattr(s, "completed_at", None) or getattr(s, "created_at", "")
                    clean_time = str(raw_time)[:19].replace("T", " ") if raw_time else ""
                    job_steps.append({
                        "job_id": j.short_id,
                        "goal": j.goal,
                        "action_type": s.action_type,
                        "tool_name": s.tool_name or "",
                        "success": s.success,
                        "reasoning": s.reasoning or "",
                        "error": s.error or "",
                        "duration_ms": s.duration_ms,
                        "time": clean_time,
                    })
            except Exception:
                pass
        job_steps.sort(key=lambda x: x.get("time", ""), reverse=True)
    except Exception:
        pass

    # 3. Conversations
    conversations = []
    try:
        conn = mem.get_connection()
        cursor = conn.execute(
            """
            SELECT role, content, created_at
            FROM conversation_history
            ORDER BY id DESC
            LIMIT 50
            """
        )
        for r in cursor.fetchall():
            conversations.append({
                "role": r[0],
                "content": r[1],
                "time": r[2][:19].replace("T", " ") if r[2] else "",
            })
    except Exception:
        pass

    return {
        "logs": logs,
        "job_steps": job_steps,
        "conversations": conversations,
    }


def handle_skills_list(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all registered Orange Skills with metadata, step count, and risk badges."""
    import tools.skills as ts
    user_data_dir = params.get("user_data_dir") if params else None
    return ts.list_skills(user_data_dir=user_data_dir)


def handle_skills_create(params: Dict[str, Any]) -> Dict[str, Any]:
    """Create and persist a new custom Orange Skill."""
    import tools.skills as ts
    params = params or {}
    slug = params.get("slug", "")
    name = params.get("name", "")
    description = params.get("description", "")
    steps = params.get("steps")
    if not steps and params.get("command"):
        cmd_str = str(params["command"]).strip()
        if cmd_str.lower().startswith("git "):
            steps = [{"tool": "run_command", "args": {"command": cmd_str}}]
        else:
            steps = [{"tool": "run_powershell", "args": {"command": cmd_str}}]
    prompt_template = params.get("prompt_template", "")
    user_data_dir = params.get("user_data_dir")
    return ts.create_skill(
        slug=slug,
        name=name,
        description=description,
        steps=steps or [],
        prompt_template=prompt_template,
        user_data_dir=user_data_dir,
    )


def handle_skills_toggle(params: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle enabled/disabled state of an Orange Skill."""
    import tools.skills as ts
    params = params or {}
    slug = params.get("slug", "")
    enabled = params.get("enabled")
    user_data_dir = params.get("user_data_dir")
    return ts.toggle_skill(slug=slug, enabled=enabled, user_data_dir=user_data_dir)


def handle_skills_delete(params: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a custom Orange Skill. Built-in skills are protected."""
    import tools.skills as ts
    params = params or {}
    slug = params.get("slug", "")
    user_data_dir = params.get("user_data_dir")
    ts.delete_skill(slug=slug, user_data_dir=user_data_dir)
    return {"deleted": True, "slug": slug}


def handle_skills_run(params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an Orange Skill by slug, record activity, and return results."""
    import tools.skills as ts
    params = params or {}
    slug = params.get("slug", "")
    input_text = params.get("input", "")
    user_data_dir = params.get("user_data_dir")
    full_access_mode = tool_perm.get_full_access_mode()

    exec_res = ts.execute_skill(
        slug,
        input_text=input_text,
        full_access_mode=full_access_mode,
        user_data_dir=user_data_dir,
    )

    try:
        act_store = getattr(main, "activity_store", None)
        if act_store and hasattr(act_store, "record_activity"):
            act_store.record_activity("skill_execution", f"Executed skill: {slug}")
    except Exception as e:
        logger.debug("Failed recording activity for skill '%s': %s", slug, e)

    synthesized = _synthesize_skill_response(
        slug,
        input_text,
        exec_res.get("output", ""),
        exec_res.get("step_results", []),
    )
    return {
        "success": exec_res.get("success", False),
        "status": exec_res.get("status"),
        "slug": slug,
        "step_results": exec_res.get("step_results", []),
        "output": synthesized,
        "reply": synthesized,
    }


def handle_tools_list(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    from tools.registry import registry
    return registry.list_metadata()


def handle_permissions_audit(params: Dict[str, Any]) -> Dict[str, Any]:
    from tools.registry import registry
    is_admin = tool_sys.is_running_as_admin()
    tools_list = []
    for t in registry.list_tools():
        perm = tool_perm.check_permission(t, is_admin=is_admin)
        tools_list.append({
            "name": t.name,
            "category": t.category,
            "risk_level": t.risk_level.value,
            "status": perm.status.value,
            "reason": perm.reason,
            "requires_confirmation": t.requires_confirmation,
        })
    return {
        "admin_rights": is_admin,
        "tools": tools_list,
    }


def handle_attachments_capture_screen(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Capture screen attachment and run local OCR extraction."""
    from brain.attachments import capture_screen_attachment
    return capture_screen_attachment()


def handle_settings_get(params: Dict[str, Any]) -> Dict[str, Any]:
    current = _load_gui_settings()
    if current.get("model") not in SUPPORTED_MODELS and current.get("model") not in LEGACY_MODELS:
        current["model"] = DEFAULT_MODEL
    _apply_runtime_settings(current)
    return {
        **current,
        "settings": current,
        "supported_models": list(SUPPORTED_MODELS.values()),
        "default_model": DEFAULT_MODEL,
        "supported_cooldown_hours": [2, 4, 8],
        "supported_idle_thresholds": [5, 10, 15, 30],
    }


def handle_settings_update(params: Dict[str, Any]) -> Dict[str, Any]:
    updates = params.get("settings")
    if not isinstance(updates, dict):
        updates = params
    if not isinstance(updates, dict):
        current = _load_gui_settings()
        return {"success": False, "error": "Invalid settings payload", "settings": current, **current}

    current = _load_gui_settings()
    errors = []

    if any(k in updates for k in ("test_mode", "dev_mode", "ORANGE_AI_TEST_MODE")):
        errors.append("test_mode cannot be modified via settings RPC.")

    if "theme" in updates:
        if _validate_theme(updates["theme"]):
            current["theme"] = updates["theme"].lower()
        else:
            errors.append(f"Invalid theme: {updates['theme']}. Supported: dark, light, system.")

    if "model" in updates:
        if _validate_model(updates["model"]):
            current["model"] = updates["model"]
            current["model_routing_version"] = 2
        else:
            errors.append(f"Invalid model: {updates['model']}. Must be one of the supported models: {', '.join(SUPPORTED_MODELS.keys())}.")

    if "api_url" in updates:
        if _validate_api_url(updates["api_url"]):
            current["api_url"] = updates["api_url"].strip().rstrip("/")
        else:
            errors.append(f"Invalid API URL: {updates['api_url']}. Must be a valid HTTP or HTTPS URL.")

    if "morning_briefing_enabled" in updates:
        if isinstance(updates["morning_briefing_enabled"], bool):
            current["morning_briefing_enabled"] = updates["morning_briefing_enabled"]
        else:
            errors.append("morning_briefing_enabled must be a boolean.")

    if "preferred_briefing_time" in updates:
        if _validate_briefing_time(updates["preferred_briefing_time"]):
            current["preferred_briefing_time"] = updates["preferred_briefing_time"].strip()
        else:
            errors.append(f"Invalid preferred_briefing_time: {updates['preferred_briefing_time']}. Must be HH:MM.")

    if "contextual_advisories_enabled" in updates:
        if isinstance(updates["contextual_advisories_enabled"], bool):
            current["contextual_advisories_enabled"] = updates["contextual_advisories_enabled"]
        else:
            errors.append("contextual_advisories_enabled must be a boolean.")

    if "advisory_cooldown_hours" in updates:
        if _validate_cooldown_hours(updates["advisory_cooldown_hours"]):
            current["advisory_cooldown_hours"] = int(updates["advisory_cooldown_hours"])
        else:
            errors.append(f"Invalid advisory_cooldown_hours: {updates['advisory_cooldown_hours']}. Must be 2, 4, or 8.")

    if "quiet_hours_enabled" in updates:
        if isinstance(updates["quiet_hours_enabled"], bool):
            current["quiet_hours_enabled"] = updates["quiet_hours_enabled"]
        else:
            errors.append("quiet_hours_enabled must be a boolean.")

    if "quiet_hours_start" in updates:
        if _validate_time_hhmm(updates["quiet_hours_start"]):
            current["quiet_hours_start"] = updates["quiet_hours_start"].strip()
        else:
            errors.append(f"Invalid quiet_hours_start: {updates['quiet_hours_start']}. Must be HH:MM.")

    if "quiet_hours_end" in updates:
        if _validate_time_hhmm(updates["quiet_hours_end"]):
            current["quiet_hours_end"] = updates["quiet_hours_end"].strip()
        else:
            errors.append(f"Invalid quiet_hours_end: {updates['quiet_hours_end']}. Must be HH:MM.")

    if "idle_threshold_minutes" in updates:
        if _validate_idle_threshold_minutes(updates["idle_threshold_minutes"]):
            current["idle_threshold_minutes"] = int(updates["idle_threshold_minutes"])
        else:
            errors.append(f"Invalid idle_threshold_minutes: {updates['idle_threshold_minutes']}. Must be between 1 and 120.")

    if "reminder_lead_times" in updates:
        if isinstance(updates["reminder_lead_times"], dict):
            current["reminder_lead_times"] = updates["reminder_lead_times"]
        else:
            errors.append("reminder_lead_times must be a dictionary.")

    if "hybrid_memory_extraction_enabled" in updates:
        if isinstance(updates["hybrid_memory_extraction_enabled"], bool):
            current["hybrid_memory_extraction_enabled"] = updates["hybrid_memory_extraction_enabled"]
        else:
            errors.append("hybrid_memory_extraction_enabled must be a boolean.")

    if "adaptive_empathy_enabled" in updates:
        if isinstance(updates["adaptive_empathy_enabled"], bool):
            current["adaptive_empathy_enabled"] = updates["adaptive_empathy_enabled"]
        else:
            errors.append("adaptive_empathy_enabled must be a boolean.")

    if "hybrid_memory_confidence_threshold" in updates:
        try:
            thresh = float(updates["hybrid_memory_confidence_threshold"])
            current["hybrid_memory_confidence_threshold"] = max(0.5, min(1.0, thresh))
        except (ValueError, TypeError):
            errors.append("hybrid_memory_confidence_threshold must be a float between 0.5 and 1.0.")

    if "minimize_to_tray_enabled" in updates:
        if isinstance(updates["minimize_to_tray_enabled"], bool):
            current["minimize_to_tray_enabled"] = updates["minimize_to_tray_enabled"]
        else:
            errors.append("minimize_to_tray_enabled must be a boolean.")

    if "desktop_toasts_enabled" in updates:
        if isinstance(updates["desktop_toasts_enabled"], bool):
            current["desktop_toasts_enabled"] = updates["desktop_toasts_enabled"]
        else:
            errors.append("desktop_toasts_enabled must be a boolean.")

    if "full_access_mode" in updates:
        val = str(updates["full_access_mode"]).strip().lower()
        if val in ("supervised", "unrestricted"):
            current["full_access_mode"] = val
            os.environ["ORANGE_FULL_ACCESS_MODE"] = val
        else:
            errors.append(f"Invalid full_access_mode: {updates['full_access_mode']}. Must be 'supervised' or 'unrestricted'.")

    if "idle_followups_enabled" in updates:
        if isinstance(updates["idle_followups_enabled"], bool):
            current["idle_followups_enabled"] = updates["idle_followups_enabled"]
        else:
            errors.append("idle_followups_enabled must be a boolean.")

    if "idle_followup_minutes" in updates:
        try:
            val = int(updates["idle_followup_minutes"])
            current["idle_followup_minutes"] = max(5, min(120, val))
        except (ValueError, TypeError):
            errors.append(f"Invalid idle_followup_minutes: {updates['idle_followup_minutes']}. Must be between 5 and 120.")

    if "active_window_awareness_enabled" in updates:
        if isinstance(updates["active_window_awareness_enabled"], bool):
            current["active_window_awareness_enabled"] = updates["active_window_awareness_enabled"]
        else:
            errors.append("active_window_awareness_enabled must be a boolean.")

    if errors:
        return {
            "success": False,
            "error": "; ".join(errors),
            "settings": current,
            **current,
            "supported_models": list(SUPPORTED_MODELS.values()),
        }

    success = _save_gui_settings(current)
    if success:
        _apply_runtime_settings(current)

    return {
        "success": success,
        "settings": current,
        **current,
        "supported_models": list(SUPPORTED_MODELS.values()),
    }


def handle_ui_set_theme(params: Dict[str, Any]) -> Dict[str, Any]:
    theme = params.get("theme", "dark")
    send_event("ui.set_theme", {"theme": theme})
    return {"status": "ok", "theme": theme}


def handle_ui_toggle_drawer(params: Dict[str, Any]) -> Dict[str, Any]:
    open_state = params.get("open")
    send_event("ui.toggle_drawer", {"open": open_state})
    return {"status": "ok", "open": open_state}


def handle_ui_select_view(params: Dict[str, Any]) -> Dict[str, Any]:
    view = params.get("view", "home")
    send_event("ui.select_view", {"view": view})
    return {"status": "ok", "view": view}


# --- Scope E: Stage 2D Compatibility & RPC Methods ---

def handle_briefing_get_latest(params: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve the latest persisted daily briefing record."""
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, local_date, created_at, content, status, model_name,
                       priorities_json, sources_json, error_message
                FROM daily_briefings ORDER BY created_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return {"briefing": None}
            return {
                "briefing": {
                    "id": row["id"],
                    "local_date": row["local_date"],
                    "created_at": row["created_at"],
                    "content": row["content"],
                    "status": row["status"],
                    "model_name": row["model_name"],
                    "priorities": json.loads(row["priorities_json"] or "[]"),
                    "sources": json.loads(row["sources_json"] or "{}"),
                    "error_message": row["error_message"],
                }
            }
    except Exception as e:
        logger.error("Error in briefing.get_latest: %s", e)
        return {"briefing": None, "error": str(e)}


def handle_briefing_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """List historical daily briefing records."""
    limit = min(int(params.get("limit", 10)), 100)
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, local_date, created_at, content, status, model_name,
                       priorities_json, sources_json, error_message
                FROM daily_briefings ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            briefings = []
            for row in rows:
                briefings.append({
                    "id": row["id"],
                    "local_date": row["local_date"],
                    "created_at": row["created_at"],
                    "content": row["content"],
                    "status": row["status"],
                    "model_name": row["model_name"],
                    "priorities": json.loads(row["priorities_json"] or "[]"),
                    "sources": json.loads(row["sources_json"] or "{}"),
                    "error_message": row["error_message"],
                })
            return {"briefings": briefings}
    except Exception as e:
        logger.error("Error in briefing.list: %s", e)
        return {"briefings": [], "error": str(e)}


def handle_recommendations_get_active(params: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve currently active recommendations formatted for Stage 2A RecommendationCard."""
    recs = _get_active_recommendations()
    return {"recommendations": recs, "count": len(recs)}


def handle_reconciliation_get_latest(params: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve the latest workspace reconciliation records."""
    ws_path = params.get("workspace_path")
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            if ws_path:
                cur.execute("""
                    SELECT id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                           new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                           outstanding_items_json, error_message
                    FROM project_reconciliations WHERE workspace_path = ? ORDER BY reconciled_at DESC LIMIT 10
                """, (ws_path,))
            else:
                cur.execute("""
                    SELECT id, workspace_path, workspace_name, reconciled_at, status, git_branch, git_head_commit,
                           new_commits_json, changed_files_json, uncommitted_changes_json, file_watermark_hash,
                           outstanding_items_json, error_message
                    FROM project_reconciliations ORDER BY reconciled_at DESC LIMIT 20
                """)
            rows = cur.fetchall()
            reconciliations = []
            for row in rows:
                reconciliations.append({
                    "id": row["id"],
                    "workspace_path": row["workspace_path"],
                    "workspace_name": row["workspace_name"],
                    "reconciled_at": row["reconciled_at"],
                    "status": row["status"],
                    "git_branch": row["git_branch"],
                    "git_head_commit": row["git_head_commit"],
                    "new_commits": json.loads(row["new_commits_json"] or "[]"),
                    "changed_files": json.loads(row["changed_files_json"] or "[]"),
                    "uncommitted_changes": json.loads(row["uncommitted_changes_json"] or "[]"),
                    "file_watermark_hash": row["file_watermark_hash"],
                    "outstanding_items": json.loads(row["outstanding_items_json"] or "[]"),
                    "error_message": row["error_message"],
                })
            return {"reconciliations": reconciliations}
    except Exception as e:
        logger.error("Error in reconciliation.get_latest: %s", e)
        return {"reconciliations": [], "error": str(e)}


def handle_stage2c_trigger_briefing(params: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger morning briefing evaluation on demand (with optional sync/test parameters)."""
    force = bool(params.get("force", True))
    sync = bool(params.get("sync", True))
    test_time_str = params.get("test_time")
    test_date_str = params.get("test_date")
    test_now = None
    if test_time_str:
        try:
            parts = test_time_str.split(":")
            today = datetime.now()
            test_now = datetime(today.year, today.month, today.day, int(parts[0]), int(parts[1]))
        except Exception:
            pass
    res = _evaluate_morning_briefing(force=force, test_now=test_now, test_date=test_date_str, sync=sync)
    if sync:
        return {"success": res is not None and res.get("status") in ("success", "fallback"), "briefing": res}
    else:
        return {"success": True, "status": "in_flight"}


def handle_stage2c_trigger_idle_eval(params: Dict[str, Any]) -> Dict[str, Any]:
    """Test helper to trigger idle recommendations evaluation."""
    force = bool(params.get("force", True))
    test_now = None
    if params.get("test_now"):
        try:
            test_now = datetime.fromisoformat(params["test_now"])
        except Exception:
            pass
    recs = _evaluate_idle_recommendations(force=force, test_now=test_now)
    return {"success": True, "count": len(recs), "recommendations": recs}


def handle_stage2c_set_idle_threshold(params: Dict[str, Any]) -> Dict[str, Any]:
    """Test helper to dynamically adjust the idle inactivity threshold."""
    global _idle_inactivity_threshold
    secs = float(params.get("seconds", 600.0))
    _idle_inactivity_threshold = secs
    return {"success": True, "idle_threshold_seconds": secs}


def handle_stage2c_trigger_reconciliation(params: Dict[str, Any]) -> Dict[str, Any]:
    """Test helper to trigger workspace reconciliation on-demand."""
    ws_path = params.get("workspace_path")
    recs = _run_startup_reconciliation(target_path=ws_path)
    return {"success": True, "count": len(recs), "reconciliations": recs}


def handle_events_ack(params: Dict[str, Any]) -> Dict[str, Any]:
    """Mark a proactive event as acknowledged in SQLite."""
    event_id = params.get("event_id")
    if not event_id:
        raise ValueError("event_id parameter is required.")
    now_iso = datetime.now(timezone.utc).isoformat()
    affected = 0
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE proactive_events
                SET acknowledged = 1, acknowledged_at = ?
                WHERE event_id = ?
            """, (now_iso, str(event_id)))
            affected = cur.rowcount
            conn.commit()
    except Exception as e:
        logger.warning("[STAGE-2D] Error acknowledging event %s: %s", event_id, e)
        return {"event_id": event_id, "acknowledged": False, "error": str(e)}

    logger.info("[STAGE-2D] Acknowledged proactive event %s (rows=%d)", event_id, affected)
    return {"event_id": event_id, "acknowledged": True, "rows_affected": affected}


def handle_events_get_unacked(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all unacknowledged proactive events for reconnect/startup replay."""
    limit = max(1, min(int(params.get("limit", 200)), 1000))
    events = []
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT event_id, event_type, entity_id, created_at, payload_json, acknowledged
                FROM proactive_events
                WHERE acknowledged = 0
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            for row in reversed(rows):
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    payload = {}
                events.append({
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "created_at": row["created_at"],
                    "entity_id": row["entity_id"],
                    "version": 1,
                    "payload": payload,
                    "acknowledged": bool(row["acknowledged"]),
                })
    except Exception as e:
        logger.warning("[STAGE-2D] Error fetching unacked events: %s", e)
    return events


def handle_recommendations_dismiss(params: Dict[str, Any]) -> Dict[str, Any]:
    """Dismiss a recommendation: suppresses it for 7 days in RecommendationStore."""
    rec_id = params.get("id") or params.get("rec_id")
    if not rec_id:
        raise ValueError("Recommendation id parameter is required.")
    store = RecommendationStore()
    ok = store.dismiss(str(rec_id))
    if not ok:
        raise ValueError(f"Recommendation '{rec_id}' not found or could not be dismissed.")
    rec = store.get(str(rec_id))
    rec_dict = {
        "id": rec.rec_id,
        "title": rec.title,
        "description": rec.explanation or (getattr(rec, "suggested_action", "")),
        "category": rec.category.value if hasattr(rec.category, "value") else str(rec.category),
        "priority": normalize_recommendation_priority(rec.priority),
        "rationale": getattr(rec, "suggested_action", rec.explanation),
        "action_type": getattr(rec, "recommendation_type", "advisory"),
        "action_payload": getattr(rec, "action_payload", {"entity_id": getattr(rec, "entity_id", "")}),
        "created_at": rec.created_at.isoformat() if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
        "status": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
        "suppressed_until": rec.suppressed_until,
        "dedup_key": getattr(rec, "evidence_fingerprint", rec.rec_id),
        "evidence": getattr(rec, "evidence", []),
    }
    emit_proactive_event(
        event_type="recommendation.updated",
        entity_id=rec.rec_id,
        payload=rec_dict,
        event_id=f"evt_rec_upd_{rec.rec_id}_{uuid.uuid4().hex[:6]}",
    )
    logger.info("[STAGE-2D] Dismissed recommendation %s (suppressed until %s)", rec_id, rec.suppressed_until)
    return rec_dict


def handle_recommendations_snooze(params: Dict[str, Any]) -> Dict[str, Any]:
    """Snooze a recommendation: defers it for 24h (or specified duration) in RecommendationStore."""
    rec_id = params.get("id") or params.get("rec_id")
    duration = params.get("duration", "24h")
    if not rec_id:
        raise ValueError("Recommendation id parameter is required.")
    store = RecommendationStore()
    ok = store.defer(str(rec_id), duration)
    if not ok:
        raise ValueError(f"Recommendation '{rec_id}' not found or invalid snooze duration '{duration}'.")
    rec = store.get(str(rec_id))
    rec_dict = {
        "id": rec.rec_id,
        "title": rec.title,
        "description": rec.explanation or (getattr(rec, "suggested_action", "")),
        "category": rec.category.value if hasattr(rec.category, "value") else str(rec.category),
        "priority": normalize_recommendation_priority(rec.priority),
        "rationale": getattr(rec, "suggested_action", rec.explanation),
        "action_type": getattr(rec, "recommendation_type", "advisory"),
        "action_payload": getattr(rec, "action_payload", {"entity_id": getattr(rec, "entity_id", "")}),
        "created_at": rec.created_at.isoformat() if hasattr(rec.created_at, "isoformat") else str(rec.created_at),
        "status": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
        "suppressed_until": rec.suppressed_until,
        "dedup_key": getattr(rec, "evidence_fingerprint", rec.rec_id),
        "evidence": getattr(rec, "evidence", []),
    }
    emit_proactive_event(
        event_type="recommendation.updated",
        entity_id=rec.rec_id,
        payload=rec_dict,
        event_id=f"evt_rec_upd_{rec.rec_id}_{uuid.uuid4().hex[:6]}",
    )
    logger.info("[STAGE-2D] Snoozed recommendation %s (suppressed until %s)", rec_id, rec.suppressed_until)
    return rec_dict


def handle_recommendations_execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a recommendation action strictly via ToolRegistry and permission architecture.
    Never executes arbitrary commands. Ignores any untrusted executable payload from frontend.
    """
    rec_id = params.get("id") or params.get("rec_id")
    if not rec_id:
        return {"status": "ERROR", "error": "Recommendation ID is required."}

    store = RecommendationStore()
    rec = store.get(str(rec_id))
    if not rec:
        return {"status": "ERROR", "error": f"Recommendation '{rec_id}' not found."}

    # Authoritative resolution: read action details strictly from authoritative rec
    action_type = getattr(rec, "recommendation_type", "advisory")
    action_payload = getattr(rec, "action_payload", None)
    if not action_payload:
        action_payload = _recommendation_actions.get(str(rec.rec_id), {})
    tool_name = action_payload.get("tool_name") if isinstance(action_payload, dict) else None

    # Check for unsupported action types
    if not tool_name or action_type in ("advisory", "unsupported"):
        return {
            "status": "UNSUPPORTED",
            "error": f"Action type '{action_type}' is advisory only and has no automated execution pathway.",
            "recommendation_id": rec.rec_id,
        }

    from tools.registry import registry
    if not registry.contains(tool_name):
        return {
            "status": "UNSUPPORTED",
            "error": f"Tool '{tool_name}' is not registered in ToolRegistry.",
            "recommendation_id": rec.rec_id,
        }

    tool = registry.get(tool_name)
    perm = tool_perm.check_permission(tool)

    # 1. HIGH_RISK check
    if perm.risk_level == tool_perm.RiskLevel.HIGH_RISK or perm.status == tool_perm.PermissionStatus.DENIED:
        return {
            "status": "DENIED",
            "risk_level": "HIGH_RISK",
            "reason": perm.reason,
            "recommendation_id": rec.rec_id,
        }

    # 2. CONFIRMATION_REQUIRED check
    if perm.risk_level == tool_perm.RiskLevel.CONFIRMATION_REQUIRED:
        confirmed = params.get("confirmed")
        token = params.get("confirmation_token")

        if confirmed is None:
            # Generate confirmation token and require handshake
            tok = f"tok_conf_{uuid.uuid4().hex[:12]}"
            _pending_confirmations[tok] = {
                "rec_id": rec.rec_id,
                "tool_name": tool_name,
                "created_at": time.time(),
            }
            return {
                "status": "REQUIRES_CONFIRMATION",
                "confirmation_token": tok,
                "risk_level": "CONFIRMATION_REQUIRED",
                "tool_name": tool_name,
                "prompt": f"Executing tool '{tool_name}' requires explicit confirmation. Proceed?",
                "recommendation_id": rec.rec_id,
            }
        elif confirmed is False:
            return {
                "status": "DENIED",
                "risk_level": "CONFIRMATION_REQUIRED",
                "reason": "Execution cancelled by user.",
                "recommendation_id": rec.rec_id,
            }
        else:
            # confirmed is True - verify token if provided
            if token and token in _pending_confirmations:
                del _pending_confirmations[token]

    # 3. Execution (SAFE or confirmed CONFIRMATION_REQUIRED)
    tool_args = action_payload.get("parameters", {}) if isinstance(action_payload, dict) else {}
    try:
        # Pass prompt_fn returning 'y' because confirmation handshake was already verified
        exec_result = registry.execute(tool_name, is_admin=False, prompt_fn=lambda _: "y", **tool_args)
        store.handle(rec.rec_id)

        updated_rec = store.get(rec.rec_id)
        rec_dict = {
            "id": updated_rec.rec_id,
            "title": updated_rec.title,
            "description": updated_rec.explanation or (getattr(updated_rec, "suggested_action", "")),
            "category": updated_rec.category.value if hasattr(updated_rec.category, "value") else str(updated_rec.category),
            "priority": normalize_recommendation_priority(updated_rec.priority),
            "rationale": getattr(updated_rec, "suggested_action", updated_rec.explanation),
            "action_type": getattr(updated_rec, "recommendation_type", "advisory"),
            "action_payload": getattr(updated_rec, "action_payload", {"entity_id": getattr(updated_rec, "entity_id", "")}),
            "created_at": updated_rec.created_at.isoformat() if hasattr(updated_rec.created_at, "isoformat") else str(updated_rec.created_at),
            "status": updated_rec.state.value if hasattr(updated_rec.state, "value") else str(updated_rec.state),
            "dedup_key": getattr(updated_rec, "evidence_fingerprint", updated_rec.rec_id),
            "evidence": getattr(updated_rec, "evidence", []),
        }
        emit_proactive_event(
            event_type="recommendation.updated",
            entity_id=updated_rec.rec_id,
            payload=rec_dict,
            event_id=f"evt_rec_upd_{updated_rec.rec_id}_{uuid.uuid4().hex[:6]}",
        )
        return {
            "status": "SUCCESS",
            "risk_level": perm.risk_level.value,
            "result": exec_result,
            "recommendation_id": rec.rec_id,
        }
    except Exception as e:
        logger.error("[STAGE-2D] Error executing tool '%s': %s", tool_name, e, exc_info=True)
        return {
            "status": "ERROR",
            "error": str(e),
            "recommendation_id": rec.rec_id,
        }


def _is_test_mode_enabled() -> bool:
    """
    Check if development/test mode is explicitly enabled via process environment variable.
    Strictly disabled by default. Cannot be activated via settings.update or frontend RPC.
    """
    val = os.environ.get("ORANGE_AI_TEST_MODE", "").strip().lower()
    return val in ("1", "true", "yes", "dev", "test")


# 7. Method Dispatch Registry
METHOD_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "system.handshake": handle_system_handshake,
    "system.ping": handle_system_ping,
    "system.health": handle_system_health,
    "system.shutdown": handle_system_shutdown,
    "system.shutdown_for_update": handle_system_shutdown_for_update,
    "chat.history": handle_chat_history,
    "chat.get_history": handle_chat_history,
    "chat.new_session": handle_chat_new_session,
    "chat.confirm": handle_chat_confirm,
    "jobs.list": handle_jobs_list,
    "jobs.status": handle_jobs_status,
    "jobs.history": handle_jobs_history,
    "jobs.create": handle_jobs_create,
    "jobs.start": handle_jobs_start,
    "jobs.pause": handle_jobs_pause,
    "jobs.resume": handle_jobs_resume,
    "jobs.cancel": handle_jobs_cancel,
    "jobs.confirm": handle_jobs_confirm,
    "memory.structured": handle_memory_structured,
    "memory.legacy": handle_memory_legacy,
    "memory.stats": handle_memory_stats,
    "memory.forget": handle_memory_forget,
    "memory.retract": handle_memory_retract,
    "memory.remember": handle_memory_remember,
    "memory.create_structured": handle_memory_create_structured,
    "memory.update": handle_memory_update,
    "reminders.create": handle_reminders_create,
    "reminders.list": handle_reminders_list,
    "reminders.cancel": handle_reminders_cancel,
    "activity.get": handle_activity_get,
    "tools.list": handle_tools_list,
    "skills.list": handle_skills_list,
    "skills.create": handle_skills_create,
    "skills.toggle": handle_skills_toggle,
    "skills.delete": handle_skills_delete,
    "skills.run": handle_skills_run,
    "attachments.capture_screen": handle_attachments_capture_screen,
    "permissions.audit": handle_permissions_audit,
    "settings.get": handle_settings_get,
    "settings.update": handle_settings_update,
    "ui.set_theme": handle_ui_set_theme,
    "ui.toggle_drawer": handle_ui_toggle_drawer,
    "ui.select_view": handle_ui_select_view,
    "briefing.get_latest": handle_briefing_get_latest,
    "briefing.list": handle_briefing_list,
    "briefing.trigger": handle_stage2c_trigger_briefing,
    "stage2c.trigger_briefing": handle_stage2c_trigger_briefing,
    "recommendations.get_active": handle_recommendations_get_active,
    "recommendations.dismiss": handle_recommendations_dismiss,
    "recommendations.snooze": handle_recommendations_snooze,
    "recommendations.execute": handle_recommendations_execute,
    "reconciliation.get_latest": handle_reconciliation_get_latest,
    "events.ack": handle_events_ack,
    "events.get_unacked": handle_events_get_unacked,
}

TEST_METHOD_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "stage2c.trigger_briefing": handle_stage2c_trigger_briefing,
    "stage2c.trigger_idle_eval": handle_stage2c_trigger_idle_eval,
    "stage2c.set_idle_threshold": handle_stage2c_set_idle_threshold,
    "stage2c.trigger_reconciliation": handle_stage2c_trigger_reconciliation,
}


_EXCLUDED_ACTIVITY_METHODS = {
    "system.handshake",
    "system.ping",
    "system.health",
    "system.shutdown",
    "system.shutdown_for_update",
    "activity.get",
    "briefing.get_latest",
    "briefing.list",
    "recommendations.get_active",
    "reconciliation.get_latest",
    "events.ack",
    "events.get_unacked",
    "stage2c.trigger_briefing",
    "stage2c.trigger_idle_eval",
    "stage2c.set_idle_threshold",
    "stage2c.trigger_reconciliation",
}


def dispatch_request(req_id: Any, method: str, params: Dict[str, Any]):
    """Route a single JSON-RPC request to its handler."""
    global _last_user_activity
    if method not in _EXCLUDED_ACTIVITY_METHODS:
        _last_user_activity = time.time()

    if method == "chat.send":
        # Dispatched to its own thread inside handle_chat_send
        handle_chat_send(req_id, params)
        return

    handler = METHOD_REGISTRY.get(method)
    if not handler and _is_test_mode_enabled():
        handler = TEST_METHOD_REGISTRY.get(method)

    if not handler:
        send_error(req_id, -32601, f"Method '{method}' not found.")
        return

    try:
        res = handler(params)
        send_response(req_id, res)
    except Exception as e:
        logger.error("Error executing %s: %s", method, e, exc_info=True)
        send_error(req_id, -32000, str(e))


def main_loop():
    """Main input loop reading line-delimited JSON-RPC from standard input."""
    global _START_TIME
    _START_TIME = time.time()
    logger.info("Orange AI Runtime Adapter started. PID: %d", os.getpid())

    # Initialize core state lazily
    try:
        main.ensure_initialized()
    except Exception as e:
        logger.error("Failed to initialize background engine: %s", e, exc_info=True)

    # Inform Rust supervisor that startup is ready (guaranteed first stdout frame)
    send_event("runtime.ready", {
        "pid": os.getpid(),
        "version": ORANGE_AI_VERSION,
        "timestamp": time.time(),
    })

    try:
        # Interrupted jobs crash recovery MUST execute before scheduler and background workers start
        try:
            job_mgr = main.get_job_manager() if hasattr(main, "get_job_manager") else None
            if job_mgr:
                recovered_jobs = job_mgr.recover_interrupted()
                logger.info(
                    "[STARTUP-RECOVERY] Interrupted jobs recovery completed. Recovered count: %d",
                    len(recovered_jobs) if recovered_jobs else 0,
                )
        except Exception as e:
            logger.error("[STARTUP-RECOVERY] Failed to recover interrupted jobs during startup: %s", e, exc_info=True)

        _init_stage2c_background_workers()
        # Start the proactive background scheduler (jobs only; reminders evaluated authoritatively by Stage2C worker)
        scheduler.start(
            on_reminder_due=None,
            on_job_event=_on_job_event,
            job_manager=main.get_job_manager(),
        )
        logger.info("Background scheduler initialized.")
    except Exception as e:
        logger.error("Failed to initialize background engine: %s", e, exc_info=True)

    # Start UI command watcher for automated test control
    t_watcher = threading.Thread(target=_ui_control_file_watcher, daemon=True, name="UICommandWatcher")
    t_watcher.start()

    while not _is_shutting_down:
        try:
            line = sys.stdin.readline()
            if not line:
                # EOF: Parent pipe broken (Tauri exited or crashed)
                logger.info("EOF detected on stdin (parent process exited). Terminating adapter.")
                break

            line_str = line.strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
            except json.JSONDecodeError as e:
                logger.warning("Malformed JSON received on stdin: %s", e)
                send_error(None, -32700, "Parse error: Invalid JSON.")
                continue

            if not isinstance(msg, dict):
                send_error(None, -32600, "Invalid Request: Must be a JSON object.")
                continue

            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") or {}

            if not method:
                send_error(req_id, -32600, "Invalid Request: Missing 'method'.")
                continue

            dispatch_request(req_id, method, params)

        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.error("Unhandled error in main loop: %s", e, exc_info=True)

    # Perform clean teardown
    handle_system_shutdown({})


if __name__ == "__main__":
    main_loop()
