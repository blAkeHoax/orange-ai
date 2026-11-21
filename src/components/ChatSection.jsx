import React, { useState } from 'react';
import ConfirmationModal from './ConfirmationModal';

export default function ChatSection({
  messages,
  activeConfirmation,
  onSendMessage,
  onConfirmAction,
  isLoading
}) {
  const [input, setInput] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    onSendMessage(input.trim());
    setInput('');
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <span>Runtime Communication Test</span>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
          Line-delimited JSON-RPC 2.0 (UTF-8)
        </span>
      </div>

      <div className="chat-messages">
        {messages.length === 0 ? (
          <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-muted)' }}>
            <p style={{ fontSize: '15px', marginBottom: '6px' }}>Ready to communicate with Python runtime</p>
            <p style={{ fontSize: '12px' }}>Type a query (e.g., "what time is it" or "open notepad") to test.</p>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`message-bubble ${msg.role === 'user' ? 'message-user' : 'message-assistant'}`}
            >
              <div>{msg.content || msg.text}</div>
              {((msg.learned && msg.learned.length > 0) || (msg.retired && msg.retired.length > 0)) && (
                <div className="chat-memory-pills" style={{ marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {msg.learned?.map((item, lIdx) => (
                    <span
                      key={`l-${lIdx}`}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '11px',
                        padding: '2px 8px',
                        borderRadius: '9999px',
                        background: 'rgba(16, 185, 129, 0.12)',
                        color: '#10b981',
                        border: '1px solid rgba(16, 185, 129, 0.25)'
                      }}
                    >
                      Remembered: {item.category}/{item.key} ({item.value})
                    </span>
                  ))}
                  {msg.retired?.map((item, rIdx) => (
                    <span
                      key={`r-${rIdx}`}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '11px',
                        padding: '2px 8px',
                        borderRadius: '9999px',
                        background: 'rgba(239, 68, 68, 0.12)',
                        color: '#ef4444',
                        border: '1px solid rgba(239, 68, 68, 0.25)'
                      }}
                    >
                      Retired: {item.category}/{item.key}
                    </span>
                  ))}
                </div>
              )}
              <div className="message-meta">
                <span>{msg.role === 'user' ? 'You' : 'Orange AI (Python)'}</span>
                {msg.model && <span>• {msg.model}</span>}
                {msg.timestamp && <span>• {msg.timestamp}</span>}
              </div>
            </div>
          ))
        )}

        {isLoading && (
          <div className="message-bubble message-assistant">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div className="status-dot" style={{ backgroundColor: 'var(--orange-primary)', animation: 'pulse 1s infinite' }} />
              <span>Processing turn via background worker...</span>
            </div>
          </div>
        )}

        <ConfirmationModal
          confirmation={activeConfirmation}
          onConfirm={onConfirmAction}
        />
      </div>

      <form className="chat-composer" onSubmit={handleSubmit}>
        <input
          type="text"
          className="composer-input"
          placeholder="Ask Orange AI a question or command..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isLoading || !!activeConfirmation}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={isLoading || !input.trim() || !!activeConfirmation}
        >
          Send
        </button>
      </form>
    </div>
  );
}
