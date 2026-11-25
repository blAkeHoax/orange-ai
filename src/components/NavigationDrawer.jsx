import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Home,
  MessageSquare,
  Zap,
  Brain,
  Activity,
  Shield,
  Wrench,
  Settings,
  X,
  Sun,
  Moon,
  Radio,
  RefreshCw,
  Check,
  Download,
  AlertCircle,
  Loader2
} from 'lucide-react';
import { getVersion } from '@tauri-apps/api/app';
import { check } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { prepareForUpdate } from '../services/tauriBridge';
import { useTheme } from '../context/ThemeContext';
import orbImg from '../assets/logo_orb_64.png';
import '../styles/NavigationDrawer.css';

const NAV_ITEMS = [
  { id: 'home', label: 'Home', icon: Home, description: 'Workspace overview' },
  { id: 'chat', label: 'Chat', icon: MessageSquare, description: 'Direct AI conversation' },
  { id: 'jobs', label: 'Agent Jobs', icon: Zap, description: 'Autonomous scheduled jobs' },
  { id: 'memory', label: 'Memory', icon: Brain, description: 'Persistent contextual recall' },
  { id: 'activity', label: 'Activity', icon: Activity, description: 'System telemetry & logs' },
  { id: 'permissions', label: 'Permissions', icon: Shield, description: 'Execution control policies' },
  { id: 'tools', label: 'Tools', icon: Wrench, description: 'Capabilities & integrations' },
  { id: 'settings', label: 'Settings', icon: Settings, description: 'Preferences & environment' },
];

export default function NavigationDrawer({
  isOpen,
  onClose,
  activeView,
  onSelectView,
  runtimeStatus = 'online',
  runtimePid
}) {
  const { theme, toggleTheme } = useTheme();

  // Updater states
  const [appVersion, setAppVersion] = useState('');
  const [updateStatus, setUpdateStatus] = useState('idle'); // 'idle' | 'checking' | 'uptodate' | 'available' | 'downloading' | 'error'
  const [targetVersion, setTargetVersion] = useState(null);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState('');

  const availableUpdateRef = useRef(null);
  const updateStatusRef = useRef(updateStatus);
  updateStatusRef.current = updateStatus;
  const resetTimerRef = useRef(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Fetch current application version with safe fallback
  useEffect(() => {
    let isMounted = true;
    async function fetchAppVersion() {
      try {
        const v = await getVersion();
        if (isMounted && v) {
          setAppVersion(v);
        }
      } catch (err) {
        console.debug('[NavigationDrawer] getVersion fallback:', err);
      }
    }
    fetchAppVersion();
    return () => {
      isMounted = false;
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    };
  }, []);

  const checkForUpdates = useCallback(async ({ silent = false } = {}) => {
    if (updateStatusRef.current === 'checking' || updateStatusRef.current === 'downloading') return;

    if (!silent) {
      setUpdateStatus('checking');
      setErrorMessage('');
    }

    try {
      const update = await check();
      if (update) {
        availableUpdateRef.current = update;
        setTargetVersion(update.version || 'new');
        setUpdateStatus('available');
      } else {
        if (!silent) {
          setUpdateStatus('uptodate');
          if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
          resetTimerRef.current = setTimeout(() => {
            setUpdateStatus('idle');
          }, 4000);
        }
      }
    } catch (err) {
      console.warn('[AutoUpdater] Update check failed:', err);
      if (!silent) {
        setUpdateStatus('error');
        setErrorMessage('No release feed yet');
        if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
        resetTimerRef.current = setTimeout(() => {
          setUpdateStatus('idle');
          setErrorMessage('');
        }, 4000);
      }
    }
  }, []);

  // Silent background update check 5 seconds after app startup
  useEffect(() => {
    const startupTimer = setTimeout(() => {
      checkForUpdates({ silent: true });
    }, 5000);
    return () => clearTimeout(startupTimer);
  }, [checkForUpdates]);

  const handleInstallUpdate = async () => {
    if (!availableUpdateRef.current || updateStatusRef.current === 'downloading') return;

    setUpdateStatus('downloading');
    setDownloadProgress(0);

    try {
      try {
        await prepareForUpdate();
      } catch (prepErr) {
        console.warn('[AutoUpdater] prepareForUpdate non-blocking error:', prepErr);
      }

      let downloaded = 0;
      let total = 0;

      await availableUpdateRef.current.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          total = event.data?.contentLength || 0;
        } else if (event.event === 'Progress') {
          downloaded += event.data?.chunkLength || 0;
          if (total > 0) {
            const pct = Math.min(100, Math.round((downloaded / total) * 100));
            setDownloadProgress(pct);
          }
        } else if (event.event === 'Finished') {
          setDownloadProgress(100);
        }
      });

      try {
        await relaunch();
      } catch (e) {
        console.debug('[AutoUpdater] Relaunch signal emitted:', e);
      }
    } catch (err) {
      console.error('[AutoUpdater] Failed to install update:', err);
      setUpdateStatus('error');
      setErrorMessage('Install failed');
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
      resetTimerRef.current = setTimeout(() => {
        setUpdateStatus('available');
        setErrorMessage('');
      }, 4000);
    }
  };

  const handleUpdateClick = () => {
    if (updateStatus === 'available') {
      handleInstallUpdate();
    } else if (updateStatus === 'idle' || updateStatus === 'error') {
      checkForUpdates({ silent: false });
    }
  };

  const handleItemClick = (id) => {
    onSelectView(id);
    onClose();
  };

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={`drawer-backdrop ${isOpen ? 'is-open' : ''}`}
        onClick={onClose}
        aria-hidden={!isOpen}
      />

      {/* Drawer Container */}
      <aside
        className={`navigation-drawer ${isOpen ? 'is-open' : ''}`}
        aria-label="Application navigation"
      >
        {/* Header */}
        <div className="drawer-header">
          <div className="drawer-brand">
            <img src={orbImg} alt="" className="drawer-orb-icon" />
            <div className="drawer-brand-text">
              <span className="drawer-title">Orange AI</span>
              <span className="drawer-subtitle">DESKTOP 2.0</span>
            </div>
          </div>
          <button
            className="drawer-close-btn"
            onClick={onClose}
            title="Close menu (Esc)"
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation List */}
        <nav className="drawer-nav">
          <ul className="drawer-nav-list">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = activeView === item.id;
              return (
                <li key={item.id} className="drawer-nav-li">
                  <button
                    className={`drawer-nav-item ${isActive ? 'is-active' : ''}`}
                    onClick={() => handleItemClick(item.id)}
                    type="button"
                  >
                    <span className="drawer-nav-icon-wrapper">
                      <Icon size={18} />
                    </span>
                    <span className="drawer-nav-label-group">
                      <span className="drawer-nav-label">{item.label}</span>
                      <span className="drawer-nav-desc">{item.description}</span>
                    </span>
                    {isActive && <span className="drawer-active-indicator" />}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="drawer-footer">
          {/* Check for Updates Button */}
          <button
            className={`drawer-update-btn ${updateStatus === 'available' ? 'is-available' : ''} ${updateStatus === 'downloading' ? 'is-downloading' : ''}`}
            onClick={handleUpdateClick}
            disabled={updateStatus === 'checking' || updateStatus === 'downloading'}
            title={
              updateStatus === 'available'
                ? `Install update v${targetVersion}`
                : updateStatus === 'error'
                ? errorMessage || 'No release feed yet'
                : appVersion
                ? `Current version: v${appVersion}`
                : 'Check for updates'
            }
            type="button"
          >
            <span className="drawer-update-content">
              {updateStatus === 'idle' && (
                <>
                  <span className="drawer-update-icon">
                    <RefreshCw size={15} />
                  </span>
                  <span className="drawer-update-label">Check for Updates</span>
                </>
              )}

              {updateStatus === 'checking' && (
                <>
                  <span className="drawer-update-icon">
                    <Loader2 size={15} className="spin-animate" />
                  </span>
                  <span className="drawer-update-label">Checking...</span>
                </>
              )}

              {updateStatus === 'uptodate' && (
                <>
                  <span className="drawer-update-icon is-uptodate">
                    <Check size={15} />
                  </span>
                  <span className="drawer-update-label">Up to date{appVersion ? ` (v${appVersion})` : ''}</span>
                </>
              )}

              {updateStatus === 'available' && (
                <>
                  <span className="drawer-update-icon is-available">
                    <Download size={15} />
                  </span>
                  <span className="drawer-update-label">Install v{targetVersion}</span>
                </>
              )}

              {updateStatus === 'downloading' && (
                <>
                  <span className="drawer-update-icon is-available">
                    <Loader2 size={15} className="spin-animate" />
                  </span>
                  <span className="drawer-update-label">
                    {downloadProgress > 0 ? `Downloading ${downloadProgress}%...` : 'Downloading...'}
                  </span>
                </>
              )}

              {updateStatus === 'error' && (
                <>
                  <span className="drawer-update-icon is-error">
                    <AlertCircle size={15} />
                  </span>
                  <span className="drawer-update-label">
                    {errorMessage || 'No release feed yet'}
                  </span>
                </>
              )}
            </span>

            {/* Version Badge or Accent Tag */}
            {updateStatus === 'idle' && appVersion && (
              <span className="drawer-update-badge">v{appVersion}</span>
            )}
            {updateStatus === 'available' && (
              <span className="drawer-update-badge is-available">NEW</span>
            )}
          </button>

          <button
            className="drawer-theme-toggle"
            onClick={toggleTheme}
            type="button"
          >
            <span className="theme-toggle-icon">
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </span>
            <span className="theme-toggle-label">
              {theme === 'dark' ? 'Switch to Light' : 'Switch to Dark'}
            </span>
          </button>

          <div className="drawer-status-pill">
            <span className="status-dot-pulse" />
            <span className="status-label">
              Python Engine: {runtimeStatus}
              {runtimePid ? ` (PID ${runtimePid})` : ''}
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}
