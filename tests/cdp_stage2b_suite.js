// tests/cdp_stage2b_suite.js - Master CDP Automated Verification Suite for Stage 2B
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = String.raw`C:\Users\User\.gemini\antigravity\brain\3c7f970a-eec6-45a9-97aa-fe852ad24010`;

async function main() {
  console.log('[STAGE-2B] Connecting to CDP port 9222...');
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

  console.log(`[STAGE-2B] Found page target: ${page.title} (${page.url})`);
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
  console.log('[STAGE-2B] WebSocket connection established.');

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

  console.log('[STAGE-2B] Waiting for React application and Python runtime online...');
  let mounted = false;
  for (let i = 0; i < 50; i++) {
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
    if (val?.hasOrangeAi && val?.hasTheme && val?.status === 'online') {
      mounted = true;
      console.log(`[STAGE-2B] Runtime online detected at attempt ${i + 1}`);
      break;
    }
    await delay(500);
  }
  if (!mounted) {
    throw new Error('Python runtime failed to report online status within 25s');
  }
  console.log('[STAGE-2B] React application and Python runtime ready.');
  await delay(2000);

  // Navigate to Settings View
  console.log('\n--- Navigating to Settings Workspace ---');
  await evaluate(`window.__orangeAi.selectView('settings')`);

  // Wait for SettingsView to mount and finish loading
  for (let i = 0; i < 40; i++) {
    await delay(300);
    const ready = await evaluate(`(() => {
      const cards = document.querySelectorAll('.model-option-card');
      const isSpinning = !!document.querySelector('.spinning');
      return cards.length === 4 && !isSpinning;
    })()`);
    if (ready) {
      console.log(`[STAGE-2B] SettingsView fully mounted and settled at poll ${i + 1}`);
      break;
    }
  }
  await delay(800);

  // Set Dark Theme initially
  await evaluate(`window.__orangeAiTheme.setTheme('dark')`);
  await delay(400);

  // -------------------------------------------------------------
  // TEST A: FOUR-NVIDIA-MODEL SELECTION SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST A: Four-NVIDIA-Model Selection Suite ---');
  console.log('======================================================');

  const modelCardsCheck = await evaluate(`
    (() => {
      const cards = Array.from(document.querySelectorAll('.model-option-card'));
      const codes = cards.map(c => c.querySelector('.model-id-code code')?.textContent?.trim());
      const names = cards.map(c => c.querySelector('.model-display-name')?.textContent?.trim());
      const tags = cards.map(c => c.querySelector('.model-tag-pill')?.textContent?.trim());
      const selected = document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim();

      return {
        cardCount: cards.length,
        codes,
        names,
        tags,
        selected
      };
    })()
  `);

  console.log('[TEST A MODEL CARDS]', modelCardsCheck);
  const expectedModelIds = [
    'nvidia/llama-3.1-nemotron-70b-instruct',
    'meta/llama-3.1-70b-instruct',
    'openbmb/minicpm-v-2_6',
    'mistralai/mistral-large-2-instruct'
  ];

  if (modelCardsCheck.cardCount !== 4) {
    throw new Error(`Expected 4 model cards, got ${modelCardsCheck.cardCount}`);
  }
  for (const expectedId of expectedModelIds) {
    if (!modelCardsCheck.codes.includes(expectedId)) {
      throw new Error(`Missing expected model card: ${expectedId}`);
    }
  }

  // Helper to trigger card click
  const triggerModelCard = async (targetId) => {
    return await evaluate(`
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
  };

  // Test selecting each model in sequence
  console.log('[TEST A] Selecting meta/llama-3.1-70b-instruct...');
  const tRes = await triggerModelCard('meta/llama-3.1-70b-instruct');
  console.log('[TEST A TRIGGER RES]:', tRes);

  let curSelected = '';
  let statusText = '';
  for (let i = 0; i < 25; i++) {
    await delay(200);
    const state = await evaluate(`({
      selected: document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim(),
      status: document.querySelector('.section-status-pill')?.textContent?.trim()
    })`);
    curSelected = state.selected;
    statusText = state.status;
    if (curSelected === 'meta/llama-3.1-70b-instruct') break;
  }
  console.log(`[TEST A] After wait: curSelected=${curSelected}, statusText=${statusText}`);
  if (curSelected !== 'meta/llama-3.1-70b-instruct') {
    throw new Error(`Expected selected model meta/llama-3.1-70b-instruct, got: ${curSelected} (status: ${statusText})`);
  }
  console.log('✓ Successfully selected Llama 70B');

  console.log('[TEST A] Selecting openbmb/minicpm-v-2_6...');
  await triggerModelCard('openbmb/minicpm-v-2_6');
  for (let i = 0; i < 25; i++) {
    await delay(200);
    curSelected = await evaluate(`document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim()`);
    if (curSelected === 'openbmb/minicpm-v-2_6') break;
  }
  if (curSelected !== 'openbmb/minicpm-v-2_6') {
    throw new Error(`Expected selected model openbmb/minicpm-v-2_6, got: ${curSelected}`);
  }
  console.log('✓ Successfully selected MiniCPM');

  console.log('[TEST A] Selecting mistralai/mistral-large-2-instruct...');
  await triggerModelCard('mistralai/mistral-large-2-instruct');
  for (let i = 0; i < 25; i++) {
    await delay(200);
    curSelected = await evaluate(`document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim()`);
    if (curSelected === 'mistralai/mistral-large-2-instruct') break;
  }
  if (curSelected !== 'mistralai/mistral-large-2-instruct') {
    throw new Error(`Expected selected model mistralai/mistral-large-2-instruct, got: ${curSelected}`);
  }
  console.log('✓ Successfully selected Mistral Large 2');

  console.log('[TEST A] Returning to default nvidia/llama-3.1-nemotron-70b-instruct...');
  await triggerModelCard('nvidia/llama-3.1-nemotron-70b-instruct');
  for (let i = 0; i < 25; i++) {
    await delay(200);
    curSelected = await evaluate(`document.querySelector('.model-option-card.is-selected .model-id-code code')?.textContent?.trim()`);
    if (curSelected === 'nvidia/llama-3.1-nemotron-70b-instruct') break;
  }
  if (curSelected !== 'nvidia/llama-3.1-nemotron-70b-instruct') {
    throw new Error(`Expected selected model nvidia/llama-3.1-nemotron-70b-instruct, got: ${curSelected}`);
  }
  console.log('✓ Successfully returned to Nemotron 70B (Default)');

  // Capture Dark Theme Screenshot
  await takeScreenshot('stage2b_model_selector_dark.png');

  // Switch to Light Theme for Light Screenshot
  await evaluate(`window.__orangeAiTheme.setTheme('light')`);
  await delay(400);
  await takeScreenshot('stage2b_model_selector_light.png');

  // Return to Dark Theme
  await evaluate(`window.__orangeAiTheme.setTheme('dark')`);
  await delay(300);

  console.log('PASSED: Test A (Four-NVIDIA-Model Selection)');

  // -------------------------------------------------------------
  // TEST B: PROACTIVE PERSONAL ASSISTANCE CONTROLS
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST B: Proactive Personal Assistance Controls ---');
  console.log('======================================================');

  // 1. Toggle Morning Briefing
  const initialBriefing = await evaluate(`
    document.querySelectorAll('.switch-toggle-btn')[0]?.classList.contains('is-active')
  `);
  console.log(`[TEST B] Initial Morning Briefing toggle state: ${initialBriefing}`);

  await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.click()`);
  await delay(500);

  const toggledBriefing = await evaluate(`
    document.querySelectorAll('.switch-toggle-btn')[0]?.classList.contains('is-active')
  `);
  console.log(`[TEST B] Toggled Morning Briefing state: ${toggledBriefing}`);
  if (toggledBriefing === initialBriefing) {
    throw new Error('Morning Briefing toggle state did not change upon click');
  }

  // Toggle back to initial
  await evaluate(`document.querySelectorAll('.switch-toggle-btn')[0]?.click()`);
  await delay(400);

  // 2. Preferred Delivery Time Validation (Invalid format: 99:99)
  console.log('[TEST B] Testing invalid delivery time input (99:99)...');
  await evaluate(`
    (() => {
      const input = document.querySelector('.settings-time-input');
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(input, '99:99');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const btn = document.querySelector('.btn-save-inline');
      btn.click();
    })()
  `);
  await delay(400);

  const timeErrorMsg = await evaluate(`document.querySelector('.inline-error-text')?.textContent?.trim()`);
  console.log(`[TEST B] Got time error response: "${timeErrorMsg}"`);
  if (!timeErrorMsg || !timeErrorMsg.includes('Invalid format')) {
    throw new Error(`Expected invalid time format error, got: ${timeErrorMsg}`);
  }
  console.log('✓ Invalid delivery time format was properly rejected');

  // Valid delivery time input: 08:30
  console.log('[TEST B] Testing valid delivery time input (08:30)...');
  await evaluate(`
    (() => {
      const input = document.querySelector('.settings-time-input');
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(input, '08:30');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const btn = document.querySelector('.btn-save-inline');
      btn.click();
    })()
  `);
  await delay(500);

  const timeVal = await evaluate(`document.querySelector('.settings-time-input')?.value`);
  console.log(`[TEST B] Verified valid delivery time: ${timeVal}`);
  if (timeVal !== '08:30') {
    throw new Error(`Expected time input to be 08:30, got: ${timeVal}`);
  }

  // 3. Toggle Contextual Advisories
  const initialAdvisories = await evaluate(`
    document.querySelectorAll('.switch-toggle-btn')[1]?.classList.contains('is-active')
  `);
  console.log(`[TEST B] Initial Contextual Advisories toggle state: ${initialAdvisories}`);

  await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.click()`);
  await delay(500);

  const toggledAdvisories = await evaluate(`
    document.querySelectorAll('.switch-toggle-btn')[1]?.classList.contains('is-active')
  `);
  console.log(`[TEST B] Toggled Contextual Advisories state: ${toggledAdvisories}`);
  if (toggledAdvisories === initialAdvisories) {
    throw new Error('Contextual Advisories toggle state did not change upon click');
  }

  // Restore advisories to true
  await evaluate(`document.querySelectorAll('.switch-toggle-btn')[1]?.click()`);
  await delay(400);

  // 4. Test Cooldown Pills (2h, 4h, 8h)
  console.log('[TEST B] Testing cooldown pills selection...');
  const cooldownButtons = await evaluate(`
    Array.from(document.querySelectorAll('.cooldown-btn')).map(b => b.textContent.trim())
  `);
  console.log('[TEST B] Cooldown options found:', cooldownButtons);
  if (cooldownButtons.length !== 3) {
    throw new Error(`Expected 3 cooldown buttons, found ${cooldownButtons.length}`);
  }

  // Click 2 hours
  await evaluate(`
    Array.from(document.querySelectorAll('.cooldown-btn')).find(b => b.textContent.includes('2 hours'))?.click()
  `);
  await delay(400);
  let activeCooldown = await evaluate(`document.querySelector('.cooldown-btn.is-selected')?.textContent?.trim()`);
  if (!activeCooldown?.includes('2 hours')) {
    throw new Error(`Expected 2 hours active, got: ${activeCooldown}`);
  }

  // Click 8 hours
  await evaluate(`
    Array.from(document.querySelectorAll('.cooldown-btn')).find(b => b.textContent.includes('8 hours'))?.click()
  `);
  await delay(400);
  activeCooldown = await evaluate(`document.querySelector('.cooldown-btn.is-selected')?.textContent?.trim()`);
  if (!activeCooldown?.includes('8 hours')) {
    throw new Error(`Expected 8 hours active, got: ${activeCooldown}`);
  }

  // Return to 4 hours (Default)
  await evaluate(`
    Array.from(document.querySelectorAll('.cooldown-btn')).find(b => b.textContent.includes('4 hours'))?.click()
  `);
  await delay(400);
  activeCooldown = await evaluate(`document.querySelector('.cooldown-btn.is-selected')?.textContent?.trim()`);
  if (!activeCooldown?.includes('4 hours')) {
    throw new Error(`Expected 4 hours active, got: ${activeCooldown}`);
  }
  console.log('✓ Cooldown pill selection verified successfully');

  // 5. Verify Honest Stage Limitation Disclaimer
  const disclaimerText = await evaluate(`document.querySelector('.proactive-disclaimer-box')?.textContent?.trim()`);
  console.log(`[TEST B] Disclaimer Box text: "${disclaimerText}"`);
  if (!disclaimerText || !disclaimerText.includes('Implementation Note')) {
    throw new Error('Proactive assistance disclaimer box is missing');
  }

  // Capture screenshot of proactive assistance section
  await takeScreenshot('stage2b_proactive_settings.png');
  console.log('PASSED: Test B (Proactive Personal Assistance Controls)');

  // -------------------------------------------------------------
  // TEST C: SYSTEM THEME AUTO-DETECTION SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST C: System Theme Auto-Detection Suite ---');
  console.log('======================================================');

  // Verify theme options are present
  const themeBoxes = await evaluate(`
    Array.from(document.querySelectorAll('.theme-option-box')).map(b => b.querySelector('.theme-option-name')?.textContent?.trim())
  `);
  console.log('[TEST C] Found theme options:', themeBoxes);
  if (!themeBoxes.includes('Dark Theme') || !themeBoxes.includes('Light Theme') || !themeBoxes.includes('System Default')) {
    throw new Error(`Missing expected theme options in: ${JSON.stringify(themeBoxes)}`);
  }

  // Select Light Theme
  console.log('[TEST C] Selecting Light Theme...');
  await evaluate(`
    Array.from(document.querySelectorAll('.theme-option-box')).find(b => b.textContent.includes('Light Theme'))?.click()
  `);
  await delay(400);

  const lightState = await evaluate(`({
    pref: window.__orangeAiTheme.themePreference,
    resolved: window.__orangeAiTheme.resolvedTheme,
    bodyTheme: document.body.getAttribute('data-theme') || document.documentElement.getAttribute('data-theme')
  })`);
  console.log('[TEST C] Light Theme state:', lightState);
  if (lightState.pref !== 'light' || lightState.resolved !== 'light' || lightState.bodyTheme !== 'light') {
    throw new Error(`Light theme selection failed: ${JSON.stringify(lightState)}`);
  }

  // Select Dark Theme
  console.log('[TEST C] Selecting Dark Theme...');
  await evaluate(`
    Array.from(document.querySelectorAll('.theme-option-box')).find(b => b.textContent.includes('Dark Theme'))?.click()
  `);
  await delay(400);

  const darkState = await evaluate(`({
    pref: window.__orangeAiTheme.themePreference,
    resolved: window.__orangeAiTheme.resolvedTheme,
    bodyTheme: document.body.getAttribute('data-theme') || document.documentElement.getAttribute('data-theme')
  })`);
  console.log('[TEST C] Dark Theme state:', darkState);
  if (darkState.pref !== 'dark' || darkState.resolved !== 'dark' || darkState.bodyTheme !== 'dark') {
    throw new Error(`Dark theme selection failed: ${JSON.stringify(darkState)}`);
  }

  // Select System Default
  console.log('[TEST C] Selecting System Default Theme...');
  await evaluate(`
    Array.from(document.querySelectorAll('.theme-option-box')).find(b => b.textContent.includes('System Default'))?.click()
  `);
  await delay(400);

  const systemState = await evaluate(`({
    pref: window.__orangeAiTheme.themePreference,
    resolved: window.__orangeAiTheme.resolvedTheme,
    osPrefersDark: window.matchMedia('(prefers-color-scheme: dark)').matches,
    bodyHasClass: document.body.className
  })`);
  console.log('[TEST C] System Default state:', systemState);
  if (systemState.pref !== 'system') {
    throw new Error(`System theme preference failed: ${JSON.stringify(systemState)}`);
  }
  const expectedResolved = systemState.osPrefersDark ? 'dark' : 'light';
  if (systemState.resolved !== expectedResolved) {
    throw new Error(`Expected resolved theme ${expectedResolved}, got ${systemState.resolved}`);
  }
  console.log('✓ System theme auto-detection verified with live OS prefers-color-scheme match');

  // Capture System Theme Screenshot
  await takeScreenshot('stage2b_system_theme_detection.png');
  console.log('PASSED: Test C (System Theme Auto-Detection)');

  // -------------------------------------------------------------
  // TEST D: EDITABLE ORANGE API URL SUITE
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST D: Editable Orange API URL Suite ---');
  console.log('======================================================');

  // Verify initial URL display
  const initialUrlDisplay = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
  console.log(`[TEST D] Initial API URL displayed: "${initialUrlDisplay}"`);
  if (!initialUrlDisplay || !initialUrlDisplay.includes('https://orange-api-cuuo.onrender.com')) {
    throw new Error(`Expected default production URL, got: ${initialUrlDisplay}`);
  }

  // Click "Edit Endpoint"
  console.log('[TEST D] Clicking Edit Endpoint...');
  await evaluate(`document.querySelector('.btn-edit-endpoint')?.click()`);
  await delay(300);

  let isInputPresent = await evaluate(`!!document.querySelector('.settings-url-input')`);
  if (!isInputPresent) {
    throw new Error('Endpoint input did not appear after clicking Edit Endpoint');
  }

  // 1. Test Rejection of Unsafe Scheme: javascript:alert(1)
  console.log('[TEST D] Testing unsafe URL scheme (javascript:alert(1))...');
  await evaluate(`
    (() => {
      const input = document.querySelector('.settings-url-input');
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(input, 'javascript:alert(1)');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const btn = document.querySelector('.btn-save-endpoint');
      btn.click();
    })()
  `);
  await delay(400);

  let urlErr = await evaluate(`document.querySelector('.endpoint-edit-container .inline-error-text')?.textContent?.trim()`);
  console.log(`[TEST D] Got unsafe scheme error: "${urlErr}"`);
  if (!urlErr || !urlErr.includes('Unsafe scheme rejected')) {
    throw new Error(`Expected unsafe scheme error, got: ${urlErr}`);
  }
  console.log('✓ Unsafe URL scheme was blocked by frontend validation');

  // 2. Test Rejection of Malformed URL: not-a-valid-url
  console.log('[TEST D] Testing malformed URL (not-a-valid-url)...');
  await evaluate(`
    (() => {
      const input = document.querySelector('.settings-url-input');
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(input, 'not-a-valid-url');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const btn = document.querySelector('.btn-save-endpoint');
      btn.click();
    })()
  `);
  await delay(400);

  urlErr = await evaluate(`document.querySelector('.endpoint-edit-container .inline-error-text')?.textContent?.trim()`);
  console.log(`[TEST D] Got malformed URL error: "${urlErr}"`);
  if (!urlErr || !urlErr.includes('http://') && !urlErr.includes('https://')) {
    throw new Error(`Expected protocol error, got: ${urlErr}`);
  }
  console.log('✓ Malformed URL was blocked by frontend validation');

  // 3. Test "Cancel" Button
  console.log('[TEST D] Testing Cancel button...');
  await evaluate(`document.querySelector('.btn-cancel-endpoint')?.click()`);
  await delay(300);

  isInputPresent = await evaluate(`!!document.querySelector('.settings-url-input')`);
  if (isInputPresent) {
    throw new Error('Cancel button did not close the edit container');
  }
  const cancelledUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
  if (cancelledUrl !== initialUrlDisplay) {
    throw new Error(`Cancel failed to preserve initial URL: expected ${initialUrlDisplay}, got ${cancelledUrl}`);
  }
  console.log('✓ Cancel button closed editor and preserved URL');

  // 4. Test Valid Custom URL Update
  console.log('[TEST D] Testing valid custom URL update...');
  await evaluate(`document.querySelector('.btn-edit-endpoint')?.click()`);
  await delay(300);

  const customUrl = 'https://custom-api.orange-test.org';
  await evaluate(`
    (() => {
      const input = document.querySelector('.settings-url-input');
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSetter.call(input, '${customUrl}');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const btn = document.querySelector('.btn-save-endpoint');
      btn.click();
    })()
  `);
  let updatedUrl = '';
  for (let i = 0; i < 20; i++) {
    await delay(200);
    updatedUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
    if (updatedUrl === customUrl) break;
  }

  console.log(`[TEST D] Updated URL displayed: "${updatedUrl}"`);
  if (updatedUrl !== customUrl) {
    throw new Error(`Expected updated URL ${customUrl}, got: ${updatedUrl}`);
  }
  console.log('✓ Valid custom URL saved and displayed successfully');

  // Capture screenshot during API URL editing / updated state
  await takeScreenshot('stage2b_api_url_editing.png');

  // 5. Restore Default Production URL
  console.log('[TEST D] Restoring production default URL...');
  for (let i = 0; i < 25; i++) {
    const hasEditBtn = await evaluate(`!!document.querySelector('.btn-edit-endpoint')`);
    if (hasEditBtn) break;
    await delay(200);
  }
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
  let restoredUrl = '';
  for (let i = 0; i < 30; i++) {
    await delay(300);
    restoredUrl = await evaluate(`document.querySelector('.endpoint-code')?.textContent?.trim()`);
    if (restoredUrl === 'https://orange-api-cuuo.onrender.com') break;
  }
  if (restoredUrl !== 'https://orange-api-cuuo.onrender.com') {
    throw new Error(`Failed to restore production default URL, got: ${restoredUrl}`);
  }
  console.log('✓ Successfully restored production default URL');

  console.log('PASSED: Test D (Editable Orange API URL)');

  // -------------------------------------------------------------
  // TEST E: REGRESSION & NAVIGATION INTEGRITY
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST E: Regression & Navigation Integrity ---');
  console.log('======================================================');

  // Test navigation to all 8 views without crashes or errors
  const allViews = ['home', 'chat', 'jobs', 'memory', 'activity', 'permissions', 'tools', 'settings'];
  for (const v of allViews) {
    console.log(`[TEST E] Navigating to view: ${v}...`);
    await evaluate(`window.__orangeAi.selectView('${v}')`);
    let active = '';
    for (let i = 0; i < 20; i++) {
      await delay(150);
      active = await evaluate(`window.__orangeAi?.getActiveView?.()`);
      if (active === v) break;
    }
    if (active !== v) {
      throw new Error(`Failed to navigate to view ${v}, active is ${active}`);
    }
  }

  // Switch to Chat and verify Stage 2A timeline elements are intact
  console.log('[TEST E] Verifying Chat timeline regression...');
  await evaluate(`window.__orangeAi.selectView('chat')`);
  await delay(400);

  // Send a test message to verify chat interface & model tag badge
  await evaluate(`
    window.__orangeAi.setMessages([
      { role: 'user', text: 'Regression test prompt' },
      { role: 'assistant', text: 'This is a **markdown** regression response with \`inline code\`.', model: 'nvidia/llama-3.1-nemotron-70b-instruct' }
    ]);
  `);
  await delay(500);

  const chatRegression = await evaluate(`({
    hasModelBadge: !!document.querySelector('.chat-model-tag'),
    badgeText: document.querySelector('.chat-model-tag')?.textContent?.trim(),
    hasStrong: !!document.querySelector('.chat-message-bubble strong'),
    hasCode: !!document.querySelector('.chat-message-bubble .inline-code')
  })`);
  console.log('[TEST E] Chat regression audit:', chatRegression);
  if (!chatRegression.hasModelBadge || !chatRegression.hasStrong || !chatRegression.hasCode) {
    throw new Error(`Chat regression failed: ${JSON.stringify(chatRegression)}`);
  }
  console.log('PASSED: Test E (Regression & Navigation Integrity)');

  // -------------------------------------------------------------
  // TEST F: SECURITY & CLIENT IMMUTABILITY AUDIT
  // -------------------------------------------------------------
  console.log('\n======================================================');
  console.log('--- TEST F: Security & Client Immutability Audit ---');
  console.log('======================================================');

  // Verify secret protection in localStorage and DOM
  console.log('[TEST F] Auditing DOM and localStorage for credential leaks...');
  const securityAudit = await evaluate(`(() => {
    const rawStorage = JSON.stringify(window.localStorage);
    const bodyHtml = document.body.innerHTML;
    const hasApiKeyInStorage = /api[_-]?key|secret|password|token/i.test(rawStorage);
    const hasSecretInDom = /orange_api_secret|internal_token/i.test(bodyHtml);
    const hasDirectDb = !!window.sqlite3 || !!window.sqlite || !!window.fs;

    return {
      hasApiKeyInStorage,
      hasSecretInDom,
      hasDirectDb
    };
  })()`);
  console.log('[TEST F] Client security audit result:', securityAudit);
  if (securityAudit.hasApiKeyInStorage) {
    throw new Error('Sensitive credentials detected in localStorage!');
  }
  if (securityAudit.hasSecretInDom) {
    throw new Error('Sensitive internal token detected in DOM!');
  }
  if (securityAudit.hasDirectDb) {
    throw new Error('Direct database/filesystem handle exposed on window!');
  }
  console.log('✓ Secret protection audit passed: 0 credentials leaked, zero direct DB access from React');

  console.log('\n======================================================');
  console.log('ALL STAGE 2B TESTS COMPLETED SUCCESSFULLY!');
  console.log('======================================================');

  ws.close();
}

main().catch((err) => {
  console.error('\n[FATAL STAGE-2B TEST SUITE ERROR]:', err);
  process.exit(1);
});
