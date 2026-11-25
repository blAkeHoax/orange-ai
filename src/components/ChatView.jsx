// src/components/ChatView.jsx - Markdown-enabled rich chat timeline
import React, { useRef, useEffect, useState } from 'react';
import { User, Loader2, Sparkles, XCircle, Plus, Zap, Paperclip, Image as ImageIcon } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import BrandTrigger from './BrandTrigger';
import Composer from './Composer';
import CodeBlock from './CodeBlock';
import ToolResultCard from './ToolResultCard';
import RecommendationCard from './RecommendationCard';
import { openExternalUrl, createSkill } from '../services/tauriBridge';
import orbImg from '../assets/logo_orb_64.png';
import '../styles/ChatView.css';

// Markdown component mapping for semantic, secure typography
const markdownComponents = {
  code({ node, inline, className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    const codeString = String(children || '').replace(/\n$/, '');

    // Block code (explicit language or contains multiline code)
    if (!inline && (match || String(children).includes('\n'))) {
      return (
        <CodeBlock
          language={match ? match[1] : ''}
          code={codeString}
        />
      );
    }

    // Inline code
    return (
      <code className="inline-code" {...props}>
        {children}
      </code>
    );
  },
  h1: ({ children }) => <h1 className="md-h1">{children}</h1>,
  h2: ({ children }) => <h2 className="md-h2">{children}</h2>,
  h3: ({ children }) => <h3 className="md-h3">{children}</h3>,
  p: ({ children }) => <p className="md-p">{children}</p>,
  ul: ({ children }) => <ul className="md-ul">{children}</ul>,
  ol: ({ children }) => <ol className="md-ol">{children}</ol>,
  li: ({ children }) => <li className="md-li">{children}</li>,
  blockquote: ({ children }) => <blockquote className="md-blockquote">{children}</blockquote>,
  hr: () => <hr className="md-hr" />,
  table: ({ children }) => (
    <div className="md-table-wrapper">
      <table className="md-table">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="md-thead">{children}</thead>,
  tbody: ({ children }) => <tbody className="md-tbody">{children}</tbody>,
  tr: ({ children }) => <tr className="md-tr">{children}</tr>,
  th: ({ children }) => <th className="md-th">{children}</th>,
  td: ({ children }) => <td className="md-td">{children}</td>,
  a: ({ href, children }) => {
    // Security check: validate protocol
    const isSafe = href && (href.startsWith('http://') || href.startsWith('https://'));
    const handleClick = (e) => {
      e.preventDefault();
      if (isSafe) {
        openExternalUrl(href);
      }
    };
    return (
      <a
        href={isSafe ? href : '#'}
        onClick={handleClick}
        className="chat-link"
        target="_blank"
        rel="noopener noreferrer"
        title={isSafe ? href : 'Blocked unsafe link'}
      >
        {children}
      </a>
    );
  }
};

export default function ChatView({
  onToggleDrawer,
  isDrawerOpen,
  messages = [],
  onSendMessage,
  isExecuting = false,
  activeAdvisory = null,
  onDismissAdvisory,
  onSnoozeAdvisory,
  onExecuteAdvisory,
  onNewChat
}) {
  const messagesEndRef = useRef(null);
  const [savedSkillSlugs, setSavedSkillSlugs] = useState(new Set());

  const handleSaveSuggestedSkill = async (suggestion) => {
    if (!suggestion || !suggestion.suggested_slug) return;
    try {
      await createSkill({
        slug: suggestion.suggested_slug,
        name: suggestion.name || suggestion.suggested_slug,
        description: suggestion.description || 'Automated multi-step routine.',
        steps: suggestion.steps || [],
        prompt_template: suggestion.prompt_template || '',
      });
      setSavedSkillSlugs((prev) => new Set(prev).add(suggestion.suggested_slug));
    } catch (err) {
      console.error('Failed saving suggested skill:', err);
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isExecuting, activeAdvisory]);

  return (
    <div className="chat-view-container">
      {/* Top Bar with Brand Trigger and New Chat Action */}
      <div className="chat-top-bar">
        <BrandTrigger onToggleDrawer={onToggleDrawer} isDrawerOpen={isDrawerOpen} />
        <div className="chat-top-actions">
          <div className="chat-top-title">Active Conversation</div>
          {onNewChat && (
            <button
              type="button"
              className="chat-new-chat-btn"
              onClick={onNewChat}
              title="Start a new chat session"
            >
              <Plus size={13} className="chat-new-chat-icon" />
              <span>New Chat</span>
            </button>
          )}
        </div>
      </div>

      {/* Messages Timeline */}
      <div className="chat-timeline">
        {/* Dedicated Top-Level Advisory Slot */}
        {activeAdvisory && (
          <div className="chat-advisory-container">
            <RecommendationCard
              recommendation={activeAdvisory}
              onDismiss={onDismissAdvisory}
              onSnooze={onSnoozeAdvisory}
              onExecute={onExecuteAdvisory}
            />
          </div>
        )}

        {messages.length === 0 ? (
          <div className="chat-empty-state">
            <img src={orbImg} alt="" className="chat-empty-orb" />
            <div className="chat-empty-title">Orange AI Conversation</div>
            <div className="chat-empty-desc">
              Ask anything or issue a command. Your conversation history and context are preserved.
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={msg.id || `${msg.timestamp || 'msg'}-${idx}`} className={`chat-message-row is-${msg.role}`}>
              <div className="chat-avatar">
                {msg.role === 'user' ? (
                  <User size={16} />
                ) : (
                  <img src={orbImg} alt="AI" className="chat-ai-avatar" />
                )}
              </div>
              <div className="chat-message-bubble">
                <div className="chat-message-sender">
                  {msg.role === 'user' ? 'You' : 'Orange AI'}
                  {msg.model && <span className="chat-model-tag">{msg.model}</span>}
                  {msg.skill_used && (
                    <span className="chat-skill-tag" title={`Invoked skill: ${msg.skill_used}`}>
                      ⚡ Skill: /skill {msg.skill_used}
                    </span>
                  )}
                </div>

                {/* User plain text vs Assistant rich markdown */}
                {msg.role === 'user' ? (
                  <div className="chat-message-content is-user-text">
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className="chat-user-attachments">
                        {msg.attachments.map((att, aIdx) => (
                          <span key={aIdx} className="chat-user-attachment-pill" title={att.name}>
                            {att.kind === 'image' || att.kind === 'screenshot' ? (
                              <ImageIcon size={12} className="attachment-pill-icon" />
                            ) : (
                              <Paperclip size={12} className="attachment-pill-icon" />
                            )}
                            <span className="attachment-pill-name">{att.name}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="chat-user-prompt-text">{msg.text}</div>
                  </div>
                ) : (
                  <div className="chat-message-content is-assistant-content">
                    {msg.tool_result && (
                      <ToolResultCard {...msg.tool_result} />
                    )}
                    {msg.text && (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={markdownComponents}
                      >
                        {msg.text}
                      </ReactMarkdown>
                    )}
                    {msg.skill_suggestion && (
                      <div className="chat-skill-suggestion-banner">
                        <div className="skill-suggestion-info">
                          <Sparkles size={13} className="text-orange" />
                          <span>
                            Detected repeated routine: <strong>{msg.skill_suggestion.name || msg.skill_suggestion.suggested_slug}</strong>
                          </span>
                          <span className="skill-suggestion-slug">/skill {msg.skill_suggestion.suggested_slug}</span>
                        </div>
                        <button
                          type="button"
                          className="btn-save-skill-pill"
                          onClick={() => handleSaveSuggestedSkill(msg.skill_suggestion)}
                          disabled={savedSkillSlugs.has(msg.skill_suggestion.suggested_slug)}
                        >
                          {savedSkillSlugs.has(msg.skill_suggestion.suggested_slug) ? 'Saved as Skill!' : 'Save as Orange Skill'}
                        </button>
                      </div>
                    )}
                    {((msg.learned && msg.learned.length > 0) || (msg.retired && msg.retired.length > 0)) && (
                      <div className="chat-memory-pills">
                        {msg.learned?.map((item, lIdx) => (
                          <span
                            key={`learned-${lIdx}`}
                            className="chat-memory-pill is-learned"
                            title={`Remembered ${item.category}/${item.key}`}
                          >
                            <Sparkles size={11} className="pill-icon" />
                            <span>
                              Remembered: <strong>{item.category}/{item.key}</strong>
                              {item.value ? ` (${item.value})` : ''}
                            </span>
                          </span>
                        ))}
                        {msg.retired?.map((item, rIdx) => (
                          <span
                            key={`retired-${rIdx}`}
                            className="chat-memory-pill is-retired"
                            title={`Retired ${item.category}/${item.key}`}
                          >
                            <XCircle size={11} className="pill-icon" />
                            <span>
                              Retired: <del>{item.category}/{item.key}</del>
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {isExecuting && (
          <div className="chat-message-row is-assistant is-thinking">
            <div className="chat-avatar">
              <img src={orbImg} alt="AI" className="chat-ai-avatar" />
            </div>
            <div className="chat-message-bubble">
              <div className="chat-thinking-indicator">
                <Loader2 size={16} className="spinner" />
                <span>Orange AI is thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Bottom Composer */}
      <Composer onSendMessage={onSendMessage} disabled={isExecuting} />
    </div>
  );
}
