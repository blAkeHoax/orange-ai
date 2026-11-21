// src/components/views/SettingsView.jsx - Desktop Settings, Appearance & Environment Workspace
import React, { useState, useEffect } from 'react';
import {
  Settings,
  Sun,
  Moon,
  Monitor,
  RefreshCw,
  Server,
  ShieldCheck,
  HardDrive,
  Cpu,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Sparkles,
  Clock,
  Edit3,
  Save,
  X,
  Check
} from 'lucide-react';
import { pingAdapter, getHealth, getSettings, updateSettings, triggerBriefing } from '../../services/tauriBridge';
import { useTheme } from '../../context/ThemeContext';
import '../../styles/SecondaryViews.css';

// Approved Model Foundation & Task-Based Dynamic Routing
const FALLBACK_MODELS = [
  {
    id: 'auto',
    name: 'Auto (Task-Based Dynamic Routing)',
    provider: 'Orange AI',
    tag: 'RECOMMENDED / DYNAMIC',
    description: 'Routes conversation & reasoning to Nemotron 3.5 Bolt E4B, briefings & agent decisions to Nemotron 3.5 Lightning 30B, and coding to MiniMax M3.1 Flash.'
  },
  {
    id: 'nvidia/nemotron-3.5-bolt-e4b',
    name: 'Nemotron 3.5 Bolt E4B',
    provider: 'NVIDIA',
    tag: 'CONVERSATIONAL & REASONING',
    description: 'Ultra-fast 1.7s model tuned for daily conversation, multi-turn dialogue, and analytical reasoning.'
  },
  {
    id: 'nvidia/nemotron-3.5-lightning-30b-a3b',
    name: 'Nemotron 3.5 Lightning 30B',
    provider: 'NVIDIA',
    tag: 'BRIEFING, AGENT & FALLBACK',
    description: 'Authoritative 2.4s foundation model for Morning Briefings, agent tool execution, and default fallback.'
  },
  {
    id: 'minimaxai/minimax-m3.1-flash',
    name: 'MiniMax M3.1 Flash',
    provider: 'MiniMax',
    tag: 'CODING & STRUCTURED',
    description: 'Specialized open-weights model optimized for code generation, debugging, refactoring, and structured JSON.'
  }
];

export default function SettingsView() {
  const { themePreference, resolvedTheme, setThemePreference } = useTheme();

  // Runtime telemetry & settings
  const [runtimeInfo, setRuntimeInfo] = useState(null);
  const [healthInfo, setHealthInfo] = useState(null);
  const [settingsData, setSettingsData] = useState({});
  const [loading, setLoading] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState(null);

  // Model Selection State
  const [supportedModels, setSupportedModels] = useState(FALLBACK_MODELS);
  const [selectedModel, setSelectedModel] = useState('auto');
  const [updatingModel, setUpdatingModel] = useState(false);
  const [modelStatusMsg, setModelStatusMsg] = useState('');

  // Proactive Personal Assistance State
  const [briefingEnabled, setBriefingEnabled] = useState(false);
  const [briefingTime, setBriefingTime] = useState('08:30');
  const [briefingTimeInput, setBriefingTimeInput] = useState('08:30');
  const [timeError, setTimeError] = useState('');
  const [advisoriesEnabled, setAdvisoriesEnabled] = useState(true);
  const [cooldownHours, setCooldownHours] = useState(4);
  const [proactiveStatusMsg, setProactiveStatusMsg] = useState('');
  const [generatingBriefing, setGeneratingBriefing] = useState(false);

  // Quiet Hours State (GAP-4A-5)
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(false);
  const [quietHoursStart, setQuietHoursStart] = useState('22:00');
  const [quietHoursEnd, setQuietHoursEnd] = useState('07:00');
  const [quietHoursStartInput, setQuietHoursStartInput] = useState('22:00');
  const [quietHoursEndInput, setQuietHoursEndInput] = useState('07:00');
  const [quietHoursError, setQuietHoursError] = useState('');

  // Idle Inactivity Threshold State (GAP-4A-7)
  const [idleThresholdMinutes, setIdleThresholdMinutes] = useState(10);

  // Editable Orange API URL State
  const [apiUrl, setApiUrl] = useState('https://orange-api-cuuo.onrender.com');
  const [isEditingUrl, setIsEditingUrl] = useState(false);
  const [tempUrlInput, setTempUrlInput] = useState('https://orange-api-cuuo.onrender.com');
  const [urlError, setUrlError] = useState('');
  const [urlStatusMsg, setUrlStatusMsg] = useState('');
  const [savingUrl, setSavingUrl] = useState(false);

  const fetchSettingsAndStatus = async () => {
    setLoading(true);
    try {
      const [ping, health, conf] = await Promise.all([
        pingAdapter(),
        getHealth(),
        getSettings()
      ]);
      setRuntimeInfo(ping || {});
      setHealthInfo(health || {});
      setSettingsData(conf || {});
      setConnectionStatus(ping?.api_online ? 'online' : 'offline');

      // Populate models
      const modelsList = Array.isArray(conf?.supported_models) && conf.supported_models.length > 0
        ? conf.supported_models
        : FALLBACK_MODELS;
      setSupportedModels(modelsList);
      if (conf?.model) {
        const isValid = modelsList.some((m) => m.id === conf.model);
        setSelectedModel(isValid ? conf.model : (conf.default_model || 'auto'));
      }

      // Populate proactive assistance settings
      if (typeof conf?.morning_briefing_enabled === 'boolean') {
        setBriefingEnabled(conf.morning_briefing_enabled);
      }
      if (conf?.preferred_briefing_time) {
        setBriefingTime(conf.preferred_briefing_time);
        setBriefingTimeInput(conf.preferred_briefing_time);
      }
      if (typeof conf?.contextual_advisories_enabled === 'boolean') {
        setAdvisoriesEnabled(conf.contextual_advisories_enabled);
      }
      if (conf?.advisory_cooldown_hours) {
        setCooldownHours(Number(conf.advisory_cooldown_hours));
      }
      if (typeof conf?.quiet_hours_enabled === 'boolean') {
        setQuietHoursEnabled(conf.quiet_hours_enabled);
      }
      if (conf?.quiet_hours_start) {
        setQuietHoursStart(conf.quiet_hours_start);
        setQuietHoursStartInput(conf.quiet_hours_start);
      }
      if (conf?.quiet_hours_end) {
        setQuietHoursEnd(conf.quiet_hours_end);
        setQuietHoursEndInput(conf.quiet_hours_end);
      }
      if (conf?.idle_threshold_minutes) {
        setIdleThresholdMinutes(Number(conf.idle_threshold_minutes));
      }

      // Populate API URL
      const currentUrl = conf?.api_url || health?.api?.endpoint || 'https://orange-api-cuuo.onrender.com';
      setApiUrl(currentUrl);
      setTempUrlInput(currentUrl);
    } catch (err) {
      console.error('Error fetching settings info:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettingsAndStatus();
  }, []);

  const handleTestConnection = async () => {
    setTestingConnection(true);
    try {
      const ping = await pingAdapter();
      setRuntimeInfo(ping || {});
      setConnectionStatus(ping?.api_online ? 'online' : 'offline');
    } catch (err) {
      setConnectionStatus('offline');
    } finally {
      setTestingConnection(false);
    }
  };

  // 1. Theme Selection Handler (Scope C)
  const handleSelectTheme = async (mode) => {
    setThemePreference(mode);
    try {
      await updateSettings({ theme: mode });
    } catch (err) {
      console.warn('Could not persist theme to Python settings:', err);
    }
  };

  // 2. Model Selection Handler (Scope A)
  const handleSelectModel = async (modelId) => {
    if (modelId === selectedModel || updatingModel) return;
    setUpdatingModel(true);
    setModelStatusMsg('');
    try {
      const res = await updateSettings({ model: modelId });
      if (res?.success) {
        setSelectedModel(modelId);
        const modelName = supportedModels.find((m) => m.id === modelId)?.name || modelId;
        setModelStatusMsg(`✓ Switched to ${modelName}`);
        setTimeout(() => setModelStatusMsg(''), 3000);
      } else {
        setModelStatusMsg(`Error: ${res?.error || 'Failed to update model'}`);
      }
    } catch (err) {
      setModelStatusMsg(`Error: ${err.message || String(err)}`);
    } finally {
      setUpdatingModel(false);
    }
  };

  // 3. Proactive Settings Handlers (Scope B)
  const handleToggleBriefing = async () => {
    const nextVal = !briefingEnabled;
    setBriefingEnabled(nextVal);
    try {
      await updateSettings({ morning_briefing_enabled: nextVal });
      flashProactiveStatus(nextVal ? '✓ Morning Briefing Enabled' : '✓ Morning Briefing Disabled');
    } catch (err) {
      setBriefingEnabled(!nextVal);
      flashProactiveStatus('Error updating briefing preference', true);
    }
  };

  const handleSaveBriefingTime = async () => {
    setTimeError('');
    const regex = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
    if (!regex.test(briefingTimeInput.trim())) {
      setTimeError('Invalid format. Use 24h HH:MM (e.g. 08:30)');
      return;
    }
    const cleanTime = briefingTimeInput.trim();
    try {
      const res = await updateSettings({ preferred_briefing_time: cleanTime });
      if (res?.success) {
        setBriefingTime(cleanTime);
        flashProactiveStatus(`✓ Briefing Time Saved (${cleanTime})`);
      } else {
        setTimeError(res?.error || 'Validation failed');
      }
    } catch (err) {
      setTimeError(err.message || 'Failed to save briefing time');
    }
  };

  const handleToggleAdvisories = async () => {
    const nextVal = !advisoriesEnabled;
    setAdvisoriesEnabled(nextVal);
    try {
      await updateSettings({ contextual_advisories_enabled: nextVal });
      flashProactiveStatus(nextVal ? '✓ Contextual Advisories Enabled' : '✓ Contextual Advisories Disabled');
    } catch (err) {
      setAdvisoriesEnabled(!nextVal);
      flashProactiveStatus('Error updating advisories preference', true);
    }
  };

  const handleSelectCooldown = async (hrs) => {
    const num = Number(hrs);
    setCooldownHours(num);
    try {
      await updateSettings({ advisory_cooldown_hours: num });
      flashProactiveStatus(`✓ Cooldown set to ${num} hours`);
    } catch (err) {
      flashProactiveStatus('Error saving cooldown hours', true);
    }
  };

  const handleSelectIdleThreshold = async (mins) => {
    const num = Number(mins);
    setIdleThresholdMinutes(num);
    try {
      await updateSettings({ idle_threshold_minutes: num });
      flashProactiveStatus(`✓ Idle Threshold set to ${num} minutes`);
    } catch (err) {
      flashProactiveStatus('Error saving idle threshold', true);
    }
  };

  const handleToggleQuietHours = async () => {
    const nextVal = !quietHoursEnabled;
    setQuietHoursEnabled(nextVal);
    try {
      await updateSettings({ quiet_hours_enabled: nextVal });
      flashProactiveStatus(nextVal ? '✓ Quiet Hours Enabled' : '✓ Quiet Hours Disabled');
    } catch (err) {
      setQuietHoursEnabled(!nextVal);
      flashProactiveStatus('Error updating Quiet Hours preference', true);
    }
  };

  const handleSaveQuietHoursTimes = async () => {
    setQuietHoursError('');
    const regex = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
    const cleanStart = quietHoursStartInput.trim();
    const cleanEnd = quietHoursEndInput.trim();
    if (!regex.test(cleanStart) || !regex.test(cleanEnd)) {
      setQuietHoursError('Invalid format. Use 24h HH:MM (e.g. 22:00 and 07:00)');
      return;
    }
    try {
      const res = await updateSettings({
        quiet_hours_start: cleanStart,
        quiet_hours_end: cleanEnd
      });
      if (res?.success) {
        setQuietHoursStart(cleanStart);
        setQuietHoursEnd(cleanEnd);
        flashProactiveStatus(`✓ Quiet Hours Saved (${cleanStart} - ${cleanEnd})`);
      } else {
        setQuietHoursError(res?.error || 'Validation failed');
      }
    } catch (err) {
      setQuietHoursError(err.message || 'Failed to save Quiet Hours');
    }
  };

  const handleGenerateBriefingNow = async () => {
    if (generatingBriefing) return;
    setGeneratingBriefing(true);
    flashProactiveStatus('Synthesizing morning briefing...');
    try {
      const res = await triggerBriefing({ force: true, sync: true });
      if (res?.success) {
        flashProactiveStatus('✓ Morning Briefing Generated');
        if (res?.briefing && window.__orangeAi?.openBriefing) {
          window.__orangeAi.openBriefing(res.briefing);
        }
      } else {
        flashProactiveStatus(`Error: ${res?.error || 'Failed to generate briefing'}`, true);
      }
    } catch (err) {
      flashProactiveStatus(`Error: ${err.message || String(err)}`, true);
    } finally {
      setGeneratingBriefing(false);
    }
  };

  const flashProactiveStatus = (msg, isError = false) => {
    setProactiveStatusMsg(msg);
    setTimeout(() => setProactiveStatusMsg(''), 3500);
  };

  // 4. API URL Handlers (Scope D)
  const validateUrl = (urlStr) => {
    if (!urlStr || typeof urlStr !== 'string') return 'URL cannot be empty.';
    const trimmed = urlStr.trim();
    const lower = trimmed.toLowerCase();
    if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('file:') || lower.startsWith('ftp:')) {
      return 'Unsafe scheme rejected. Only HTTP and HTTPS URLs are permitted.';
    }
    if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
      return 'URL must start with http:// or https://';
    }
    try {
      const parsed = new URL(trimmed);
      if (!parsed.hostname) return 'URL must include a valid hostname.';
      return null;
    } catch (e) {
      return 'Malformed URL syntax.';
    }
  };

  const handleSaveUrl = async () => {
    setUrlError('');
    setUrlStatusMsg('');
    const trimmed = tempUrlInput.trim();
    const err = validateUrl(trimmed);
    if (err) {
      setUrlError(err);
      return;
    }

    setSavingUrl(true);
    try {
      const res = await updateSettings({ api_url: trimmed });
      if (res?.success) {
        const cleanSaved = res?.settings?.api_url || trimmed;
        setApiUrl(cleanSaved);
        setTempUrlInput(cleanSaved);
        setIsEditingUrl(false);
        setUrlStatusMsg('✓ API Endpoint Updated');
        setTimeout(() => setUrlStatusMsg(''), 3000);
        // Retest connection with new URL
        handleTestConnection();
      } else {
        setUrlError(res?.error || 'Failed to update API URL');
      }
    } catch (e) {
      setUrlError(e.message || 'Network error saving API URL');
    } finally {
      setSavingUrl(false);
    }
  };

  const handleCancelUrl = () => {
    setTempUrlInput(apiUrl);
    setUrlError('');
    setIsEditingUrl(false);
  };

  return (
    <div className="view-inner-container">
      {/* View Header */}
      <div className="view-header-row">
        <div>
          <h2 className="view-title">Settings & Configuration</h2>
          <p className="view-subtitle">
            Configure appearance, select foundational reasoning models, configure assistant preferences, and manage endpoint connectivity.
          </p>
        </div>
        <button
          className="action-btn-secondary"
          onClick={fetchSettingsAndStatus}
          disabled={loading}
          type="button"
          title="Refresh Settings from Python Runtime"
        >
          <RefreshCw size={14} className={loading ? 'spinning' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="feed-scroll-container">
        {/* ============================================================== */}
        {/* SECTION 1: Appearance & Workspace Theme (Scope C)               */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <Sun size={18} className="text-orange" />
            <span className="section-card-title">Appearance & Workspace Theme</span>
          </div>
          <p className="section-card-desc">
            Choose your preferred color palette. Changes take effect instantly across all views, modals, and native title bars.
          </p>
          <div className="theme-toggle-options">
            {/* Dark Theme */}
            <button
              className={`theme-option-box ${themePreference === 'dark' ? 'is-selected' : ''}`}
              onClick={() => handleSelectTheme('dark')}
              type="button"
            >
              <Moon size={20} />
              <div className="theme-option-info">
                <span className="theme-option-name">Dark Theme</span>
                <span className="theme-option-detail">#0D1117 Immersive Workspace</span>
              </div>
              {themePreference === 'dark' && <CheckCircle2 size={16} className="text-orange" />}
            </button>

            {/* Light Theme */}
            <button
              className={`theme-option-box ${themePreference === 'light' ? 'is-selected' : ''}`}
              onClick={() => handleSelectTheme('light')}
              type="button"
            >
              <Sun size={20} />
              <div className="theme-option-info">
                <span className="theme-option-name">Light Theme</span>
                <span className="theme-option-detail">#FFFFFF Clean Daylight Workspace</span>
              </div>
              {themePreference === 'light' && <CheckCircle2 size={16} className="text-orange" />}
            </button>

            {/* System Mode (Scope C) */}
            <button
              className={`theme-option-box ${themePreference === 'system' ? 'is-selected' : ''}`}
              onClick={() => handleSelectTheme('system')}
              type="button"
            >
              <Monitor size={20} />
              <div className="theme-option-info">
                <span className="theme-option-name">System Default</span>
                <span className="theme-option-detail">
                  Auto-detects OS theme ({resolvedTheme} active)
                </span>
              </div>
              {themePreference === 'system' && <CheckCircle2 size={16} className="text-orange" />}
            </button>
          </div>
        </div>

        {/* ============================================================== */}
        {/* SECTION 2: NVIDIA Model Selection (Scope A)                     */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <Cpu size={18} className="text-orange" />
            <div className="section-card-title-group">
              <span className="section-card-title">NVIDIA Model Foundation</span>
              {modelStatusMsg && (
                <span className="section-status-pill">{modelStatusMsg}</span>
              )}
            </div>
          </div>
          <p className="section-card-desc">
            Select the active foundational model for conversational assistance and agent reasoning. Choice is validated and persisted authoritatively by the Python runtime.
          </p>

          <div className="model-radio-grid">
            {supportedModels.map((m) => {
              const isSelected = selectedModel === m.id;
              return (
                <div
                  key={m.id}
                  className={`model-option-card ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => handleSelectModel(m.id)}
                  role="button"
                  tabIndex={0}
                >
                  <div className="model-card-top">
                    <div className="model-radio-circle">
                      {isSelected ? <div className="model-radio-dot" /> : null}
                    </div>
                    <div className="model-name-group">
                      <span className="model-display-name">{m.name}</span>
                      <span className="model-tag-pill">{m.tag}</span>
                    </div>
                  </div>
                  <p className="model-description">{m.description}</p>
                  <div className="model-id-code">
                    <code>{m.id}</code>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ============================================================== */}
        {/* SECTION 3: Proactive Personal Assistance (Scope B)              */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <Sparkles size={18} className="text-orange" />
            <div className="section-card-title-group">
              <span className="section-card-title">Proactive Personal Assistance</span>
              {proactiveStatusMsg && (
                <span className="section-status-pill">{proactiveStatusMsg}</span>
              )}
            </div>
          </div>
          <p className="section-card-desc">
            Configure morning briefing schedule and contextual recommendations in conversational chat. Preferences are saved and maintained by the Python runtime sidecar.
          </p>

          <div className="proactive-controls-list">
            {/* Control 1: Morning Briefing Toggle */}
            <div className="proactive-row">
              <div className="proactive-label-group">
                <span className="proactive-title">Morning Briefing</span>
                <span className="proactive-subtitle">
                  Deliver a daily summary of project status, deadlines, and system reminders on first launch.
                </span>
              </div>
              <button
                type="button"
                className={`switch-toggle-btn ${briefingEnabled ? 'is-active' : ''}`}
                onClick={handleToggleBriefing}
                title={briefingEnabled ? 'Disable Morning Briefing' : 'Enable Morning Briefing'}
              >
                <div className="switch-toggle-handle" />
              </button>
            </div>

            {/* Control 2: Preferred Delivery Time */}
            <div className="proactive-row is-sub-control">
              <div className="proactive-label-group">
                <span className="proactive-title">Preferred Delivery Time (24h)</span>
                <span className="proactive-subtitle">
                  Target delivery time in HH:MM format (default 08:30).
                </span>
              </div>
              <div className="time-entry-group">
                <input
                  type="text"
                  className={`settings-time-input ${timeError ? 'is-error' : ''}`}
                  value={briefingTimeInput}
                  onChange={(e) => setBriefingTimeInput(e.target.value)}
                  maxLength={5}
                  placeholder="08:30"
                />
                <button
                  type="button"
                  className="btn-save-inline"
                  onClick={handleSaveBriefingTime}
                >
                  <Save size={12} />
                  <span>Save Time</span>
                </button>
              </div>
            </div>
            {timeError && (
              <div className="inline-error-text">
                <AlertTriangle size={12} />
                <span>{timeError}</span>
              </div>
            )}

            {/* Control 2b: Manual Briefing Trigger (GAP-4A-3) */}
            <div className="proactive-row is-sub-control">
              <div className="proactive-label-group">
                <span className="proactive-title">Manual Briefing Trigger</span>
                <span className="proactive-subtitle">
                  Generate or refresh today's morning briefing immediately on demand.
                </span>
              </div>
              <div className="time-entry-group">
                <button
                  type="button"
                  className="btn-save-inline"
                  onClick={handleGenerateBriefingNow}
                  disabled={generatingBriefing}
                  title="Generate or refresh today's morning briefing"
                >
                  <Sparkles size={12} className={generatingBriefing ? 'spinning' : ''} />
                  <span>{generatingBriefing ? 'Generating...' : 'Generate Briefing Now'}</span>
                </button>
              </div>
            </div>

            {/* Control 3: Contextual Chat Advisories Toggle */}
            <div className="proactive-row">
              <div className="proactive-label-group">
                <span className="proactive-title">Contextual Chat Advisories</span>
                <span className="proactive-subtitle">
                  Append contextual recommendations to conversational responses when discussing active projects or jobs.
                </span>
              </div>
              <button
                type="button"
                className={`switch-toggle-btn ${advisoriesEnabled ? 'is-active' : ''}`}
                onClick={handleToggleAdvisories}
                title={advisoriesEnabled ? 'Disable Advisories' : 'Enable Advisories'}
              >
                <div className="switch-toggle-handle" />
              </button>
            </div>

            {/* Control 4: Advisory Cooldown */}
            <div className="proactive-row is-sub-control">
              <div className="proactive-label-group">
                <span className="proactive-title">Minimum Advisory Cooldown</span>
                <span className="proactive-subtitle">
                  Minimum quiet period between consecutive chat advisories for the same entity unless explicitly requested.
                </span>
              </div>
              <div className="cooldown-pill-group">
                {[2, 4, 8].map((hrs) => (
                  <button
                    key={hrs}
                    type="button"
                    className={`cooldown-btn ${cooldownHours === hrs ? 'is-selected' : ''}`}
                    onClick={() => handleSelectCooldown(hrs)}
                  >
                    {hrs === 4 ? `${hrs} hours (Default)` : `${hrs} hours`}
                  </button>
                ))}
              </div>
            </div>

            {/* Control 5: Idle Inactivity Threshold (GAP-4A-7) */}
            <div className="proactive-row is-sub-control">
              <div className="proactive-label-group">
                <span className="proactive-title">Idle Inactivity Threshold</span>
                <span className="proactive-subtitle">
                  Duration of user inactivity before evaluating contextual recommendations.
                </span>
              </div>
              <div className="cooldown-pill-group">
                {[5, 10, 15, 30].map((mins) => (
                  <button
                    key={mins}
                    type="button"
                    className={`cooldown-btn ${idleThresholdMinutes === mins ? 'is-selected' : ''}`}
                    onClick={() => handleSelectIdleThreshold(mins)}
                  >
                    {mins === 10 ? `${mins} min (Default)` : `${mins} min`}
                  </button>
                ))}
              </div>
            </div>

            {/* Control 6: Quiet Hours (Do-Not-Disturb) (GAP-4A-5) */}
            <div className="proactive-row">
              <div className="proactive-label-group">
                <span className="proactive-title">Quiet Hours (Do-Not-Disturb)</span>
                <span className="proactive-subtitle">
                  Defer automatic morning briefings, idle recommendations, pre-due reminder alerts, and post-job follow-ups during selected hours.
                </span>
              </div>
              <button
                type="button"
                className={`switch-toggle-btn ${quietHoursEnabled ? 'is-active' : ''}`}
                onClick={handleToggleQuietHours}
                title={quietHoursEnabled ? 'Disable Quiet Hours' : 'Enable Quiet Hours'}
              >
                <div className="switch-toggle-handle" />
              </button>
            </div>

            {/* Control 7: Quiet Hours Window */}
            <div className="proactive-row is-sub-control">
              <div className="proactive-label-group">
                <span className="proactive-title">Quiet Hours Window (24h)</span>
                <span className="proactive-subtitle">
                  Configure start and end times in HH:MM format (supports overnight windows, e.g. 22:00 to 07:00).
                </span>
              </div>
              <div className="time-entry-group">
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>From</span>
                <input
                  type="text"
                  className={`settings-time-input ${quietHoursError ? 'is-error' : ''}`}
                  value={quietHoursStartInput}
                  onChange={(e) => setQuietHoursStartInput(e.target.value)}
                  maxLength={5}
                  placeholder="22:00"
                />
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>to</span>
                <input
                  type="text"
                  className={`settings-time-input ${quietHoursError ? 'is-error' : ''}`}
                  value={quietHoursEndInput}
                  onChange={(e) => setQuietHoursEndInput(e.target.value)}
                  maxLength={5}
                  placeholder="07:00"
                />
                <button
                  type="button"
                  className="btn-save-inline"
                  onClick={handleSaveQuietHoursTimes}
                >
                  <Save size={12} />
                  <span>Save Hours</span>
                </button>
              </div>
            </div>
            {quietHoursError && (
              <div className="inline-error-text">
                <AlertTriangle size={12} />
                <span>{quietHoursError}</span>
              </div>
            )}

            {/* Active Proactive Engine Status (Stage 4) */}
            <div className="proactive-disclaimer-box">
              <span className="disclaimer-title">Proactive Engine Active:</span> Morning briefings, due reminder evaluation, and contextual advisories are running autonomously with local crash recovery and persistent outbox delivery.
            </div>
          </div>
        </div>

        {/* ============================================================== */}
        {/* SECTION 4: Orange API Connection & Status (Scope D)             */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <Server size={18} className="text-orange" />
            <div className="section-card-title-group">
              <span className="section-card-title">Orange API Connection & Status</span>
              {urlStatusMsg && (
                <span className="section-status-pill">{urlStatusMsg}</span>
              )}
            </div>
          </div>
          <p className="section-card-desc">
            Configured HTTP service endpoint for conversational AI inference and remote tools. Validated and persisted by Python.
          </p>

          <div className="endpoint-config-card">
            <div className="endpoint-top-row">
              <div className="endpoint-info">
                <span className="info-label">API Endpoint:</span>
                {!isEditingUrl ? (
                  <div className="endpoint-display-group">
                    <code className="endpoint-code">{apiUrl}</code>
                    {apiUrl === 'https://orange-api-cuuo.onrender.com' && (
                      <span className="default-pill">Production Default</span>
                    )}
                  </div>
                ) : null}
              </div>

              {!isEditingUrl ? (
                <div className="endpoint-actions">
                  <button
                    className="btn-edit-endpoint"
                    onClick={() => {
                      setIsEditingUrl(true);
                      setTempUrlInput(apiUrl);
                      setUrlError('');
                    }}
                    type="button"
                  >
                    <Edit3 size={12} />
                    <span>Edit Endpoint</span>
                  </button>
                </div>
              ) : null}
            </div>

            {/* Editable Input Row (Scope D) */}
            {isEditingUrl && (
              <div className="endpoint-edit-container">
                <div className="endpoint-edit-row">
                  <input
                    type="text"
                    className={`settings-url-input ${urlError ? 'is-error' : ''}`}
                    value={tempUrlInput}
                    onChange={(e) => setTempUrlInput(e.target.value)}
                    placeholder="https://orange-api-cuuo.onrender.com"
                    autoFocus
                  />
                  <div className="endpoint-edit-buttons">
                    <button
                      className="btn-save-endpoint"
                      onClick={handleSaveUrl}
                      disabled={savingUrl}
                      type="button"
                    >
                      <Save size={13} />
                      <span>{savingUrl ? 'Saving...' : 'Save'}</span>
                    </button>
                    <button
                      className="btn-cancel-endpoint"
                      onClick={handleCancelUrl}
                      type="button"
                    >
                      <X size={13} />
                      <span>Cancel</span>
                    </button>
                  </div>
                </div>

                {urlError && (
                  <div className="inline-error-text">
                    <AlertTriangle size={12} />
                    <span>{urlError}</span>
                  </div>
                )}
              </div>
            )}

            {/* Live Connection Telemetry Row */}
            <div className="connection-status-row">
              <span className={`status-pill-connection is-${loading ? 'checking' : (connectionStatus || 'offline')}`}>
                {loading ? (
                  <>
                    <RefreshCw size={13} className="spinning" />
                    <span>Checking...</span>
                  </>
                ) : connectionStatus === 'online' ? (
                  <>
                    <CheckCircle2 size={13} />
                    <span>Backend Online</span>
                  </>
                ) : (
                  <>
                    <XCircle size={13} />
                    <span>Offline / Local Fallback</span>
                  </>
                )}
              </span>

              <button
                className="btn-test-connection"
                onClick={handleTestConnection}
                disabled={testingConnection}
                type="button"
              >
                <RefreshCw size={12} className={testingConnection ? 'spinning' : ''} />
                <span>Test Connection</span>
              </button>
            </div>
          </div>
        </div>

        {/* ============================================================== */}
        {/* SECTION 5: Model Routing & Security Architecture                */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <ShieldCheck size={18} className="text-green" />
            <span className="section-card-title">Model Routing & Security Architecture</span>
          </div>
          <p className="section-card-desc">
            Orange AI employs a multi-tier dynamic routing pipeline for optimal speed, privacy, and reasoning depth:
          </p>

          <div className="routing-tiers-list">
            <div className="routing-tier-item">
              <span className="tier-tag">L1: Fast Local</span>
              <span className="tier-text">
                Direct deterministic tool execution, regex parsing, and system state queries without cloud calls.
              </span>
            </div>
            <div className="routing-tier-item">
              <span className="tier-tag">L2: Standard Cloud</span>
              <span className="tier-text">
                General user assistance, conversational replies, and single-turn task resolution via Orange API.
              </span>
            </div>
            <div className="routing-tier-item">
              <span className="tier-tag">L3: Autonomous Agent</span>
              <span className="tier-text">
                Multi-step autonomous execution, planner-dispatcher loops, and long-running agent workflows.
              </span>
            </div>
          </div>

          <div className="security-disclosure-box">
            <strong>Security Boundary:</strong> No model provider credentials or API keys are stored on or exposed to the desktop application shell. All authorization is managed exclusively by the isolated backend.
          </div>
        </div>

        {/* ============================================================== */}
        {/* SECTION 6: Data & Storage Paths                                 */}
        {/* ============================================================== */}
        <div className="settings-section-card">
          <div className="section-card-header">
            <HardDrive size={18} className="text-muted" />
            <span className="section-card-title">Runtime Storage & File Locations</span>
          </div>
          <p className="section-card-desc">
            Local persistent SQLite databases, audit logs, and configuration paths:
          </p>

          <div className="storage-paths-list">
            <div className="storage-path-row">
              <span className="path-label">Database:</span>
              <code>{runtimeInfo?.database_path || 'memory.db'}</code>
            </div>
            <div className="storage-path-row">
              <span className="path-label">User Data Directory:</span>
              <code>{runtimeInfo?.user_data_dir || '%LOCALAPPDATA%\\Orange AI'}</code>
            </div>
            <div className="storage-path-row">
              <span className="path-label">Python Supervisor PID:</span>
              <code>{runtimeInfo?.pid || 'active'}</code>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
