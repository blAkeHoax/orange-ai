// src/components/views/MemoryView.jsx - Memory 2.0 Inspection & Management Workspace
import React, { useState, useEffect } from 'react';
import {
  Brain,
  RefreshCw,
  Search,
  Plus,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  X,
  Edit2,
  Check,
  Sparkles
} from 'lucide-react';
import {
  getMemoryStats,
  getStructuredMemory,
  getLegacyMemory,
  retractMemory,
  forgetMemory,
  rememberFact,
  createStructuredMemory,
  updateStructuredMemory
} from '../../services/tauriBridge';
import '../../styles/SecondaryViews.css';

const CATEGORIES = [
  { label: 'All', value: null },
  { label: 'Identity', value: 'identity' },
  { label: 'Projects', value: 'project' },
  { label: 'Tools', value: 'tool' },
  { label: 'Preferences', value: 'preference' },
  { label: 'Goals', value: 'goal' },
  { label: 'Relationships', value: 'relationship' },
  { label: 'Facts', value: 'fact' },
  { label: 'Legacy', value: 'legacy' }
];

const STRUCTURED_CATEGORY_OPTIONS = [
  { label: 'Identity (name, role)', value: 'identity' },
  { label: 'Project (current, workspace)', value: 'project' },
  { label: 'Tool (cli, editor, stack)', value: 'tool' },
  { label: 'Preference (style, theme)', value: 'preference' },
  { label: 'Goal (milestones, targets)', value: 'goal' },
  { label: 'Relationship (team, peers)', value: 'relationship' },
  { label: 'Fact (general facts)', value: 'fact' }
];

export default function MemoryView({ onMemoryChanged }) {
  const [stats, setStats] = useState(null);
  const [structuredMemories, setStructuredMemories] = useState([]);
  const [legacyMemories, setLegacyMemories] = useState([]);
  const [activeCategory, setActiveCategory] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);

  // Form states
  const [showAddForm, setShowAddForm] = useState(false);
  const [addMode, setAddMode] = useState('natural'); // 'natural' | 'structured'
  const [newFact, setNewFact] = useState('');
  const [structuredCategory, setStructuredCategory] = useState('project');
  const [structuredKey, setStructuredKey] = useState('');
  const [structuredVal, setStructuredVal] = useState('');
  const [savingFact, setSavingFact] = useState(false);

  // Inline editing state
  const [editingItem, setEditingItem] = useState(null); // { category, key, value }
  const [editValue, setEditValue] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState(null);

  // Confirmation & Feedback
  const [confirmTarget, setConfirmTarget] = useState(null); // { type, item }
  const [errorMsg, setErrorMsg] = useState(null);
  const [actionFeedback, setActionFeedback] = useState(null); // { type, message }

  const fetchAllMemoryData = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [sData, structData, legData] = await Promise.all([
        getMemoryStats(),
        getStructuredMemory(),
        getLegacyMemory(80)
      ]);
      setStats(sData || {});
      setStructuredMemories(Array.isArray(structData) ? structData : []);
      setLegacyMemories(Array.isArray(legData) ? legData : []);
    } catch (err) {
      console.error('Failed to load memory data:', err);
      setErrorMsg('Error loading persistent memory database.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAllMemoryData();
  }, []);

  const handleSaveNaturalFact = async (e) => {
    e.preventDefault();
    if (!newFact.trim() || savingFact) return;
    setSavingFact(true);
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      const res = await rememberFact(newFact.trim());
      if (res?.success) {
        setNewFact('');
        setShowAddForm(false);
        await fetchAllMemoryData();
        if (typeof onMemoryChanged === 'function') {
          onMemoryChanged();
        }
        if (res.mode === 'structured') {
          const storedStr = (res.stored || []).map((s) => `${s.category}/${s.key}`).join(', ');
          const retiredStr = (res.retired || []).map((r) => `${r.category}/${r.key}`).join(', ');
          let msg = `Classified as structured: stored [${storedStr || 'item'}]`;
          if (retiredStr) msg += `, retired [${retiredStr}]`;
          setActionFeedback({ type: 'success', message: msg });
        } else {
          setActionFeedback({ type: 'success', message: `Saved to legacy memories: "${res.fact || newFact}"` });
        }
      } else {
        setErrorMsg(res?.error || 'Failed to save fact.');
      }
    } catch (err) {
      setErrorMsg(`Failed to save memory: ${err.message || String(err)}`);
    } finally {
      setSavingFact(false);
    }
  };

  const handleSaveStructuredMemory = async (e) => {
    e.preventDefault();
    if (savingFact) return;
    const cat = structuredCategory.trim().toLowerCase();
    const key = structuredKey.trim().toLowerCase();
    const val = structuredVal.trim();

    if (!key || !val) {
      setErrorMsg('Key and value cannot be empty.');
      return;
    }

    setSavingFact(true);
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      const res = await createStructuredMemory({
        category: cat,
        key,
        value: val,
        confidence: 1.0
      });
      if (res?.success) {
        setStructuredKey('');
        setStructuredVal('');
        setShowAddForm(false);
        await fetchAllMemoryData();
        if (typeof onMemoryChanged === 'function') {
          onMemoryChanged();
        }
        setActionFeedback({
          type: 'success',
          message: `Created structured memory: [${res.memory?.category || cat}/${res.memory?.key || key}]`
        });
      } else {
        setErrorMsg(res?.error || 'Failed to create structured memory.');
      }
    } catch (err) {
      setErrorMsg(`Failed to create memory: ${err.message || String(err)}`);
    } finally {
      setSavingFact(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingItem || savingEdit) return;
    if (!editValue.trim()) {
      setEditError('Value cannot be empty.');
      return;
    }
    setSavingEdit(true);
    setEditError(null);
    try {
      const res = await updateStructuredMemory({
        category: editingItem.category,
        key: editingItem.key,
        value: editValue.trim()
      });
      if (res?.success) {
        setEditingItem(null);
        setEditValue('');
        await fetchAllMemoryData();
        if (typeof onMemoryChanged === 'function') {
          onMemoryChanged();
        }
        setActionFeedback({
          type: 'success',
          message: `Updated [${editingItem.category}/${editingItem.key}] successfully.`
        });
      } else {
        setEditError(res?.error || 'Failed to update memory.');
      }
    } catch (err) {
      setEditError(err.message || String(err));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleRetractStructured = async (mem) => {
    try {
      await retractMemory(mem.category, mem.key);
      setConfirmTarget(null);
      await fetchAllMemoryData();
      if (typeof onMemoryChanged === 'function') {
        onMemoryChanged();
      }
      setActionFeedback({
        type: 'success',
        message: `Retracted memory [${mem.category}/${mem.key}].`
      });
    } catch (err) {
      setErrorMsg(`Failed to retract memory: ${err.message || String(err)}`);
    }
  };

  const handleForgetLegacy = async (text) => {
    try {
      await forgetMemory(text.slice(0, 30));
      setConfirmTarget(null);
      await fetchAllMemoryData();
      if (typeof onMemoryChanged === 'function') {
        onMemoryChanged();
      }
      setActionFeedback({
        type: 'success',
        message: 'Deleted matching legacy memory.'
      });
    } catch (err) {
      setErrorMsg(`Failed to forget memory: ${err.message || String(err)}`);
    }
  };

  // Filter memories
  const filteredStructured = structuredMemories.filter((m) => {
    if (activeCategory && activeCategory !== 'legacy') {
      if ((m.category || '').toLowerCase() !== activeCategory.toLowerCase()) return false;
    }
    if (activeCategory === 'legacy') return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchKey = (m.key || '').toLowerCase().includes(q);
      const matchVal = (m.value || '').toLowerCase().includes(q);
      const matchCat = (m.category || '').toLowerCase().includes(q);
      if (!matchKey && !matchVal && !matchCat) return false;
    }
    return true;
  });

  const filteredLegacy = legacyMemories.filter((text) => {
    if (activeCategory && activeCategory !== 'legacy') return false;
    if (searchQuery.trim()) {
      return text.toLowerCase().includes(searchQuery.toLowerCase());
    }
    return true;
  });

  return (
    <div className="view-inner-container">
      {/* Header */}
      <div className="view-header-row">
        <div>
          <h2 className="view-title">Contextual Memory</h2>
          <p className="view-subtitle">
            Browse, search, edit, and manage persistent profile facts, project context, and knowledge.
          </p>
        </div>
        <div className="header-actions-group">
          <button
            className="action-btn-primary"
            onClick={() => {
              setShowAddForm((prev) => !prev);
              setErrorMsg(null);
              setActionFeedback(null);
            }}
            type="button"
          >
            <Plus size={14} />
            <span>Store Fact</span>
          </button>
          <button
            className="action-btn-secondary"
            onClick={fetchAllMemoryData}
            disabled={loading}
            type="button"
          >
            <RefreshCw size={14} className={loading ? 'spinning' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="error-banner">
          <AlertTriangle size={15} />
          <span>{errorMsg}</span>
          <button
            type="button"
            className="btn-dismiss-banner"
            onClick={() => setErrorMsg(null)}
            style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {actionFeedback && (
        <div className={`action-feedback-banner ${actionFeedback.type === 'error' ? 'is-error' : ''}`}>
          <CheckCircle2 size={15} />
          <span>{actionFeedback.message}</span>
          <button
            type="button"
            className="btn-dismiss-banner"
            onClick={() => setActionFeedback(null)}
            style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Stats Summary Cards */}
      <div className="memory-stats-grid">
        <div className="stat-card">
          <span className="stat-label">Structured Memories</span>
          <span className="stat-value">{stats?.structured_memories ?? stats?.structured_count ?? structuredMemories.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Legacy Facts</span>
          <span className="stat-value">{stats?.legacy_memories ?? stats?.legacy_count ?? legacyMemories.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Total Persistent Memories</span>
          <span className="stat-value">
            {stats?.total ?? ((stats?.structured_memories ?? stats?.structured_count ?? structuredMemories.length) + (stats?.legacy_memories ?? stats?.legacy_count ?? legacyMemories.length))}
          </span>
        </div>
      </div>

      {/* Add Memory Form with Mode Tabs */}
      {showAddForm && (
        <div className="memory-add-form">
          <div className="memory-form-mode-tabs">
            <button
              type="button"
              className={`form-mode-tab ${addMode === 'natural' ? 'is-active' : ''}`}
              onClick={() => setAddMode('natural')}
            >
              <Sparkles size={12} style={{ marginRight: 4 }} />
              Natural Language (Auto-Classify)
            </button>
            <button
              type="button"
              className={`form-mode-tab ${addMode === 'structured' ? 'is-active' : ''}`}
              onClick={() => setAddMode('structured')}
            >
              Explicit Structured Entry
            </button>
          </div>

          {addMode === 'natural' ? (
            <form onSubmit={handleSaveNaturalFact}>
              <div className="form-title">Enter Fact (Orange AI will classify into structured categories or legacy facts):</div>
              <div className="form-input-row" style={{ marginTop: 8 }}>
                <input
                  type="text"
                  className="form-text-input"
                  placeholder="e.g. My primary project is ZephyrCore on feature branch mesh"
                  value={newFact}
                  onChange={(e) => setNewFact(e.target.value)}
                  autoFocus
                />
                <button className="btn-save-fact" type="submit" disabled={savingFact || !newFact.trim()}>
                  {savingFact ? 'Saving...' : 'Remember Fact'}
                </button>
                <button
                  className="btn-cancel-fact"
                  type="button"
                  onClick={() => {
                    setShowAddForm(false);
                    setNewFact('');
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleSaveStructuredMemory}>
              <div className="form-title">Define Explicit Structured Memory:</div>
              <div className="form-grid-row" style={{ marginTop: 8 }}>
                <select
                  className="form-select"
                  value={structuredCategory}
                  onChange={(e) => setStructuredCategory(e.target.value)}
                >
                  {STRUCTURED_CATEGORY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  className="form-text-input"
                  placeholder="Key (e.g. name, current)"
                  value={structuredKey}
                  onChange={(e) => setStructuredKey(e.target.value)}
                />
                <input
                  type="text"
                  className="form-text-input"
                  placeholder="Value (e.g. ZephyrCore)"
                  value={structuredVal}
                  onChange={(e) => setStructuredVal(e.target.value)}
                />
                <button
                  className="btn-save-fact"
                  type="submit"
                  disabled={savingFact || !structuredKey.trim() || !structuredVal.trim()}
                >
                  {savingFact ? 'Saving...' : 'Create Memory'}
                </button>
                <button
                  className="btn-cancel-fact"
                  type="button"
                  onClick={() => {
                    setShowAddForm(false);
                    setStructuredKey('');
                    setStructuredVal('');
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Confirmation Dialog for Retraction */}
      {confirmTarget && (
        <div className="memory-confirm-dialog">
          <AlertTriangle size={16} className="text-orange" />
          <div className="confirm-text">
            Permanent Retraction:{' '}
            {confirmTarget.type === 'structured'
              ? `Retract [${confirmTarget.item.category.toUpperCase()}] "${confirmTarget.item.key}"?`
              : `Forget legacy fact "${confirmTarget.item.slice(0, 40)}..."?`}
          </div>
          <div className="confirm-buttons">
            <button
              className="btn-danger-confirm"
              onClick={() =>
                confirmTarget.type === 'structured'
                  ? handleRetractStructured(confirmTarget.item)
                  : handleForgetLegacy(confirmTarget.item)
              }
              type="button"
            >
              Confirm Retraction
            </button>
            <button
              className="btn-cancel-confirm"
              onClick={() => setConfirmTarget(null)}
              type="button"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="filter-search-bar">
        <div className="filter-pill-group">
          {CATEGORIES.map((c) => (
            <button
              key={c.label}
              className={`filter-pill ${activeCategory === c.value ? 'is-active' : ''}`}
              onClick={() => setActiveCategory(c.value)}
              type="button"
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="search-input-wrapper">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder="Search keys, values, or content..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Memory Cards Feed */}
      <div className="feed-scroll-container">
        {loading && structuredMemories.length === 0 && legacyMemories.length === 0 ? (
          <div className="feed-empty-state">
            <RefreshCw size={24} className="spinning text-orange" />
            <p>Loading persistent memories...</p>
          </div>
        ) : filteredStructured.length === 0 && filteredLegacy.length === 0 ? (
          <div className="feed-empty-state">
            <Brain size={28} className="text-muted" />
            <h3>No Memories Found</h3>
            <p>
              {searchQuery || activeCategory
                ? 'No memories match your search or category filter.'
                : 'No stored facts in persistent memory yet.'}
            </p>
          </div>
        ) : (
          <>
            {/* Structured Memories */}
            {filteredStructured.map((m, idx) => {
              const isEditing = editingItem && editingItem.category === m.category && editingItem.key === m.key;
              return (
                <div key={`struct-${idx}`} className="memory-card">
                  <div className="memory-card-header">
                    <span className={`category-tag is-${(m.category || '').toLowerCase()}`}>
                      {m.category}
                    </span>
                    <span className="memory-key-text">{m.key}</span>
                    {m.confidence !== undefined && (
                      <span className="memory-confidence-tag">
                        {Math.round(m.confidence * 100)}%
                      </span>
                    )}
                    <div className="memory-card-actions">
                      {!isEditing && (
                        <button
                          className="btn-edit-memory"
                          onClick={() => {
                            setEditingItem({ category: m.category, key: m.key, value: m.value });
                            setEditValue(m.value || '');
                            setEditError(null);
                          }}
                          title="Edit Value in place"
                          type="button"
                        >
                          <Edit2 size={12} />
                          <span>Edit</span>
                        </button>
                      )}
                      <button
                        className="btn-retract"
                        onClick={() => setConfirmTarget({ type: 'structured', item: m })}
                        title="Retract Fact"
                        type="button"
                      >
                        <Trash2 size={13} />
                        <span>Retract</span>
                      </button>
                    </div>
                  </div>

                  {isEditing ? (
                    <div className="memory-edit-box">
                      <input
                        type="text"
                        className="memory-edit-input"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        disabled={savingEdit}
                        autoFocus
                      />
                      {editError && <div className="memory-edit-error">{editError}</div>}
                      <div className="memory-edit-actions">
                        <button
                          className="btn-save-edit"
                          onClick={handleSaveEdit}
                          disabled={savingEdit || !editValue.trim()}
                          type="button"
                        >
                          <Check size={12} />
                          <span>{savingEdit ? 'Saving...' : 'Save'}</span>
                        </button>
                        <button
                          className="btn-cancel-edit"
                          onClick={() => {
                            setEditingItem(null);
                            setEditValue('');
                            setEditError(null);
                          }}
                          type="button"
                        >
                          <X size={12} />
                          <span>Cancel</span>
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="memory-value-text">{m.value}</div>
                  )}
                </div>
              );
            })}

            {/* Legacy Memories */}
            {filteredLegacy.map((text, idx) => (
              <div key={`leg-${idx}`} className="memory-card is-legacy">
                <div className="memory-card-header">
                  <span className="category-tag is-legacy">legacy</span>
                  <div className="memory-card-actions">
                    <button
                      className="btn-retract"
                      onClick={() => setConfirmTarget({ type: 'legacy', item: text })}
                      title="Forget Fact"
                      type="button"
                    >
                      <Trash2 size={13} />
                      <span>Forget</span>
                    </button>
                  </div>
                </div>
                <div className="memory-value-text">{text}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
