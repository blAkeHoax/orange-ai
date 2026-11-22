// src/components/views/PermissionsView.jsx - Safety Policy & Permission Tiers Workspace
import React, { useState, useEffect } from 'react';
import {
  Shield,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  Lock,
  User,
  AlertTriangle,
  Zap
} from 'lucide-react';
import { getPermissionsAudit, getSettings, updateSettings } from '../../services/tauriBridge';
import '../../styles/SecondaryViews.css';

export default function PermissionsView() {
  const [audit, setAudit] = useState({ admin_rights: false, tools: [] });
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [fullAccessMode, setFullAccessMode] = useState('supervised');

  const fetchAudit = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [auditData, settingsData] = await Promise.all([
        getPermissionsAudit(),
        getSettings().catch(() => null),
      ]);
      setAudit(auditData || { admin_rights: false, tools: [] });
      if (settingsData && settingsData.full_access_mode) {
        setFullAccessMode(settingsData.full_access_mode);
      }
    } catch (err) {
      console.error('Failed to load permissions audit:', err);
      setErrorMsg('Could not retrieve permissions policy audit.');
    } finally {
      setLoading(false);
    }
  };

  const handleModeChange = async (newMode) => {
    setFullAccessMode(newMode);
    try {
      await updateSettings({ full_access_mode: newMode });
      await fetchAudit();
    } catch (err) {
      console.error('Failed to update full access mode:', err);
      setErrorMsg('Failed to update system trust mode.');
    }
  };

  useEffect(() => {
    fetchAudit();
  }, []);

  const tools = audit.tools || [];
  const isAdmin = Boolean(audit.admin_rights);

  const filteredTools = tools.filter((t) => {
    if (riskFilter && t.risk_level !== riskFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = (t.name || '').toLowerCase().includes(q);
      const matchCat = (t.category || '').toLowerCase().includes(q);
      const matchReason = (t.reason || '').toLowerCase().includes(q);
      if (!matchName && !matchCat && !matchReason) return false;
    }
    return true;
  });

  return (
    <div className="view-inner-container">
      {/* Header */}
      <div className="view-header-row">
        <div>
          <h2 className="view-title">Permissions & Security Policy</h2>
          <p className="view-subtitle">
            Centralized execution policy, two trust modes, and audited tool enforcement rules.
          </p>
        </div>
        <button
          className="action-btn-secondary"
          onClick={fetchAudit}
          disabled={loading}
          type="button"
        >
          <RefreshCw size={14} className={loading ? 'spinning' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {errorMsg && (
        <div className="error-banner">
          <AlertTriangle size={15} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* System Execution Trust Mode Selector Card */}
      <div style={{
        background: 'var(--bg-secondary, #1a1a24)',
        borderRadius: '12px',
        padding: '18px 20px',
        marginBottom: '20px',
        border: '1px solid var(--border-color, #2a2a38)',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Zap size={20} style={{ color: fullAccessMode === 'unrestricted' ? '#ef4444' : '#f97316' }} />
            <div>
              <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: 'var(--text-primary, #ffffff)' }}>
                System Execution Trust Mode
              </h3>
              <p style={{ margin: '3px 0 0', fontSize: '12px', color: 'var(--text-secondary, #9ca3af)' }}>
                Control whether Orange AI executes shell, filesystem, and process tasks with supervised confirmation or full autonomous permission.
              </p>
            </div>
          </div>
          <span style={{
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.5px',
            padding: '5px 12px',
            borderRadius: '20px',
            background: fullAccessMode === 'unrestricted' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)',
            color: fullAccessMode === 'unrestricted' ? '#ef4444' : '#3b82f6',
            border: `1px solid ${fullAccessMode === 'unrestricted' ? 'rgba(239, 68, 68, 0.3)' : 'rgba(59, 130, 246, 0.3)'}`
          }}>
            {fullAccessMode === 'unrestricted' ? '⚡ UNRESTRICTED AUTONOMY' : '🛡️ SUPERVISED ACCESS'}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
          {/* Supervised Full Access Option */}
          <div
            onClick={() => handleModeChange('supervised')}
            style={{
              padding: '14px 16px',
              borderRadius: '8px',
              border: fullAccessMode === 'supervised' ? '2px solid #3b82f6' : '1px solid var(--border-color, #2a2a38)',
              background: fullAccessMode === 'supervised' ? 'rgba(59, 130, 246, 0.08)' : 'rgba(255, 255, 255, 0.02)',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
              <span style={{ fontWeight: 600, fontSize: '13px', color: fullAccessMode === 'supervised' ? '#60a5fa' : 'inherit', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <ShieldCheck size={16} />
                Supervised Full Access (Default)
              </span>
              {fullAccessMode === 'supervised' && (
                <span style={{ fontSize: '10px', background: '#3b82f6', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>ACTIVE</span>
              )}
            </div>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-secondary, #9ca3af)', lineHeight: '1.4' }}>
              Safe tools and workspace-scoped actions (D:\Orange AI, D:\CreatorPulse) execute automatically. Prompts confirmation for actions outside active workspaces or system changes.
            </p>
          </div>

          {/* Unrestricted Autonomous Mode Option */}
          <div
            onClick={() => handleModeChange('unrestricted')}
            style={{
              padding: '14px 16px',
              borderRadius: '8px',
              border: fullAccessMode === 'unrestricted' ? '2px solid #ef4444' : '1px solid var(--border-color, #2a2a38)',
              background: fullAccessMode === 'unrestricted' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255, 255, 255, 0.02)',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
              <span style={{ fontWeight: 600, fontSize: '13px', color: fullAccessMode === 'unrestricted' ? '#f87171' : 'inherit', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Zap size={16} />
                Unrestricted Autonomous Mode ("Full Access — No Prompts")
              </span>
              {fullAccessMode === 'unrestricted' && (
                <span style={{ fontSize: '10px', background: '#ef4444', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>ACTIVE</span>
              )}
            </div>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-secondary, #9ca3af)', lineHeight: '1.4' }}>
              Zero confirmation popups. All shell, file, clipboard, and process tasks execute immediately while logging every step to Activity. Catastrophic OS destruction (format C:, wiping System32) remains permanently blocked.
            </p>
          </div>
        </div>
      </div>

      {/* Process Privilege Status Banner */}
      <div className={`permissions-privilege-banner ${isAdmin ? 'is-elevated' : 'is-standard'}`}>
        <div className="privilege-header">
          {isAdmin ? (
            <ShieldAlert size={18} className="text-warning" />
          ) : (
            <User size={18} className="text-primary" />
          )}
          <span className="privilege-title">
            Process Privilege Level:{' '}
            {isAdmin ? 'Elevated: Windows Administrator Rights' : 'Standard User Privilege (UAC Standard)'}
          </span>
        </div>
        <div className="privilege-description">
          <strong>Immutable Security Policy:</strong> Operating system administrator privileges do
          NOT override safety constraints. Catastrophic OS destruction is permanently blocked regardless of mode.
        </div>
      </div>

      {/* 3 Locked Risk Classification Tiers */}
      <div className="risk-tiers-grid">
        <div className="risk-tier-card tier-safe">
          <div className="tier-header">
            <ShieldCheck size={18} className="text-green" />
            <span className="tier-name">Tier 1: SAFE</span>
          </div>
          <p className="tier-desc">
            Read-only queries, system metrics, clipboard reading, and non-destructive information retrieval.
          </p>
          <span className="tier-status-pill pill-allow">Execution: Direct / Immediate</span>
        </div>

        <div className="risk-tier-card tier-confirm">
          <div className="tier-header">
            <ShieldAlert size={18} className="text-orange" />
            <span className="tier-name">Tier 2: CONFIRMATION_REQUIRED</span>
          </div>
          <p className="tier-desc">
            Launching apps, PowerShell commands, modifying files, and system state-altering operations.
          </p>
          <span className="tier-status-pill pill-confirm">
            {fullAccessMode === 'unrestricted' ? 'Unrestricted Mode: Auto-Executed' : 'Supervised: Workspace Auto / External Confirmed'}
          </span>
        </div>

        <div className="risk-tier-card tier-highrisk">
          <div className="tier-header">
            <ShieldX size={18} className="text-red" />
            <span className="tier-name">Tier 3: HIGH_RISK / CATASTROPHIC</span>
          </div>
          <p className="tier-desc">
            Irreversible OS destruction (format C:, wiping System32, deleting memory.db directly).
          </p>
          <span className="tier-status-pill pill-deny">Execution: Permanently Denied</span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="filter-search-bar">
        <div className="filter-pill-group">
          {[
            { label: 'All Tiers', value: null },
            { label: 'Safe', value: 'SAFE' },
            { label: 'Confirmation Required', value: 'CONFIRMATION_REQUIRED' },
            { label: 'High Risk', value: 'HIGH_RISK' }
          ].map((f) => (
            <button
              key={f.label}
              className={`filter-pill ${riskFilter === f.value ? 'is-active' : ''}`}
              onClick={() => setRiskFilter(f.value)}
              type="button"
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="search-input-wrapper">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder="Search audited tools..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Tool Audit Table */}
      <div className="feed-scroll-container">
        {loading && tools.length === 0 ? (
          <div className="feed-empty-state">
            <RefreshCw size={24} className="spinning text-orange" />
            <p>Auditing tool permissions...</p>
          </div>
        ) : filteredTools.length === 0 ? (
          <div className="feed-empty-state">
            <Shield size={28} className="text-muted" />
            <h3>No Tools Matched</h3>
            <p>Try adjusting your search query or risk tier filter.</p>
          </div>
        ) : (
          <div className="tools-audit-table">
            <div className="audit-table-header">
              <span className="col-name">Tool Name</span>
              <span className="col-cat">Category</span>
              <span className="col-risk">Risk Level</span>
              <span className="col-status">Enforcement Status</span>
              <span className="col-reason">Reasoning</span>
            </div>
            {filteredTools.map((t, idx) => (
              <div key={idx} className="audit-table-row">
                <span className="col-name">
                  <code>{t.name}</code>
                </span>
                <span className="col-cat">
                  <span className="category-tag-subtle">{t.category}</span>
                </span>
                <span className="col-risk">
                  <span className={`risk-tag is-${(t.risk_level || '').toLowerCase()}`}>
                    {t.risk_level}
                  </span>
                </span>
                <span className="col-status">
                  <span className={`status-badge is-${(t.status || '').toLowerCase()}`}>
                    {t.status}
                  </span>
                </span>
                <span className="col-reason">{t.reason || 'Standard policy rule'}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
