import React, { useState, useRef } from 'react';
import { Paperclip, SendHorizonal, Camera, X, FileText, Image as ImageIcon, Loader2 } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { captureScreenAttachment } from '../services/tauriBridge';
import '../styles/Composer.css';

export default function Composer({ onSendMessage, disabled = false }) {
  const [inputText, setInputText] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const { theme } = useTheme();
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);

  const placeholder =
    theme === 'light' ? 'Type a message to Orange AI...' : 'Type a message...';

  const processFile = (file) => {
    if (!file) return;
    const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB limit
    if (file.size > MAX_FILE_SIZE) {
      alert(`File "${file.name}" exceeds the 10 MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB). Please select a smaller file.`);
      return;
    }

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const isImage = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif'].includes(ext);

    const reader = new FileReader();
    reader.onload = (e) => {
      const base64Data = e.target.result;
      let kind = 'file';
      if (isImage) {
        kind = 'image';
      } else if (ext === 'pdf') {
        kind = 'pdf';
      } else if (['py', 'js', 'jsx', 'ts', 'tsx', 'rs', 'toml', 'json', 'yaml', 'yml', 'sql', 'ps1', 'sh'].includes(ext)) {
        kind = 'code';
      }

      const attachRecord = (finalBase64, finalSize) => {
        const newAttachment = {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          name: file.name,
          kind,
          mime_type: file.type || (kind === 'pdf' ? 'application/pdf' : 'application/octet-stream'),
          base64_data: finalBase64,
          size: finalSize,
          preview_meta:
            finalSize > 1024 * 1024
              ? `${(finalSize / (1024 * 1024)).toFixed(1)} MB`
              : `${Math.round(finalSize / 1024)} KB`,
        };
        setAttachments((prev) => [...prev, newAttachment]);
      };

      if (isImage && typeof window !== 'undefined' && window.Image) {
        const img = new Image();
        img.onload = () => {
          const maxDimension = 1600;
          if (img.width > maxDimension || img.height > maxDimension) {
            let width = img.width;
            let height = img.height;
            if (width > height) {
              if (width > maxDimension) {
                height = Math.round((height * maxDimension) / width);
                width = maxDimension;
              }
            } else {
              if (height > maxDimension) {
                width = Math.round((width * maxDimension) / height);
                height = maxDimension;
              }
            }
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            if (ctx) {
              ctx.drawImage(img, 0, 0, width, height);
              const downscaledBase64 = canvas.toDataURL(file.type || 'image/jpeg', 0.85);
              attachRecord(downscaledBase64, Math.round(downscaledBase64.length * 0.75));
              return;
            }
          }
          attachRecord(base64Data, file.size);
        };
        img.onerror = () => {
          attachRecord(base64Data, file.size);
        };
        img.src = base64Data;
      } else {
        attachRecord(base64Data, file.size);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    files.forEach(processFile);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleAttachmentClick = () => {
    fileInputRef.current?.click();
  };

  const handleCaptureScreen = async () => {
    if (disabled || isCapturing) return;
    setIsCapturing(true);
    try {
      const result = await captureScreenAttachment();
      if (result && (result.name || result.base64_data)) {
        const newAttachment = {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          name: result.name || `screenshot-${Date.now()}.png`,
          kind: 'screenshot',
          mime_type: result.mime_type || 'image/png',
          base64_data: result.base64_data,
          preview_meta: result.preview_meta || 'Screen',
          extracted_text: result.extracted_text,
          formatted_block: result.formatted_block,
        };
        setAttachments((prev) => [...prev, newAttachment]);
      }
    } catch (err) {
      console.error('[Composer] Screen capture error:', err);
    } finally {
      setIsCapturing(false);
    }
  };

  const removeAttachment = (idToRemove) => {
    setAttachments((prev) => prev.filter((a) => a.id !== idToRemove));
  };

  const handlePaste = (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type.indexOf('image') !== -1) {
        const file = item.getAsFile();
        if (file) {
          const namedFile = new File([file], `pasted-image-${Date.now()}.png`, { type: file.type });
          processFile(namedFile);
          e.preventDefault();
        }
      }
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer?.files || []);
    files.forEach(processFile);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    const trimmed = inputText.trim();
    if ((!trimmed && attachments.length === 0) || disabled) return;

    const prompt = trimmed || (attachments.length > 0 ? 'Analyze the attached file(s).' : '');
    onSendMessage(prompt, attachments);
    setInputText('');
    setAttachments([]);
  };

  const isReady = (inputText.trim().length > 0 || attachments.length > 0) && !disabled;

  return (
    <div
      className={`composer-container ${isDragging ? 'is-dragging-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onPaste={handlePaste}
    >
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".txt,.md,.log,.json,.csv,.py,.js,.jsx,.ts,.tsx,.rs,.toml,.yaml,.yml,.html,.css,.sql,.ps1,.pdf,.png,.jpg,.jpeg,.webp"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      {/* Removable Attachment Chips */}
      {attachments.length > 0 && (
        <div className="composer-attachments-bar">
          {attachments.map((att) => (
            <div key={att.id} className="composer-attachment-chip">
              {att.kind === 'image' || att.kind === 'screenshot' ? (
                <ImageIcon size={13} className="chip-icon text-orange" />
              ) : (
                <FileText size={13} className="chip-icon" />
              )}
              <span className="chip-name" title={att.name}>
                {att.name}
              </span>
              {att.preview_meta && <span className="chip-badge">{att.preview_meta}</span>}
              <button
                type="button"
                className="chip-remove-btn"
                onClick={() => removeAttachment(att.id)}
                title="Remove attachment"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      <form className="composer-form" onSubmit={handleSubmit}>
        <div className="composer-pill">
          {/* Attachment Paperclip Button */}
          <button
            className="composer-action-btn btn-attachment"
            type="button"
            onClick={handleAttachmentClick}
            title="Attach file (code, docs, logs, PDF, images)"
            disabled={disabled}
          >
            <Paperclip size={18} />
          </button>

          {/* Capture Screen Button */}
          <button
            className="composer-action-btn btn-capture-screen"
            type="button"
            onClick={handleCaptureScreen}
            title="Capture screen with local OCR"
            disabled={disabled || isCapturing}
          >
            {isCapturing ? <Loader2 size={18} className="animate-spin text-orange" /> : <Camera size={18} />}
          </button>

          {/* Input Field */}
          <input
            ref={inputRef}
            className="composer-input"
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={attachments.length > 0 ? 'Add instructions or press Enter to analyze...' : placeholder}
            disabled={disabled}
            autoFocus
          />
        </div>

        {/* Separate Orange Glowing Send Button */}
        <button
          className={`composer-send-btn ${isReady ? 'is-ready' : ''}`}
          type="submit"
          disabled={!isReady}
          title="Send message"
        >
          <SendHorizonal size={18} className="send-icon" />
        </button>
      </form>
    </div>
  );
}
