// tests/cdp_stage2b_final_verification.js
// CDP automation module for Stage 2B Final Acceptance Verification
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = String.raw`C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010`;
const mode = process.argv[2] || '--all';

async function connectCDP() {
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
    throw new Error('No page target found on port 9222');
  }

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
      throw new Error(`Eval failed: ${JSON.stringify(r.exceptionDetails)}`);
    }
    return r.result ? r.result.value : undefined;
  }

  // Wait for React & runtime ready
  for (let i = 0; i < 50; i++) {
    const ready = await evaluate(`({
      hasOrangeAi: !!window.__orangeAi,
      hasTheme: !!window.__orangeAiTheme,
      status: window.__orangeAi?.getRuntimeStatus?.()
    })`);
    if (ready?.hasOrangeAi && ready?.hasTheme && ready?.status === 'online') {
      break;
    }
    await delay(500);
  }

  return { ws, evaluate, delay, send };
}

async function waitForSettings(evaluate, delay) {
  await evaluate(`window.__orangeAi.selectView('settings')`);
  for (let i = 0; i < 40; i++) {
    await delay(250);
    const ready = await evaluate(`(() => {
      const cards = document.querySelectorAll('.model-option-card');
      const isSpinning = !!document.querySelector('.spinning');
      return cards.length === 4 && !isSpinning;
    })()`);
    if (ready) break;
  }
  await delay(600);
}

async function triggerModelCard(evaluate, delay, targetId) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await evaluate(`
      (async () => {
        const cards = Array.from(document.querySelectorAll('.model-option-card'));
        const card = cards.find(c => c.querySelector('.model-id-code code')?.textContent?.trim() === '${targetId}');
        if (!card) return { found: false };
        const keys = Object.keys(card);
        const reactKey = keys.find(k => k.startsWith('__reactProps'));
        if (reactKey && typeof card[reactKey]?.onClick === 'function') {
          const res = card[reactKey].onClick();
          if (res && typeof res.then === 'function') {
            await res;
          }
          return { found: true, via: 'reactProps' };
        }
        card.click();
        return { found: true, via: 'domClick' };
      })()
    `);
    for (let p = 0; p < 15; p++) {
      await delay(200);
      const cur = await evaluate(`document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim()`);
      if (cur === targetId) return cur;
    }
  }
  throw new Error(`Failed to select model ${targetId} after 5 attempts`);
}

async function run() {
  const { ws, evaluate, delay } = await connectCDP();

  if (mode === '--test1-select-model') {
    await waitForSettings(evaluate, delay);
    console.log('[CDP] Selecting meta/llama-3.1-70b-instruct...');
    const cur = await triggerModelCard(evaluate, delay, 'meta/llama-3.1-70b-instruct');
    await delay(1000);
    console.log('[CDP] Selected model in DOM:', cur);
    console.log(JSON.stringify({ selectedInDom: cur }));
  } else if (mode === '--test1-send-chat') {
    console.log('[CDP] Sending chat inference turn...');
    await evaluate(`window.__orangeAi.sendMessage('What is your primary design philosophy?')`);
    
    // Wait for response to appear in chat timeline
    let messages = [];
    for (let i = 0; i < 40; i++) {
      await delay(500);
      messages = await evaluate(`window.__orangeAi.getMessages()`);
      if (messages.length >= 2 && messages[messages.length - 1].role === 'assistant') {
        break;
      }
    }
    console.log('[CDP] Chat result:', JSON.stringify(messages[messages.length - 1]));
  } else if (mode === '--test1-restore-default') {
    await waitForSettings(evaluate, delay);
    console.log('[CDP] Restoring default model nvidia/llama-3.1-nemotron-70b-instruct...');
    const cur = await triggerModelCard(evaluate, delay, 'nvidia/llama-3.1-nemotron-70b-instruct');
    await delay(1000);
    console.log('[CDP] Restored model in DOM:', cur);
    console.log(JSON.stringify({ restoredInDom: cur }));
  } else if (mode === '--test2-configure-endpoint') {
    const targetUrl = process.argv[3] || 'http://127.0.0.1:8765';
    await waitForSettings(evaluate, delay);

    console.log(`[CDP] Setting test endpoint: ${targetUrl}...`);
    await evaluate(`document.querySelector('.btn-edit-endpoint')?.click()`);
    await delay(400);

    await evaluate(`
      (() => {
        const input = document.querySelector('.settings-url-input');
        if (input) {
          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeSetter.call(input, '${targetUrl}');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const btn = document.querySelector('.btn-save-endpoint');
        btn?.click();
      })()
    `);
    await delay(2000);

    const displayedUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
    console.log('[CDP] Displayed URL after save:', displayedUrl);
    console.log(JSON.stringify({ configuredUrl: displayedUrl }));
  } else if (mode === '--test2-trigger-ping') {
    console.log('[CDP] Triggering connection test / ping in settings...');
    await evaluate(`document.querySelector('.action-btn-secondary')?.click()`);
    await delay(1200);
    console.log('[CDP] Ping completed.');
  } else if (mode === '--test2-restore-endpoint') {
    const prodUrl = 'https://orange-api-cuuo.onrender.com';
    await waitForSettings(evaluate, delay);

    console.log('[CDP] Restoring production endpoint in Settings...');
    await evaluate(`document.querySelector('.btn-edit-endpoint')?.click()`);
    await delay(400);

    await evaluate(`
      (() => {
        const input = document.querySelector('.settings-url-input');
        if (input) {
          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeSetter.call(input, '${prodUrl}');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const btn = document.querySelector('.btn-save-endpoint');
        btn?.click();
      })()
    `);
    await delay(2000);

    const restoredUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
    console.log('[CDP] Restored URL in DOM:', restoredUrl);
    console.log(JSON.stringify({ restoredUrl }));
  } else if (mode === '--test3-setup-values') {
    await waitForSettings(evaluate, delay);

    console.log('[CDP] Setting 7 test configuration values...');
    // 1. Model: meta/llama-3.1-70b-instruct
    await triggerModelCard(evaluate, delay, 'meta/llama-3.1-70b-instruct');
    await delay(600);

    // 2. Morning Briefing: enabled (true)
    const briefingActive = await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.classList.contains('is-active')`);
    if (!briefingActive) {
      await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.click()`);
      await delay(500);
    }

    // 3. Delivery Time: 08:30
    await evaluate(`
      (() => {
        const input = document.querySelector('.settings-time-input');
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(input, '08:30');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        const btn = document.querySelector('.btn-save-inline');
        btn?.click();
      })()
    `);
    await delay(500);

    // 4. Contextual Advisories: disabled (false)
    const advisoriesActive = await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.classList.contains('is-active')`);
    if (advisoriesActive) {
      await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.click()`);
      await delay(500);
    }

    // 5. Cooldown: 8 hours
    await evaluate(`
      Array.from(document.querySelectorAll('.cooldown-btn')).find(b => b.textContent.includes('8 hours'))?.click()
    `);
    await delay(500);

    // 6. Theme: system
    await evaluate(`
      Array.from(document.querySelectorAll('.theme-option-box')).find(b => b.textContent.includes('System Default'))?.click()
    `);
    await delay(500);

    // 7. API URL: production default
    const currentUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
    console.log('[CDP] Test 3 setup complete. Current API URL:', currentUrl);
    await delay(800);
  } else if (mode === '--test3-verify-values') {
    await waitForSettings(evaluate, delay);

    const values = await evaluate(`({
      model: document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim(),
      morning_briefing_enabled: document.querySelectorAll('.switch-toggle-btn')[0]?.classList.contains('is-active'),
      preferred_briefing_time: document.querySelector('.settings-time-input')?.value,
      contextual_advisories_enabled: document.querySelectorAll('.switch-toggle-btn')[1]?.classList.contains('is-active'),
      advisory_cooldown_hours: document.querySelector('.cooldown-btn.is-selected')?.textContent?.trim(),
      theme_preference: window.__orangeAiTheme?.themePreference,
      api_url: document.querySelector('.endpoint-code')?.textContent?.trim()
    })`);

    console.log('[CDP] Verified values after restart in DOM:');
    console.log(JSON.stringify(values, null, 2));
  } else if (mode === '--restore-production-defaults') {
    await waitForSettings(evaluate, delay);

    console.log('[CDP] Restoring production default configuration in Settings...');
    // Model: Default Nemotron 70B
    await triggerModelCard(evaluate, delay, 'nvidia/llama-3.1-nemotron-70b-instruct');
    await delay(500);

    // Morning Briefing: false
    const bActive = await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.classList.contains('is-active')`);
    if (bActive) {
      await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.click()`);
      await delay(400);
    }

    // Delivery Time: 08:30
    await evaluate(`
      (() => {
        const input = document.querySelector('.settings-time-input');
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(input, '08:30');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        const btn = document.querySelector('.btn-save-inline');
        btn?.click();
      })()
    `);
    await delay(400);

    // Contextual Advisories: true
    const aActive = await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.classList.contains('is-active')`);
    if (!aActive) {
      await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.click()`);
      await delay(400);
    }

    // Cooldown: 4 hours
    await evaluate(`
      Array.from(document.querySelectorAll('.cooldown-btn')).find(b => b.textContent.includes('4 hours'))?.click()
    `);
    await delay(400);

    // Theme: dark
    await evaluate(`
      Array.from(document.querySelectorAll('.theme-option-box')).find(b => b.textContent.includes('Dark Theme'))?.click()
    `);
    await delay(400);

    // API URL: production default
    await evaluate(`document.querySelector('.btn-edit-endpoint')?.click()`);
    await delay(400);
    await evaluate(`
      (() => {
        const input = document.querySelector('.settings-url-input');
        if (input) {
          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeSetter.call(input, 'https://orange-api-cuuo.onrender.com');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const btn = document.querySelector('.btn-save-endpoint');
        btn?.click();
      })()
    `);
    await delay(1000);
    console.log('[CDP] Production defaults restored.');
  }

  ws.close();
}

run().catch((err) => {
  console.error('[CDP ERROR]:', err);
  process.exit(1);
});
