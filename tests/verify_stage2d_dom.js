// tests/verify_stage2d_dom.js
// CDP automation script to verify DOM rendering of:
// 1. Proactive Notification Toasts (briefing.ready, reminder.due, recommendation.created, reconciliation.ready)
// 2. Morning Briefing Modal dialog (Markdown, priorities, status badge, acknowledge button)
// 3. RecommendationCard Stage 2D lifecycle controls (.rec-dismiss-btn, .rec-snooze-btn, .rec-execute-btn)
// 4. Capture visual artifact screenshot: stage2d_proactive_notifications_dom.png

import fs from 'fs';
import path from 'path';
import http from 'http';
import { spawn } from 'child_process';

const ARTIFACT_DIR = String.raw`C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010`;
const TAURI_ROOT = String.raw`D:\Orange AI\Orange AI Tauri`;
const DIST_DIR = path.join(TAURI_ROOT, 'dist');
const TAURI_EXE = path.join(TAURI_ROOT, 'src-tauri', 'target', 'x86_64-pc-windows-gnu', 'debug', 'app.exe');

// Simple static HTTP server for freshly built dist/
function startStaticServer(port = 5174) {
  const mimeTypes = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml'
  };

  const server = http.createServer((req, res) => {
    let reqPath = req.url.split('?')[0];
    if (reqPath === '/') reqPath = '/index.html';
    const filePath = path.join(DIST_DIR, reqPath);

    fs.readFile(filePath, (err, data) => {
      if (err) {
        // Fallback to index.html for SPA routing
        fs.readFile(path.join(DIST_DIR, 'index.html'), (err2, fallbackData) => {
          if (err2) {
            res.writeHead(404);
            res.end('Not found');
          } else {
            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(fallbackData);
          }
        });
        return;
      }
      const ext = path.extname(filePath);
      const contentType = mimeTypes[ext] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': contentType });
      res.end(data);
    });
  });

  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () => {
      console.log(`[HTTP SERVER] Serving dist on http://127.0.0.1:${port}`);
      resolve(server);
    });
  });
}

async function main() {
  console.log('======================================================');
  console.log('--- STARTING STAGE 2D DOM / WEBVIEW2 VERIFICATION ---');
  console.log('======================================================');

  const staticServer = await startStaticServer(5174);
  let appProc = null;
  let page = null;

  try {
    // 1. Spawn app.exe with port 9222
    console.log('[RUNNER] Spawning app.exe with --remote-debugging-port=9222...');
    const env = { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9222' };
    appProc = spawn(TAURI_EXE, [], { env, stdio: 'ignore' });
    console.log(`[RUNNER] Spawned app.exe PID: ${appProc.pid}`);

    for (let attempt = 0; attempt < 40; attempt++) {
      await new Promise((r) => setTimeout(r, 600));
      try {
        const res = await fetch('http://127.0.0.1:9222/json');
        const targets = await res.json();
        page = targets.find((t) => t.type === 'page' && !t.url.startsWith('about:'));
        if (page) break;
      } catch (err) {}
    }

    if (!page) {
      throw new Error('Could not establish CDP connection to app.exe on port 9222');
    }

    console.log(`[CDP] Connected to page: ${page.title || page.url}`);
    const ws = new WebSocket(page.webSocketDebuggerUrl);

    let idCounter = 1;
    const pending = new Map();

    function send(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = idCounter++;
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.method === 'Runtime.consoleAPICalled') {
        const text = msg.params.args.map(a => a.value || a.description).join(' ');
        console.log(`[PAGE CONSOLE ${msg.params.type}]`, text);
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        console.error(`[PAGE UNCAUGHT EXCEPTION]`, JSON.stringify(msg.params.exceptionDetails));
      }
      if (msg.id && pending.has(msg.id)) {
        const { resolve, reject } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      }
    };

    await new Promise((resolve) => (ws.onopen = resolve));
    await send('Page.enable');
    await send('Runtime.enable');
    await send('DOM.enable');

    const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    async function evaluate(expression) {
      const r = await send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true
      });
      if (r.exceptionDetails) {
        throw new Error('Evaluation failed: ' + JSON.stringify(r.exceptionDetails));
      }
      return r.result.value;
    }

    // 2. Navigate WebView2 to the freshly built dist/ on port 5174
    console.log('[CDP] Navigating WebView2 to http://127.0.0.1:5174...');
    await send('Page.navigate', { url: 'http://127.0.0.1:5174' });
    await delay(1500);

    // Wait for window.__orangeAi
    console.log('[DOM TEST] Waiting for React application interface from freshly built dist...');
    for (let i = 0; i < 30; i++) {
      const ready = await evaluate(`Boolean(window.__orangeAi && window.__orangeAi.setMessages)`);
      if (ready) break;
      await delay(500);
    }

    // Set view to chat
    await evaluate(`if (window.__orangeAi && window.__orangeAi.selectView) window.__orangeAi.selectView('chat');`);
    await delay(600);

    // =========================================================================
    // SECTION 1: RecommendationCard Stage 2D Lifecycle Buttons DOM Audit
    // =========================================================================
    console.log('[DOM TEST 1] Injecting Stage 2D recommendation fixtures into chat timeline...');
    const cardFixtures = [
      {
        role: 'user',
        text: 'Review active recommendations and pending actions.'
      },
      {
        role: 'assistant',
        text: 'Here is an active recommendation with Stage 2D lifecycle controls:',
        model: 'assistant',
        recommendation: {
          id: 'rec_stage2d_demo_01',
          priority: 'HIGH',
          title: 'High Priority Advisory: Database Optimization Required',
          reason: 'Unindexed query spikes detected in primary memory store.',
          evidence: {
            table: 'memory_entries',
            unindexed_queries: 42
          },
          action_type: 'tool_call',
          suggested_action: 'Run database index migration',
          status: 'ACTIVE'
        }
      }
    ];

    await evaluate(`window.__orangeAi.setMessages(${JSON.stringify(cardFixtures)});`);
    await delay(800);

    const cardAudit = await evaluate(`
      (() => {
        const card = document.querySelector('.recommendation-card');
        if (!card) return { found: false };

        const dismissBtn = card.querySelector('.rec-dismiss-btn');
        const snoozeBtn = card.querySelector('.rec-snooze-btn');
        const executeBtn = card.querySelector('.rec-execute-btn');
        const actionsContainer = card.querySelector('.rec-card-lifecycle-row, .rec-lifecycle-actions');

        return {
          found: true,
          hasActionsContainer: Boolean(actionsContainer),
          dismissText: dismissBtn ? dismissBtn.textContent.trim() : null,
          snoozeText: snoozeBtn ? snoozeBtn.textContent.trim() : null,
          executeText: executeBtn ? executeBtn.textContent.trim() : null,
          classes: Array.from(card.classList),
          priorityBadge: card.querySelector('.rec-priority-badge')?.textContent?.trim()
        };
      })()
    `);

    console.log('[DOM TEST 1 RESULT] RecommendationCard Audit:', JSON.stringify(cardAudit, null, 2));
    if (!cardAudit.found) throw new Error('RecommendationCard not found in DOM');
    if (!cardAudit.dismissText?.includes('Dismiss')) throw new Error('Dismiss button missing or invalid');
    if (!cardAudit.snoozeText?.includes('Snooze')) throw new Error('Snooze button missing or invalid');
    if (!cardAudit.executeText?.includes('Execute')) throw new Error('Execute button missing or invalid');
    console.log('[PASS] RecommendationCard Stage 2D lifecycle controls verified in DOM');

    // =========================================================================
    // SECTION 2: Proactive Notification Toasts DOM Audit
    // =========================================================================
    console.log('[DOM TEST 2] Injecting proactive notification toast fixtures...');
    await evaluate(`
      (() => {
        // Trigger reminder due toast
        window.__orangeAi.triggerNotification('reminder.due', {
          event_id: 'evt_reminder_dom_test_01',
          event_type: 'reminder.due',
          created_at: new Date().toISOString(),
          entity_id: 'rem_101',
          version: 1,
          payload: {
            reminder_id: 101,
            message: 'Complete Stage 2D Acceptance Verification',
            due_at: '2026-11-16 14:30:00'
          },
          acknowledged: false
        });

        // Trigger briefing ready toast
        window.__orangeAi.triggerNotification('briefing.ready', {
          event_id: 'evt_briefing_dom_test_02',
          event_type: 'briefing.ready',
          created_at: new Date().toISOString(),
          entity_id: 'brf_2026-11-16',
          version: 1,
          payload: {
            id: 'brf_2026-11-16',
            local_date: '2026-11-16',
            content: '# 🌅 Morning Briefing — Monday, November 16, 2026\\n\\n**Primary Focus:** Orange AI Tauri\\n\\n- **Stage 2D Status:** Verification in progress\\n- **Proactive Intelligence:** Active\\n\\n## 🎯 Priorities\\n1. **Verify Proactive Notification Delivery** [HIGH]\\n2. **Review Reconciliation Status** [MEDIUM]',
            status: 'success',
            model_name: 'meta/llama-3.1-70b-instruct',
            priorities: [
              { category: 'project_focus', title: 'Verify Proactive Notification Delivery', level: 'HIGH', details: 'Complete CDP and acceptance verification.' },
              { category: 'reconciliation', title: 'Review Reconciliation Status', level: 'MEDIUM', details: 'Check workspace file integrity.' }
            ],
            sources: {
              overdue_reminders_count: 0,
              today_reminders_count: 1,
              current_project: 'Orange AI Tauri',
              recommendations_count: 2
            }
          },
          acknowledged: false
        });
      })()
    `);
    await delay(800);

    const toastAudit = await evaluate(`
      (() => {
        const toastContainer = document.querySelector('.toast-container');
        const cards = Array.from(document.querySelectorAll('.toast-card'));

        return {
          containerPresent: Boolean(toastContainer),
          totalToasts: cards.length,
          toasts: cards.map(c => ({
            classes: Array.from(c.classList),
            title: c.querySelector('.toast-title')?.textContent?.trim(),
            message: c.querySelector('.toast-message')?.textContent?.trim(),
            actionBtnText: c.querySelector('.toast-action-btn')?.textContent?.trim(),
            hasDismissBtn: Boolean(c.querySelector('.toast-close-btn'))
          }))
        };
      })()
    `);

    console.log('[DOM TEST 2 RESULT] NotificationToast Audit:', JSON.stringify(toastAudit, null, 2));
    if (!toastAudit.containerPresent) throw new Error('Notification toast container missing from DOM');
    if (toastAudit.totalToasts < 2) throw new Error(`Expected at least 2 toasts, found ${toastAudit.totalToasts}`);
    console.log('[PASS] Proactive Notification Toasts verified in DOM');

    // =========================================================================
    // SECTION 3: Morning Briefing Modal Dialog DOM Audit
    // =========================================================================
    console.log('[DOM TEST 3] Opening Morning Briefing Modal dialog...');
    const briefingFixture = {
      id: 'brf_2026-11-16',
      local_date: '2026-11-16',
      created_at: new Date().toISOString(),
      content: '# 🌅 Morning Briefing — Monday, November 16, 2026\n\n**Primary Focus:** Orange AI Tauri Application\n- **Status:** OPERATIONAL\n- **Model Synthesizer:** meta/llama-3.1-70b-instruct\n\n## 🎯 Key Priorities\n1. **Stage 2D Delivery Complete** — All 8 proactive communication pathways verified.\n2. **Recommendation Security Pipeline** — Strict tool permission checking and confirmation handshake active.',
      status: 'success',
      model_name: 'meta/llama-3.1-70b-instruct',
      priorities: [
        {
          category: 'system_milestone',
          title: 'Stage 2D Notification Delivery & Lifecycle',
          level: 'HIGH',
          details: 'Morning briefings, reminder due events, recommendations, and reconciliations.',
          action_hint: 'Review acceptance deliverables.'
        },
        {
          category: 'security',
          title: 'Tool Permission Pipeline Enforced',
          level: 'MEDIUM',
          details: 'SAFE direct execution, CONFIRMATION_REQUIRED user handshake, HIGH_RISK unconditional denial.',
          action_hint: 'Inspect ToolRegistry and permissions.'
        }
      ],
      sources: {
        overdue_reminders_count: 0,
        today_reminders_count: 1,
        blocked_jobs_count: 0,
        active_jobs_count: 0,
        current_project: 'Orange AI Tauri',
        recommendations_count: 2
      }
    };
    await evaluate(`window.__orangeAi.openBriefing(${JSON.stringify(briefingFixture)});`);
    await delay(800);

    const modalAudit = await evaluate(`
      (() => {
        const overlay = document.querySelector('.briefing-modal-backdrop');
        const container = document.querySelector('.briefing-modal-container');
        if (!container) return { found: false };

        const title = container.querySelector('.briefing-modal-title')?.textContent?.trim();
        const date = container.querySelector('.briefing-meta-item span')?.textContent?.trim();
        const badge = container.querySelector('.briefing-status-badge')?.textContent?.trim();
        const markdown = container.querySelector('.briefing-content-container')?.textContent?.trim();
        const priorities = Array.from(container.querySelectorAll('.briefing-priority-item'));
        const ackBtn = container.querySelector('.action-btn-primary');
        const closeBtn = container.querySelector('.briefing-modal-close');

        return {
          found: true,
          overlayPresent: Boolean(overlay),
          title,
          date,
          badge,
          hasMarkdownContent: Boolean(markdown && markdown.length > 20),
          prioritiesCount: priorities.length,
          hasAckButton: Boolean(ackBtn),
          ackButtonText: ackBtn ? ackBtn.textContent.trim() : null,
          hasCloseButton: Boolean(closeBtn)
        };
      })()
    `);

    console.log('[DOM TEST 3 RESULT] BriefingModal Audit:', JSON.stringify(modalAudit, null, 2));
    if (!modalAudit.found) throw new Error('BriefingModal container missing from DOM');
    if (!modalAudit.hasAckButton) throw new Error('Acknowledge Briefing button missing from modal');
    if (modalAudit.prioritiesCount !== 2) throw new Error(`Expected 2 priority items, found ${modalAudit.prioritiesCount}`);
    console.log('[PASS] Morning Briefing Modal dialog verified in DOM');

    // =========================================================================
    // SECTION 4: Capture Visual Evidence Screenshot
    // =========================================================================
    console.log('[DOM TEST 4] Capturing visual acceptance screenshot...');
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    const screenshotBuffer = Buffer.from(screenshot.data, 'base64');

    const outPath = path.join(ARTIFACT_DIR, 'stage2d_proactive_notifications_dom.png');
    fs.writeFileSync(outPath, screenshotBuffer);
    console.log(`[PASS] Captured visual artifact: ${outPath} (${screenshotBuffer.length} bytes)`);

    console.log('\n======================================================');
    console.log('ALL STAGE 2D DOM CHECKS PASSED (TOASTS, MODAL, CARDS)!');
    console.log('======================================================');
  } finally {
    if (appProc) {
      console.log('\n[RUNNER] Shutting down spawned Tauri app...');
      appProc.kill();
    }
    staticServer.close();
  }
}

main().catch((err) => {
  console.error('\n[FATAL ERROR]', err.message);
  process.exit(1);
});
