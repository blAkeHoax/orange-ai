// tests/cdp_capture.js - Direct Chrome DevTools Protocol automation for Orange AI Desktop 2.0
import fs from 'fs';
import path from 'path';

async function main() {
  console.log('[CDP] Querying localhost:9222/json...');
  const res = await fetch('http://127.0.0.1:9222/json');
  const targets = await res.json();
  console.log('[CDP] Found targets:', targets.map(t => ({ title: t.title, type: t.type, url: t.url })));
  
  const page = targets.find((t) => t.type === 'page');
  if (!page) {
    throw new Error('No page target found on CDP port 9222');
  }

  console.log(`[CDP] Connecting to ${page.webSocketDebuggerUrl}...`);
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
      const args = msg.params.args.map((a) => a.value || a.description).join(' ');
      console.log(`[Page Console][${msg.params.type}]`, args);
    } else if (msg.method === 'Runtime.exceptionThrown') {
      console.error('[Page Exception]', msg.params.exceptionDetails);
    } else if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(msg.error);
      else resolve(msg.result);
    }
  };

  await new Promise((resolve) => (ws.onopen = resolve));
  console.log('[CDP] Connected!');

  // Enable Page and Runtime
  await send('Page.enable');
  await send('Runtime.enable');

  // Check initial location
  let locRes = await send('Runtime.evaluate', {
    expression: 'window.location.href',
    returnByValue: true
  });
  console.log('[CDP] Initial location:', locRes?.result?.value);

  // If about:blank, wait a moment or navigate if necessary
  if (locRes?.result?.value === 'about:blank') {
    console.log('[CDP] Page is currently about:blank, waiting up to 5 seconds for Tauri to navigate...');
    for (let j = 0; j < 10; j++) {
      await new Promise((r) => setTimeout(r, 500));
      locRes = await send('Runtime.evaluate', {
        expression: 'window.location.href',
        returnByValue: true
      });
      if (locRes?.result?.value && locRes.result.value !== 'about:blank') {
        console.log(`[CDP] Navigated to: ${locRes.result.value}`);
        break;
      }
    }
    // If still about:blank, try navigating to http://tauri.localhost/
    if (locRes?.result?.value === 'about:blank') {
      console.log('[CDP] Still about:blank. Attempting Page.navigate to http://tauri.localhost/ ...');
      await send('Page.navigate', { url: 'http://tauri.localhost/' });
    }
  }

  // Wait for document ready & window.__orangeAi
  for (let i = 0; i < 40; i++) {
    const readyRes = await send('Runtime.evaluate', {
      expression: 'document.readyState',
      returnByValue: true
    });
    const orangeRes = await send('Runtime.evaluate', {
      expression: '!!window.__orangeAi',
      returnByValue: true
    });
    if (readyRes?.result?.value === 'complete' && orangeRes?.result?.value === true) {
      console.log(`[CDP] Document complete and window.__orangeAi ready at attempt ${i + 1}`);
      break;
    }
    await new Promise((r) => setTimeout(r, 250));
  }

  // Check current document title and URL
  const evalResult = await send('Runtime.evaluate', {
    expression: '({ title: document.title, url: window.location.href, theme: window.__orangeAiTheme?.theme, hasOrangeAi: !!window.__orangeAi })',
    returnByValue: true
  });
  console.log('[CDP] Page status:', evalResult.result.value);

  // Capture Screenshot helper
  async function capture(filename, width, height, theme, drawerOpen) {
    // 1. Set viewport metrics
    await send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false
    });

    // 2. Set theme and drawer state
    await send('Runtime.evaluate', {
      expression: `
        if (window.__orangeAiTheme) window.__orangeAiTheme.setTheme('${theme}');
        if (window.__orangeAi) {
          if (${drawerOpen}) window.__orangeAi.openDrawer();
          else window.__orangeAi.closeDrawer();
        }
      `
    });

    // Allow CSS transition to settle
    await new Promise((r) => setTimeout(r, 500));

    // 3. Capture screenshot
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(shot.data, 'base64');

    const outDir = 'D:/Orange AI/Orange AI Tauri/screenshots';
    const brainDir = 'C:/Users/User/.gemini/antigravity/brain/3c7f970a-eec6-45a9-97aa-fe852ad24010';

    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
    const filePath = path.join(outDir, filename);
    fs.writeFileSync(filePath, buffer);

    if (fs.existsSync(brainDir)) {
      fs.writeFileSync(path.join(brainDir, filename), buffer);
    }

    console.log(`[CDP] Captured: ${filename} (${width}x${height}, theme: ${theme}, drawer: ${drawerOpen}) [${buffer.length} bytes]`);
  }

  // 1. Home Dark (1024x720)
  await capture('phase3_home_dark_1024x720.png', 1024, 720, 'dark', false);

  // 2. Expanded Navigation Dark (1024x720)
  await capture('phase3_nav_expanded_dark_1024x720.png', 1024, 720, 'dark', true);

  // 3. Expanded Navigation Light (1024x720)
  await capture('phase3_nav_expanded_light_1024x720.png', 1024, 720, 'light', true);

  // 4. Home Light (1024x720)
  await capture('phase3_home_light_1024x720.png', 1024, 720, 'light', false);

  // 5. Responsive scaling: 960x600 (Dark)
  await capture('phase3_home_dark_960x600.png', 960, 600, 'dark', false);

  // 6. Responsive scaling: 1120x750 (Dark)
  await capture('phase3_home_dark_1120x750.png', 1120, 750, 'dark', false);

  // 7. Responsive scaling: 1440x900 (Dark)
  await capture('phase3_home_dark_1440x900.png', 1440, 900, 'dark', false);

  ws.close();
  console.log('[CDP] All 7 Visual Acceptance Screenshots Captured Successfully!');
}

main().catch((err) => {
  console.error('[CDP Error]', err);
  process.exit(1);
});
