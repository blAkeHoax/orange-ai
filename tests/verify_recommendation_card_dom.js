// tests/verify_recommendation_card_dom.js
// CDP automation script to verify DOM rendering of RecommendationCard across HIGH, MEDIUM, and LOW priorities.

import fs from 'fs';
import path from 'path';
import { spawn } from 'child_process';

const ARTIFACT_DIR = String.raw`C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010`;
const TAURI_ROOT = String.raw`D:\Orange AI\Orange AI Tauri`;
const TAURI_EXE = path.join(TAURI_ROOT, 'src-tauri', 'target', 'x86_64-pc-windows-gnu', 'debug', 'app.exe');

async function main() {
  console.log('======================================================');
  console.log('--- STARTING RECOMMENDATION CARD DOM VERIFICATION ---');
  console.log('======================================================');

  let appProc = null;
  let page = null;

  // 1. Check if an existing valid application page (NOT about:blank) is already on 9222
  try {
    const res = await fetch('http://127.0.0.1:9222/json');
    const targets = await res.json();
    page = targets.find((t) => t.type === 'page' && !t.url.startsWith('about:'));
  } catch (e) {}

  if (!page) {
    console.log('[RUNNER] Spawning app.exe with --remote-debugging-port=9222...');
    const env = { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9222' };
    appProc = spawn(TAURI_EXE, [], { env, stdio: 'ignore' });
    console.log(`[RUNNER] Spawned app.exe PID: ${appProc.pid}`);

    // Wait for CDP to become ready with actual application page
    for (let attempt = 0; attempt < 40; attempt++) {
      await new Promise((r) => setTimeout(r, 600));
      try {
        const res = await fetch('http://127.0.0.1:9222/json');
        const targets = await res.json();
        console.log(`[CDP ATTEMPT ${attempt}] Targets:`, targets.map((t) => ({ title: t.title, url: t.url, type: t.type })));
        page = targets.find((t) => t.type === 'page' && !t.url.startsWith('about:'));
        if (page) break;
      } catch (err) {}
    }
  }

  if (!page) {
    if (appProc) appProc.kill();
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

  try {
    // Wait for window.__orangeAi to be ready
    console.log('[DOM TEST] Waiting for React application interface...');
    for (let i = 0; i < 20; i++) {
      const ready = await evaluate(`Boolean(window.__orangeAi && window.__orangeAi.setMessages)`);
      if (ready) break;
      await delay(500);
    }

    // Set view to chat
    await evaluate(`if (window.__orangeAi && window.__orangeAi.selectView) window.__orangeAi.selectView('chat');`);
    await delay(600);

    // 2. Inject fixtures for HIGH, MEDIUM, and LOW priorities
    console.log('[DOM TEST] Injecting HIGH, MEDIUM, and LOW recommendation test fixtures...');
    const fixtures = [
      {
        role: 'user',
        text: 'Please check system advisories across all priority tiers.'
      },
      {
        role: 'assistant',
        text: 'Here are the current operational advisories by priority tier:',
        model: 'briefing',
        recommendation: {
          id: 'rec_audit_high_01',
          priority: 'HIGH',
          title: 'High Priority Advisory: Database Optimization Required',
          reason: 'Unindexed query spikes detected in primary memory store.',
          evidence: {
            table: 'memory_entries',
            unindexed_queries: 42,
            recommended_index: 'idx_memory_created'
          }
        }
      },
      {
        role: 'assistant',
        text: 'Medium priority recommendation:',
        model: 'briefing',
        recommendation: {
          id: 'rec_audit_medium_02',
          priority: 'MEDIUM',
          title: 'Medium Priority Advisory: Refresh Workspace Index',
          reason: 'Source tree manifest changed 2 hours ago without re-scan.',
          evidence: {
            manifest: 'package.json',
            time_since_sync: '2.4 hours'
          }
        }
      },
      {
        role: 'assistant',
        text: 'Low priority recommendation:',
        model: 'briefing',
        recommendation: {
          id: 'rec_audit_low_03',
          priority: 'LOW',
          title: 'Low Priority Advisory: Clean Temporary Logs',
          reason: '5 rotated log files present in temp folder exceeding 14 days.',
          evidence: {
            temp_dir: 'AppData/Local/Temp',
            expired_files: 5
          }
        }
      }
    ];

    await evaluate(`window.__orangeAi.setMessages(${JSON.stringify(fixtures)});`);
    await delay(800);

    // 3. Audit rendered DOM
    console.log('[DOM TEST] Auditing DOM structure for all 3 cards...');
    const domAudit = await evaluate(`
      (() => {
        const cards = Array.from(document.querySelectorAll('.recommendation-card'));
        const audits = cards.map(card => {
          const classes = Array.from(card.classList);
          const badge = card.querySelector('.rec-priority-badge');
          const badgeClasses = badge ? Array.from(badge.classList) : [];
          const badgeText = badge ? badge.textContent.trim() : '';
          const title = card.querySelector('.rec-action-title')?.textContent?.trim() || '';
          const reason = card.querySelector('.rec-reason-text')?.textContent?.trim() || '';

          // Check absence of fake lifecycle buttons
          const dismissBtn = card.querySelector('.rec-dismiss-btn');
          const snoozeBtn = card.querySelector('.rec-snooze-btn');
          const executeBtn = card.querySelector('.rec-execute-btn');

          return {
            classes,
            badgeClasses,
            badgeText,
            title,
            reason,
            hasFakeButtons: Boolean(dismissBtn || snoozeBtn || executeBtn)
          };
        });

        return {
          totalCards: cards.length,
          audits
        };
      })()
    `);

    console.log('[DOM AUDIT RESULT]', JSON.stringify(domAudit, null, 2));

    if (domAudit.totalCards !== 3) {
      throw new Error(`Expected 3 RecommendationCards, found ${domAudit.totalCards}`);
    }

    const [highCard, medCard, lowCard] = domAudit.audits;

    // Verify HIGH
    if (!highCard.classes.includes('priority-high')) {
      throw new Error(`High card missing 'priority-high' class. Classes: ${highCard.classes.join(', ')}`);
    }
    if (!highCard.badgeClasses.includes('is-high') || !highCard.badgeText.includes('HIGH PRIORITY')) {
      throw new Error(`High badge invalid: classes=${highCard.badgeClasses.join(', ')}, text='${highCard.badgeText}'`);
    }
    if (highCard.hasFakeButtons) throw new Error('High card has fake lifecycle buttons');
    console.log('[PASS] HIGH Priority Card DOM verified (.priority-high, .is-high, "HIGH PRIORITY")');

    // Verify MEDIUM
    if (!medCard.classes.includes('priority-medium')) {
      throw new Error(`Medium card missing 'priority-medium' class. Classes: ${medCard.classes.join(', ')}`);
    }
    if (!medCard.badgeClasses.includes('is-medium') || !medCard.badgeText.includes('MEDIUM PRIORITY')) {
      throw new Error(`Medium badge invalid: classes=${medCard.badgeClasses.join(', ')}, text='${medCard.badgeText}'`);
    }
    if (medCard.hasFakeButtons) throw new Error('Medium card has fake lifecycle buttons');
    console.log('[PASS] MEDIUM Priority Card DOM verified (.priority-medium, .is-medium, "MEDIUM PRIORITY")');

    // Verify LOW
    if (!lowCard.classes.includes('priority-low')) {
      throw new Error(`Low card missing 'priority-low' class. Classes: ${lowCard.classes.join(', ')}`);
    }
    if (!lowCard.badgeClasses.includes('is-low') || !lowCard.badgeText.includes('LOW PRIORITY')) {
      throw new Error(`Low badge invalid: classes=${lowCard.badgeClasses.join(', ')}, text='${lowCard.badgeText}'`);
    }
    if (lowCard.hasFakeButtons) throw new Error('Low card has fake lifecycle buttons');
    console.log('[PASS] LOW Priority Card DOM verified (.priority-low, .is-low, "LOW PRIORITY")');

    // 4. Capture Visual Artifact Screenshot
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(screenshot.data, 'base64');
    const artifactPath = path.join(ARTIFACT_DIR, 'stage2c_recommendation_priorities_dom.png');
    const localPath = path.join(TAURI_ROOT, 'stage2c_recommendation_priorities_dom.png');
    fs.writeFileSync(artifactPath, buffer);
    fs.writeFileSync(localPath, buffer);
    console.log(`[PASS] Captured visual artifact: ${artifactPath}`);

    console.log('\n======================================================');
    console.log('ALL RECOMMENDATION CARD DOM CHECKS PASSED (HIGH/MEDIUM/LOW)!');
    console.log('======================================================');
  } finally {
    try {
      ws.close();
    } catch (e) {}
    if (appProc) {
      console.log('[RUNNER] Shutting down spawned Tauri app...');
      appProc.kill();
    }
  }
}

main().catch((err) => {
  console.error('[FATAL ERROR in DOM verification]:', err);
  process.exit(1);
});
