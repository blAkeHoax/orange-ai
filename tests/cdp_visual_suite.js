// tests/cdp_visual_suite.js - Comprehensive CDP visual test & screenshot suite
import fs from 'fs';
import path from 'path';

async function main() {
  console.log('[CDP] Polling for WebView2 targets on port 9222...');
  let targets = [];
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json');
      targets = await res.json();
      if (targets && targets.length > 0) break;
    } catch (e) {
      // wait
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  const page = targets.find((t) => t.type === 'page');
  if (!page) {
    throw new Error('No page target found on CDP port 9222: ' + JSON.stringify(targets));
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

  let pageLoaded = false;
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.method === 'Page.loadEventFired') {
      pageLoaded = true;
    } else if (msg.method === 'Runtime.consoleAPICalled') {
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
  console.log('[CDP] Connected to WebSocket!');

  await send('Page.enable');
  await send('Runtime.enable');

  // Wait for document to reach complete & React root to populate
  console.log('[CDP] Waiting for page load and React mount...');
  let mounted = false;
  for (let i = 0; i < 40; i++) {
    const res = await send('Runtime.evaluate', {
      expression: `({
        href: window.location.href,
        ready: document.readyState,
        hasRoot: !!document.getElementById('root'),
        rootChildren: document.getElementById('root')?.children?.length || 0,
        hasOrangeAi: !!window.__orangeAi,
        hasTheme: !!window.__orangeAiTheme
      })`,
      returnByValue: true
    });
    const val = res?.result?.value;
    if (val && val.rootChildren > 0 && val.hasOrangeAi) {
      console.log(`[CDP] Application ready at attempt ${i + 1}:`, val);
      mounted = true;
      break;
    }
    await new Promise((r) => setTimeout(r, 250));
  }

  if (!mounted) {
    const statusRes = await send('Runtime.evaluate', {
      expression: '({ href: window.location.href, html: document.body.innerHTML.slice(0, 300) })',
      returnByValue: true
    });
    console.error('[CDP] App not fully mounted after timeout. Status:', statusRes?.result?.value);
  }

  // Screenshot helper
  async function capture(filename, width, height, theme, drawerOpen) {
    // 1. Set viewport
    await send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false
    });

    // 2. Set theme and drawer
    await send('Runtime.evaluate', {
      expression: `
        if (window.__orangeAiTheme) window.__orangeAiTheme.setTheme('${theme}');
        if (window.__orangeAi) {
          if (${drawerOpen}) window.__orangeAi.openDrawer();
          else window.__orangeAi.closeDrawer();
        }
      `
    });

    // Allow CSS transition to complete
    await new Promise((r) => setTimeout(r, 400));

    // 3. Capture
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(shot.data, 'base64');

    const outDir = 'D:/Orange AI/Orange AI Tauri/screenshots';
    const brainDir = 'C:/Users/User/.gemini/antigravity/brain/3c7f970a-eec6-45a9-97aa-fe852ad24010';

    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, filename), buffer);

    if (fs.existsSync(brainDir)) {
      fs.writeFileSync(path.join(brainDir, filename), buffer);
    }

    console.log(`[CDP] Captured: ${filename} (${width}x${height}, theme: ${theme}, drawer: ${drawerOpen}) -> ${buffer.length} bytes`);
  }

  // Visual Acceptance Matrix
  console.log('\n--- Capturing Visual Acceptance Screenshots ---');
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
  console.log('[CDP] Suite completed successfully!');
}

main().catch((err) => {
  console.error('[CDP Fatal Error]', err);
  process.exit(1);
});
