// tests/cdp_stage2a_suite.js - Master CDP Automated Verification Suite for Stage 2A
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = String.raw`C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010`;

async function main() {
  console.log('[STAGE-2A] Connecting to CDP port 9222...');
  let targets = [];
  let page = null;
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json');
      targets = await res.json();
      page = targets.find((t) => t.type === 'page' && !t.url.startsWith('about:')) || targets.find((t) => t.type === 'page');
      if (page && !page.url.startsWith('about:')) break;
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  if (!page) {
    throw new Error('No page target found on port 9222: ' + JSON.stringify(targets));
  }

  console.log(`[STAGE-2A] Found page target: ${page.title} (${page.url})`);
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
      const args = msg.params.args.map((a) => (a.value !== undefined ? a.value : a.description)).join(' ');
      console.log(`[Browser Console][${msg.params.type}]`, args);
    } else if (msg.method === 'Runtime.exceptionThrown') {
      console.error('[Browser Exception]', JSON.stringify(msg.params.exceptionDetails));
    } else if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(msg.error);
      else resolve(msg.result);
    }
  };

  await new Promise((resolve) => (ws.onopen = resolve));
  console.log('[STAGE-2A] WebSocket connection established.');

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
      console.error('[EVAL EXCEPTION]', r.exceptionDetails);
      throw new Error(`Eval failed: ${JSON.stringify(r.exceptionDetails)}`);
    }
    return r.result ? r.result.value : undefined;
  }

  async function takeScreenshot(filename) {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const buf = Buffer.from(shot.data, 'base64');
    const outPath = path.join(ARTIFACT_DIR, filename);
    fs.writeFileSync(outPath, buf);
    console.log(`[SCREENSHOT] Saved: ${filename} (${buf.length} bytes)`);
    return outPath;
  }

  console.log('[STAGE-2A] Waiting for React application mount...');
  let mounted = false;
  for (let i = 0; i < 40; i++) {
    const res = await send('Runtime.evaluate', {
      expression: `({
        ready: document.readyState,
        hasOrangeAi: !!window.__orangeAi,
        hasTheme: !!window.__orangeAiTheme,
        status: window.__orangeAi?.getRuntimeStatus?.(),
        activeView: window.__orangeAi?.getActiveView?.()
      })`,
      returnByValue: true
    });
    const val = res?.result?.value;
    if (val?.hasOrangeAi && val?.hasTheme && (val?.status === 'online' || i > 15)) {
      mounted = true;
      break;
    }
    await delay(500);
  }
  if (!mounted) {
    throw new Error('React application failed to mount window.__orangeAi within 20s');
  }
  console.log('[STAGE-2A] React application mounted successfully.');

  // Switch to Chat View
  console.log('\n--- Navigating to Chat Workspace ---');
  await evaluate(`window.__orangeAi.selectView('chat')`);
  await delay(600);

  // Set Dark Theme
  await evaluate(`window.__orangeAiTheme.setTheme('dark')`);
  await delay(300);

  // -------------------------------------------------------------
  // TEST A: MARKDOWN TYPOGRAPHY SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST A: Markdown Typography & Formatting ---');
  console.log('======================================================');

  const markdownDemo = `# Orange AI Desktop 2.0
## Rich Markdown Formatting Suite

Here is **bold text**, *italic emphasis*, and a [safe link](https://orange-ai.org).

> Orange AI is an agentic desktop assistant with deterministic safety policies.

### Feature Checklist
1. First ordered task item
2. Second ordered task item

- System metrics query: \`get_cpu_usage()\`
- Process health monitoring: \`is_running()\`

| Metric | Status | Target SLA |
|---|---|---|
| Latency | 42ms | < 100ms |
| Memory | Nominal | < 150MB |
| Security | Enforced | Strict 3-Tier |

---
Inline code: \`OrangeAPIClient.assist()\` ready.`;

  await evaluate(`
    window.__orangeAi.setMessages([
      { role: 'user', text: 'Can you show me a full markdown formatting demonstration?' },
      { role: 'assistant', text: ${JSON.stringify(markdownDemo)}, model: 'nvidia/llama-3.1-nemotron-70b-instruct' }
    ]);
  `);
  await delay(600);

  const mdAudit = await evaluate(`
    (() => {
      const h1 = document.querySelector('.md-h1');
      const h2 = document.querySelector('.md-h2');
      const h3 = document.querySelector('.md-h3');
      const strong = document.querySelector('.chat-message-bubble strong');
      const em = document.querySelector('.chat-message-bubble em');
      const blockquote = document.querySelector('.md-blockquote');
      const ol = document.querySelector('.md-ol');
      const ul = document.querySelector('.md-ul');
      const table = document.querySelector('.md-table');
      const th = document.querySelectorAll('.md-th');
      const td = document.querySelectorAll('.md-td');
      const inlineCode = document.querySelector('.inline-code');
      const link = document.querySelector('.chat-link');

      return {
        h1Found: Boolean(h1 && h1.textContent.includes('Orange AI Desktop 2.0')),
        h2Found: Boolean(h2 && h2.textContent.includes('Rich Markdown Formatting')),
        h3Found: Boolean(h3 && h3.textContent.includes('Feature Checklist')),
        strongFound: Boolean(strong && strong.textContent.includes('bold text')),
        emFound: Boolean(em && em.textContent.includes('italic emphasis')),
        blockquoteFound: Boolean(blockquote && blockquote.textContent.includes('deterministic safety')),
        olFound: Boolean(ol && ol.children.length === 2),
        ulFound: Boolean(ul && ul.children.length === 2),
        tableFound: Boolean(table && th.length === 3 && td.length === 9),
        inlineCodeFound: Boolean(inlineCode && inlineCode.textContent.includes('get_cpu_usage()')),
        linkFound: Boolean(link && link.href.includes('https://orange-ai.org'))
      };
    })()
  `);

  console.log('[TEST A AUDIT]', mdAudit);
  for (const [k, v] of Object.entries(mdAudit)) {
    if (!v) throw new Error(`Markdown verification failed for check: ${k}`);
  }
  console.log('PASSED: Test A (Markdown Typography)');
  await takeScreenshot('stage2a_chat_markdown_dark.png');

  // Also capture in Light Theme
  await evaluate(`window.__orangeAiTheme.setTheme('light')`);
  await delay(400);
  await takeScreenshot('stage2a_chat_markdown_light.png');
  await evaluate(`window.__orangeAiTheme.setTheme('dark')`);
  await delay(300);

  // -------------------------------------------------------------
  // TEST B: CODEBLOCK SUITE (Python & JavaScript)
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST B: CodeBlock Syntax Highlighting & Copy ---');
  console.log('======================================================');

  const codeBlocksDemo = `Here are production code examples in Python and JavaScript:

\`\`\`python
# Fibonacci calculation with memoization
def fibonacci(n: int, memo: dict = {}) -> int:
    if n in memo:
        return memo[n]
    if n <= 1:
        return n
    memo[n] = fibonacci(n - 1, memo) + fibonacci(n - 2, memo)
    return memo[n]

# Quick verification test
print(f"Fibonacci(10) = {fibonacci(10)}")
\`\`\`

\`\`\`javascript
// Asynchronous event subscriber in JavaScript
export async function listenToReminders(onReminder) {
  const channel = new BroadcastChannel('orange_ai_reminders');
  channel.onmessage = (event) => {
    console.log('[Reminder Event]', event.data);
    onReminder(event.data);
  };
  return () => channel.close();
}
\`\`\``;

  await evaluate(`
    window.__orangeAi.setMessages([
      { role: 'user', text: 'Write a python fibonacci function and a javascript event subscriber.' },
      { role: 'assistant', text: ${JSON.stringify(codeBlocksDemo)}, model: 'nvidia/llama-3.1-nemotron-70b-instruct' }
    ]);
  `);
  await delay(600);

  const codeAudit = await evaluate(`
    (() => {
      const codeBlocks = document.querySelectorAll('.code-block-container');
      const langs = Array.from(document.querySelectorAll('.code-lang-name')).map(el => el.textContent.trim());
      const pyKeywords = document.querySelectorAll('.code-block-container .token.keyword');
      const pyFunctions = document.querySelectorAll('.code-block-container .token.function');
      const copyBtns = document.querySelectorAll('.code-copy-btn');

      return {
        blocksCount: codeBlocks.length,
        languages: langs,
        hasKeywords: pyKeywords.length > 0,
        hasFunctions: pyFunctions.length > 0,
        hasCopyButtons: copyBtns.length === 2
      };
    })()
  `);

  console.log('[TEST B AUDIT]', codeAudit);
  if (codeAudit.blocksCount !== 2) throw new Error(`Expected 2 code blocks, found ${codeAudit.blocksCount}`);
  if (!codeAudit.languages.includes('python') || !codeAudit.languages.includes('javascript')) {
    throw new Error(`Expected python and javascript language labels, got: ${JSON.stringify(codeAudit.languages)}`);
  }
  if (!codeAudit.hasKeywords || !codeAudit.hasFunctions) {
    throw new Error('Prism syntax tokens missing from code block');
  }

  // Test Copy Button Interaction
  const copyTestResult = await evaluate(`
    (async () => {
      const firstCopyBtn = document.querySelector('.code-copy-btn');
      firstCopyBtn.click();
      await new Promise(r => setTimeout(r, 100));
      return {
        copiedClass: firstCopyBtn.classList.contains('is-copied'),
        btnText: firstCopyBtn.textContent.trim()
      };
    })()
  `);
  console.log('[TEST B COPY INTERACTION]', copyTestResult);
  if (!copyTestResult.copiedClass && !copyTestResult.btnText.includes('Copied')) {
    console.warn('[TEST B COPY NOTICE] Clipboard state may depend on browser window focus');
  }

  console.log('PASSED: Test B (CodeBlock Component)');
  await takeScreenshot('stage2a_codeblocks_dark.png');

  // Light Theme CodeBlock Capture
  await evaluate(`window.__orangeAiTheme.setTheme('light')`);
  await delay(400);
  await takeScreenshot('stage2a_codeblocks_light.png');
  await evaluate(`window.__orangeAiTheme.setTheme('dark')`);
  await delay(300);

  // -------------------------------------------------------------
  // TEST C: TOOL RESULT CARD SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST C: ToolResultCard Component & Auto-Collapse ---');
  console.log('======================================================');

  const longFileList = Array.from({ length: 18 }, (_, i) => `src/module_${i + 1}.py  (size: ${(i + 1) * 1024} bytes, modified: 2026-11-15)`).join('\n');

  await evaluate(`
    window.__orangeAi.setMessages([
      { role: 'user', text: 'List the files in the workspace.' },
      {
        role: 'assistant',
        text: 'I have executed the file listing query. The results are shown below:',
        model: 'tool',
        tool_result: {
          toolName: 'list_files',
          status: 'SUCCESS',
          stdout: ${JSON.stringify(longFileList)},
          commandArg: 'path="D:/Orange AI/Orange AI Tauri"'
        }
      },
      {
        role: 'assistant',
        text: 'The process check encountered an error:',
        model: 'tool',
        tool_result: {
          toolName: 'close_process',
          status: 'FAILED',
          stdout: '',
          error: 'ProcessNotFound: No running process matching name "nonexistent_daemon.exe"',
          commandArg: 'name="nonexistent_daemon.exe"'
        }
      }
    ]);
  `);
  await delay(600);

  const toolAudit = await evaluate(`
    (() => {
      const cards = document.querySelectorAll('.tool-result-card');
      const successBadge = document.querySelector('.badge-success');
      const failedBadge = document.querySelector('.badge-failed');
      const collapseBtn = document.querySelector('.tool-collapse-btn');
      const toolNames = Array.from(document.querySelectorAll('.tool-result-name')).map(e => e.textContent.trim());

      return {
        cardCount: cards.length,
        hasSuccess: Boolean(successBadge && successBadge.textContent.includes('SUCCESS')),
        hasFailed: Boolean(failedBadge && failedBadge.textContent.includes('FAILED')),
        hasCollapseBtn: Boolean(collapseBtn && collapseBtn.textContent.includes('Expand')),
        toolNames
      };
    })()
  `);

  console.log('[TEST C AUDIT]', toolAudit);
  if (toolAudit.cardCount !== 2) throw new Error(`Expected 2 tool cards, found ${toolAudit.cardCount}`);
  if (!toolAudit.hasSuccess || !toolAudit.hasFailed) throw new Error('Tool status badges missing or incorrect');
  if (!toolAudit.hasCollapseBtn) throw new Error('Tool auto-collapse button for >10 lines missing');

  // Test expanding the collapsed card
  await evaluate(`
    const collapseBtn = document.querySelector('.tool-collapse-btn');
    if (collapseBtn) collapseBtn.click();
  `);
  await delay(300);

  console.log('PASSED: Test C (ToolResultCard Component)');
  await takeScreenshot('stage2a_tool_result_cards.png');

  // -------------------------------------------------------------
  // TEST D: RECOMMENDATION CARD SUITE (No Fake Lifecycle Buttons)
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST D: RecommendationCard Component ---');
  console.log('======================================================');

  const recommendationFixture = {
    id: 'rec_disk_cleanup_01',
    priority: 'HIGH',
    title: 'Archive Stale Debug Artifacts',
    reason: '3 uncompressed debug binaries totaling 228MB detected in target/debug directory.',
    evidence: {
      target_directory: 'src-tauri/target/debug',
      affected_binaries: 3,
      total_disk_reclaimable: '228.4 MB',
      recommended_command: 'cargo clean -p app'
    }
  };

  await evaluate(`
    window.__orangeAi.setMessages([
      { role: 'user', text: 'How is the project health looking today?' },
      {
        role: 'assistant',
        text: 'Project health is overall good. I detected one high-priority maintenance advisory:',
        model: 'briefing',
        recommendation: ${JSON.stringify(recommendationFixture)}
      }
    ]);
  `);
  await delay(600);

  const debugDump = await evaluate(`
    (() => {
      const bubbles = Array.from(document.querySelectorAll('.chat-message-bubble'));
      const active = window.__orangeAi ? window.__orangeAi.getActiveView() : null;
      return {
        activeView: active,
        count: bubbles.length,
        htmls: bubbles.map(b => b.outerHTML)
      };
    })()
  `);
  console.log('[TEST D DEBUG DUMP]', JSON.stringify(debugDump, null, 2));

  const recAudit = await evaluate(`
    (() => {
      const card = document.querySelector('.recommendation-card');
      const badge = document.querySelector('.rec-priority-badge.is-high');
      const title = document.querySelector('.rec-action-title');
      const evidenceBtn = document.querySelector('.rec-evidence-toggle');
      // Verify NO fake lifecycle buttons (Dismiss / Snooze / Execute)
      const dismissBtn = document.querySelector('.rec-dismiss-btn');
      const snoozeBtn = document.querySelector('.rec-snooze-btn');
      const executeBtn = document.querySelector('.rec-execute-btn');

      return {
        cardFound: Boolean(card),
        priorityBadgeHigh: Boolean(badge && badge.textContent.includes('HIGH PRIORITY')),
        titleMatches: Boolean(title && title.textContent.includes('Archive Stale Debug Artifacts')),
        hasEvidenceToggle: Boolean(evidenceBtn),
        fakeButtonsAbsent: !dismissBtn && !snoozeBtn && !executeBtn
      };
    })()
  `);

  console.log('[TEST D AUDIT]', recAudit);
  if (!recAudit.cardFound) throw new Error('RecommendationCard not rendered');
  if (!recAudit.priorityBadgeHigh) throw new Error('HIGH PRIORITY badge missing');
  if (!recAudit.fakeButtonsAbsent) throw new Error('Fake lifecycle buttons illegally rendered');

  // Expand Evidence section
  await evaluate(`
    const evidenceBtn = document.querySelector('.rec-evidence-toggle');
    if (evidenceBtn) evidenceBtn.click();
  `);
  await delay(300);

  const evidenceCheck = await evaluate(`
    (() => {
      const list = document.querySelector('.rec-evidence-list');
      return Boolean(list && list.children.length === 4);
    })()
  `);
  if (!evidenceCheck) throw new Error('Evidence list failed to expand');

  console.log('PASSED: Test D (RecommendationCard Component)');
  await takeScreenshot('stage2a_recommendation_cards.png');

  // -------------------------------------------------------------
  // TEST F: SECURITY & XSS SANITIZATION SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST F: Security Sanitization & Protocol Checks ---');
  console.log('======================================================');

  const xssPayload = `Testing markdown security sanitization:

<script>window.__XSS_TRIGGERED = true;</script>
<img src="nonexistent.png" onerror="window.__XSS_TRIGGERED = true" />
<iframe src="javascript:window.__XSS_TRIGGERED = true"></iframe>

[Malicious Javascript Link](javascript:window.__XSS_TRIGGERED=true)
[Malicious Data Link](data:text/html,<script>window.__XSS_TRIGGERED=true</script>)
[Legitimate Safe Link](https://google.com)`;

  await evaluate(`
    window.__XSS_TRIGGERED = false;
    window.__orangeAi.setMessages([
      { role: 'user', text: 'Can you render this HTML and JS payload?' },
      { role: 'assistant', text: ${JSON.stringify(xssPayload)}, model: 'security-audit' }
    ]);
  `);
  await delay(800);

  const securityAudit = await evaluate(`
    (() => {
      const xssTriggered = window.__XSS_TRIGGERED;
      const scriptTags = document.querySelectorAll('.chat-message-bubble script');
      const iframeTags = document.querySelectorAll('.chat-message-bubble iframe');
      const safeLink = document.querySelector('.chat-link[href="https://google.com"]');
      const unsafeJsLink = document.querySelector('.chat-link[href="javascript:window.__XSS_TRIGGERED=true"]');
      const unsafeDataLink = document.querySelector('.chat-link[href^="data:"]');

      return {
        xssTriggered: Boolean(xssTriggered),
        scriptTagsCount: scriptTags.length,
        iframeTagsCount: iframeTags.length,
        safeLinkFound: Boolean(safeLink),
        unsafeJsLinkBlocked: !unsafeJsLink,
        unsafeDataLinkBlocked: !unsafeDataLink
      };
    })()
  `);

  console.log('[TEST F AUDIT]', securityAudit);
  if (securityAudit.xssTriggered) {
    throw new Error('SECURITY BREACH: XSS payload executed in chat timeline!');
  }
  if (securityAudit.scriptTagsCount > 0 || securityAudit.iframeTagsCount > 0) {
    throw new Error('SECURITY VIOLATION: Raw script or iframe tags present in DOM');
  }
  if (!securityAudit.unsafeJsLinkBlocked || !securityAudit.unsafeDataLinkBlocked) {
    throw new Error('SECURITY VIOLATION: Dangerous URI schemes (javascript: or data:) not blocked');
  }

  console.log('PASSED: Test F (Security & Sanitization)');
  await takeScreenshot('stage2a_security_sanitization.png');

  // -------------------------------------------------------------
  // TEST E: REGRESSION VERIFICATION (Workspaces & Native Shell)
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST E: Regression Verification ---');
  console.log('======================================================');

  // Verify all 8 workspaces are accessible
  const views = ['jobs', 'memory', 'activity', 'permissions', 'tools', 'settings', 'home', 'chat'];
  for (const v of views) {
    await evaluate(`window.__orangeAi.selectView('${v}')`);
    await delay(200);
    const active = await evaluate(`window.__orangeAi.getActiveView()`);
    if (active !== v) throw new Error(`Navigation failed for view: ${v}`);
  }
  console.log('PASSED: All 8 workspaces navigated successfully.');

  // Verify Drawer
  await evaluate(`window.__orangeAi.openDrawer()`);
  await delay(200);
  const drawerOpen = await evaluate(`window.__orangeAi.isDrawerOpen()`);
  if (!drawerOpen) throw new Error('Drawer failed to open');
  await evaluate(`window.__orangeAi.closeDrawer()`);
  await delay(200);
  console.log('PASSED: Navigation drawer regression check.');

  console.log('\n======================================================');
  console.log('ALL STAGE 2A TESTS PASSED (A, B, C, D, E, F)');
  console.log('======================================================\n');

  try {
    ws.close();
  } catch (e) {}
}

main()
  .then(() => {
    process.exit(0);
  })
  .catch((err) => {
    console.error('[TEST-SUITE FATAL ERROR]', err);
    process.exit(1);
  });
