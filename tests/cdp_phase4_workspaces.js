// tests/cdp_phase4_workspaces.js - Comprehensive Phase 4 Multi-View Visual Capture Suite
import fs from 'fs';
import path from 'path';

async function main() {
  console.log('[CDP Phase 4] Polling for WebView2 targets on port 9222...');
  let targets = [];
  for (let attempt = 0; attempt < 25; attempt++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json');
      targets = await res.json();
      if (targets && targets.length > 0) break;
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 500));
  }

  const page = targets.find((t) => t.type === 'page');
  if (!page) {
    throw new Error('No page target found on CDP port 9222: ' + JSON.stringify(targets));
  }

  console.log(`[CDP Phase 4] Connecting to ${page.webSocketDebuggerUrl}...`);
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
  console.log('[CDP Phase 4] Connected to WebSocket!');

  await send('Page.enable');
  await send('Runtime.enable');

  // Wait for document and window.__orangeAi mount
  console.log('[CDP Phase 4] Waiting for React application mount...');
  let mounted = false;
  for (let i = 0; i < 40; i++) {
    const res = await send('Runtime.evaluate', {
      expression: `({
        ready: document.readyState,
        hasOrangeAi: !!window.__orangeAi,
        hasTheme: !!window.__orangeAiTheme,
        activeView: window.__orangeAi?.getActiveView?.()
      })`,
      returnByValue: true
    });
    const val = res?.result?.value;
    if (val && val.hasOrangeAi) {
      console.log(`[CDP Phase 4] App ready at attempt ${i + 1}:`, val);
      mounted = true;
      break;
    }
    await new Promise((r) => setTimeout(r, 300));
  }

  if (!mounted) {
    throw new Error('Application failed to mount within timeout.');
  }

  // Set standard desktop viewport
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1080,
    height: 750,
    deviceScaleFactor: 1,
    mobile: false
  });

  const outDir = 'D:/Orange AI/Orange AI Tauri/screenshots';
  const brainDir = 'C:/Users/User/.gemini/antigravity/brain/3c7f970a-eec6-45a9-97aa-fe852ad24010';
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  async function captureWorkspace(filename, viewId, theme = 'dark', waitMs = 500) {
    // 1. Set theme
    await send('Runtime.evaluate', {
      expression: `window.__orangeAiTheme?.setTheme('${theme}');`
    });

    // 2. Select view
    await send('Runtime.evaluate', {
      expression: `window.__orangeAi?.selectView('${viewId}');`
    });

    // Wait for view component data to load & render
    for (let w = 0; w < 15; w++) {
      await new Promise((r) => setTimeout(r, 200));
      const checkRes = await send('Runtime.evaluate', {
        expression: `!document.querySelector('.spinning')`,
        returnByValue: true
      });
      if (checkRes?.result?.value) break;
    }
    await new Promise((r) => setTimeout(r, 400));

    // 3. Capture screenshot
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(shot.data, 'base64');

    fs.writeFileSync(path.join(outDir, filename), buffer);
    if (fs.existsSync(brainDir)) {
      fs.writeFileSync(path.join(brainDir, filename), buffer);
    }
    console.log(`[CDP Phase 4] Captured: ${filename} (view: ${viewId}, theme: ${theme}) [${buffer.length} bytes]`);
  }

  console.log('\n--- Capturing All 8 Workspaces ---');

  // 1. Home (Dark)
  await captureWorkspace('phase4_workspace_home_dark.png', 'home', 'dark', 400);

  // 2. Home (Light)
  await captureWorkspace('phase4_workspace_home_light.png', 'home', 'light', 400);

  // 3. Chat (Dark) - with loaded persistent history
  await captureWorkspace('phase4_workspace_chat_dark.png', 'chat', 'dark', 600);

  // 4. Agent Jobs (Dark)
  await captureWorkspace('phase4_workspace_jobs_dark.png', 'jobs', 'dark', 700);

  // 5. Memory (Dark)
  await captureWorkspace('phase4_workspace_memory_dark.png', 'memory', 'dark', 700);

  // 6. Activity (Dark)
  await captureWorkspace('phase4_workspace_activity_dark.png', 'activity', 'dark', 700);

  // 7. Permissions (Dark)
  await captureWorkspace('phase4_workspace_permissions_dark.png', 'permissions', 'dark', 700);

  // 8. Tools (Dark)
  await captureWorkspace('phase4_workspace_tools_dark.png', 'tools', 'dark', 700);

  // 9. Settings (Dark)
  await captureWorkspace('phase4_workspace_settings_dark.png', 'settings', 'dark', 600);

  // 10. Settings (Light)
  await captureWorkspace('phase4_workspace_settings_light.png', 'settings', 'light', 600);

  // 11. Interactive Chat Turn
  console.log('\n--- Executing Interactive Chat Turn via Frontend Bridge ---');
  await send('Runtime.evaluate', {
    expression: `window.__orangeAi?.sendMessage('What time is it right now?');`
  });
  // Wait for turn to complete execution (async worker thread)
  await new Promise((r) => setTimeout(r, 2500));
  await captureWorkspace('phase4_workspace_chat_interactive.png', 'chat', 'dark', 300);

  // 12. Interactive Confirmation Modal
  console.log('\n--- Capturing Action Confirmation Modal ---');
  await send('Runtime.evaluate', {
    expression: `window.__orangeAi?.triggerConfirmation({
      confirmation_id: 'conf_sec_8e21',
      prompt_text: '⚠️ Orange AI wants to perform: open_app (notepad)\\nRisk level: CONFIRMATION_REQUIRED\\nProceed? [y/N]:'
    });`
  });
  await new Promise((r) => setTimeout(r, 400));
  await captureWorkspace('phase4_confirmation_modal.png', 'chat', 'dark', 200);

  // Dismiss modal
  await send('Runtime.evaluate', {
    expression: `window.__orangeAi?.triggerConfirmation(null);`
  });
  await new Promise((r) => setTimeout(r, 200));

  ws.close();
  console.log('\n[CDP Phase 4] All Workspace Visual Captures Completed Successfully!');
}

main().catch((err) => {
  console.error('[CDP Phase 4 Fatal Error]', err);
  process.exit(1);
});
