// src/components/HomeView.jsx - Home View with Dynamic Context & Reminders Strip
import React, { useState, useEffect, useCallback } from 'react';
import {
  FolderGit2,
  GitBranch,
  Bell,
  Clock,
  Plus,
  Trash2,
  RefreshCw,
  AlertCircle,
  X
} from 'lucide-react';
import WelcomeSection from './WelcomeSection';
import OrbArtwork from './OrbArtwork';
import Composer from './Composer';
import BrandTrigger from './BrandTrigger';
import {
  getStructuredMemory,
  getLatestReconciliations,
  listReminders,
  createReminder,
  cancelReminder
} from '../services/tauriBridge';
import '../styles/HomeView.css';

export default function HomeView({
  onToggleDrawer,
  isDrawerOpen,
  onSendMessage,
  userName = 'Sayan',
  onMemoryChanged
}) {
  const [activeTab, setActiveTab] = useState('projects'); // 'projects' | 'reminders'
  const [projects, setProjects] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(false);

  // Quick-add reminder state
  const [showAddReminder, setShowAddReminder] = useState(false);
  const [newReminderMsg, setNewReminderMsg] = useState('');
  const [newReminderDue, setNewReminderDue] = useState('');
  const [reminderLeadTime, setReminderLeadTime] = useState(0);
  const [addingReminder, setAddingReminder] = useState(false);
  const [contextError, setContextError] = useState(null);

  const getDefaultDueAt = () => {
    const d = new Date(Date.now() + 3600 * 1000);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const loadHomeContext = useCallback(async () => {
    setLoading(true);
    setContextError(null);
    try {
      const [structMemories, recons, rems] = await Promise.all([
        getStructuredMemory(),
        getLatestReconciliations(),
        listReminders({ include_completed: false })
      ]);

      // 1. Projects
      const projMemories = Array.isArray(structMemories)
        ? structMemories.filter((m) => (m.category || '').toLowerCase() === 'project')
        : [];

      const reconList = Array.isArray(recons) ? recons : [];

      const enrichedProjects = projMemories.map((pm) => {
        const pName = (pm.value || pm.key || '').toLowerCase();
        const matched = reconList.find((r) => {
          const rName = (r.workspace_name || '').toLowerCase();
          const rPath = (r.workspace_path || '').toLowerCase();
          return rName === pName || rPath.endsWith(pName) || rPath.includes(pName);
        });
        return {
          key: pm.key,
          name: pm.value,
          reconciliation: matched || null
        };
      });

      // Add recent active workspace reconciliations if not already present
      reconList.forEach((r) => {
        if (!enrichedProjects.some((ep) => (ep.name || '').toLowerCase() === (r.workspace_name || '').toLowerCase())) {
          enrichedProjects.push({
            key: r.workspace_name?.toLowerCase(),
            name: r.workspace_name,
            reconciliation: r,
            isReconOnly: true
          });
        }
      });

      setProjects(enrichedProjects);

      // 2. Reminders
      setReminders(Array.isArray(rems) ? rems : []);
    } catch (err) {
      console.warn('Failed to load home context:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHomeContext();
  }, [loadHomeContext]);

  const handleAddReminder = async (e) => {
    e.preventDefault();
    if (!newReminderMsg.trim() || addingReminder) return;

    let dueIso = newReminderDue;
    if (!dueIso) {
      dueIso = new Date(Date.now() + 3600 * 1000).toISOString();
    } else {
      try {
        dueIso = new Date(newReminderDue).toISOString();
      } catch (err) {
        dueIso = new Date(Date.now() + 3600 * 1000).toISOString();
      }
    }

    setAddingReminder(true);
    setContextError(null);
    try {
      await createReminder({
        message: newReminderMsg.trim(),
        due_at: dueIso,
        lead_time_minutes: reminderLeadTime
      });
      setNewReminderMsg('');
      setReminderLeadTime(0);
      setShowAddReminder(false);
      await loadHomeContext();
      if (typeof onMemoryChanged === 'function') {
        onMemoryChanged();
      }
    } catch (err) {
      setContextError(err.message || String(err));
    } finally {
      setAddingReminder(false);
    }
  };

  const handleCancelReminder = async (remId) => {
    try {
      await cancelReminder(remId);
      await loadHomeContext();
      if (typeof onMemoryChanged === 'function') {
        onMemoryChanged();
      }
    } catch (err) {
      setContextError(err.message || String(err));
    }
  };

  return (
    <div className="home-view-container">
      {/* Top-Left Brand Logo & Wordmark (Drawer Trigger) */}
      <div className="home-top-bar">
        <BrandTrigger onToggleDrawer={onToggleDrawer} isDrawerOpen={isDrawerOpen} />
      </div>

      {/* Main Hero Area */}
      <div className="home-hero-area">
        <div className="home-hero-left">
          <WelcomeSection userName={userName} />

          {/* Ongoing Context & Reminders Strip */}
          <div className="home-context-strip">
            <div className="context-strip-header">
              <div className="context-tab-group">
                <button
                  type="button"
                  className={`context-tab-btn ${activeTab === 'projects' ? 'is-active' : ''}`}
                  onClick={() => setActiveTab('projects')}
                >
                  <FolderGit2 size={13} />
                  <span>Active Projects</span>
                  {projects.length > 0 && <span className="tab-count">{projects.length}</span>}
                </button>
                <button
                  type="button"
                  className={`context-tab-btn ${activeTab === 'reminders' ? 'is-active' : ''}`}
                  onClick={() => setActiveTab('reminders')}
                >
                  <Bell size={13} />
                  <span>Upcoming Reminders</span>
                  {reminders.length > 0 && <span className="tab-count">{reminders.length}</span>}
                </button>
              </div>

              <div className="context-strip-actions">
                {activeTab === 'reminders' && (
                  <button
                    type="button"
                    className="btn-context-action"
                    onClick={() => {
                      setShowAddReminder((prev) => !prev);
                      if (!newReminderDue) setNewReminderDue(getDefaultDueAt());
                    }}
                    title="Add Reminder"
                  >
                    <Plus size={13} />
                    <span>New</span>
                  </button>
                )}
                <button
                  type="button"
                  className="btn-context-action"
                  onClick={loadHomeContext}
                  disabled={loading}
                  title="Refresh Context"
                >
                  <RefreshCw size={12} className={loading ? 'spinning' : ''} />
                </button>
              </div>
            </div>

            {contextError && (
              <div className="context-error-banner">
                <AlertCircle size={13} />
                <span>{contextError}</span>
                <button
                  type="button"
                  onClick={() => setContextError(null)}
                  style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }}
                >
                  <X size={12} />
                </button>
              </div>
            )}

            {/* Content Body */}
            <div className="context-strip-body">
              {activeTab === 'projects' && (
                <div className="context-projects-list">
                  {projects.length === 0 ? (
                    <div className="context-empty-hint">
                      No active projects tracked. Mention a project in chat to remember it.
                    </div>
                  ) : (
                    projects.map((proj, idx) => (
                      <div
                        key={`proj-${idx}`}
                        className="context-project-card"
                        onClick={() => onSendMessage(`What is the current status of project ${proj.name}?`)}
                        title="Click to discuss in chat"
                      >
                        <div className="context-project-main">
                          <span className="context-project-name">{proj.name}</span>
                          {proj.reconciliation?.git_branch && (
                            <span className="context-branch-badge">
                              <GitBranch size={10} />
                              <span>{proj.reconciliation.git_branch}</span>
                            </span>
                          )}
                          {proj.reconciliation?.status && (
                            <span className={`context-status-badge is-${proj.reconciliation.status.toLowerCase()}`}>
                              {proj.reconciliation.status}
                            </span>
                          )}
                          {proj.reconciliation?.uncommitted_changes?.length > 0 && (
                            <span className="context-uncommitted-badge">
                              {proj.reconciliation.uncommitted_changes.length} uncommitted
                            </span>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {activeTab === 'reminders' && (
                <div className="context-reminders-list">
                  {showAddReminder && (
                    <form className="context-add-reminder-form" onSubmit={handleAddReminder}>
                      <input
                        type="text"
                        className="context-reminder-input"
                        placeholder="Reminder message (e.g. Check test results)"
                        value={newReminderMsg}
                        onChange={(e) => setNewReminderMsg(e.target.value)}
                        autoFocus
                      />
                      <input
                        type="datetime-local"
                        className="context-reminder-datetime"
                        value={newReminderDue}
                        onChange={(e) => setNewReminderDue(e.target.value)}
                      />
                      <div className="reminder-lead-time-group">
                        <span className="lead-time-label">Alert:</span>
                        {[
                          { label: 'At due time', value: 0 },
                          { label: '5m early', value: 5 },
                          { label: '15m early', value: 15 },
                          { label: '30m early', value: 30 }
                        ].map((opt) => (
                          <button
                            key={opt.value}
                            type="button"
                            className={`lead-time-pill ${reminderLeadTime === opt.value ? 'is-selected' : ''}`}
                            onClick={() => setReminderLeadTime(opt.value)}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                      <button
                        type="submit"
                        className="btn-save-reminder"
                        disabled={addingReminder || !newReminderMsg.trim()}
                      >
                        {addingReminder ? 'Adding...' : 'Add'}
                      </button>
                      <button
                        type="button"
                        className="btn-cancel-reminder"
                        onClick={() => {
                          setShowAddReminder(false);
                          setNewReminderMsg('');
                          setReminderLeadTime(0);
                        }}
                      >
                        Cancel
                      </button>
                    </form>
                  )}

                  {reminders.length === 0 && !showAddReminder ? (
                    <div className="context-empty-hint">
                      No scheduled reminders. Click "+ New" to add one.
                    </div>
                  ) : (
                    reminders.map((rem, idx) => (
                      <div key={`rem-${rem.id || idx}`} className="context-reminder-card">
                        <div className="context-reminder-content">
                          <span className="context-reminder-msg">
                            {rem.message}
                            {rem.lead_time_minutes > 0 ? (
                              <span className="lead-time-badge"> ({rem.lead_time_minutes}m early)</span>
                            ) : null}
                          </span>
                          <span className="context-reminder-time">
                            <Clock size={11} />
                            <span>
                              {rem.due_at ? new Date(rem.due_at).toLocaleString([], {
                                month: 'short',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit'
                              }) : 'No date'}
                            </span>
                          </span>
                        </div>
                        <button
                          type="button"
                          className="btn-cancel-rem-item"
                          onClick={() => handleCancelReminder(rem.id)}
                          title="Cancel reminder"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Signature Orb Artwork */}
        <OrbArtwork />
      </div>

      {/* Floating Bottom Composer */}
      <Composer onSendMessage={onSendMessage} />
    </div>
  );
}
