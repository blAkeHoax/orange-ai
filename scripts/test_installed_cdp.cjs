const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const APP_PATH = 'C:\\Users\\User\\AppData\\Local\\Orange AI\\app.exe';
const ARTIFACT_DIR = 'C:\\Users\\User\\.gemini\\antigravity\\brain\\3c7f970a-eec6-45a9-97aa-fe852ad24010';

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function getCDPTarget() {
  for (let i = 0; i < 20; i++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json');
      const targets = await res.json();
      const page = targets.find(t => t.type === 'page');
      if (page && page.webSocketDebuggerUrl) {
        return page;
      }
    } catch (e) {
      // retry
    }
    await sleep(500);
  }
  throw new Error('Could not find CDP page target');
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.id = 1;
    this.pending = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) {
          reject(msg.error);
        } else {
          resolve(msg.result);
        }
      }
    };
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.id++;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, awaitPromise = true) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise,
      returnByValue: true
    });
    if (res.exceptionDetails) {
      throw new Error(JSON.stringify(res.exceptionDetails));
    }
    return res.result ? res.result.value : null;
  }

  close() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

async function main() {
  console.log('=== STARTING INSTALLED ORANGE AI LIVE CDP TEST ===');

  // Kill any existing instances first
  try {
    execSync('taskkill /F /IM app.exe /T', { stdio: 'ignore' });
    execSync('taskkill /F /IM runtime_adapter.exe /T', { stdio: 'ignore' });
  } catch (e) {}
  await sleep(1000);

  // Spawn installed app
  const env = { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9222' };
  const child = spawn(APP_PATH, [], { env, detached: true, stdio: 'ignore' });
  child.unref();

  console.log(`Launched ${APP_PATH} (PID: ${child.pid})`);

  try {
    const target = await getCDPTarget();
    console.log(`Connected to CDP target: ${target.title} (${target.url})`);

    const cdp = new CDPClient(target.webSocketDebuggerUrl);
    await cdp.connect();
    console.log('CDP WebSocket connected successfully.');

    await cdp.send('Runtime.enable');
    await cdp.send('Page.enable');

    // Wait 2 seconds for React to mount
    await sleep(2000);

    // 1. Test ping
    console.log('\n--- 1. Testing Tauri IPC ping ---');
    const pingRes = await cdp.evaluate("window.__TAURI_INTERNALS__.invoke('ping')");
    console.log('Ping Result:', JSON.stringify(pingRes, null, 2));

    // 2. Test get_health
    console.log('\n--- 2. Testing Tauri IPC get_health ---');
    const healthRes = await cdp.evaluate("window.__TAURI_INTERNALS__.invoke('get_health')");
    console.log('Health Result:', JSON.stringify(healthRes, null, 2));

    // 3. Test memory stats
    console.log('\n--- 3. Testing Tauri IPC get_memory ---');
    const memoryStats = await cdp.evaluate("window.__TAURI_INTERNALS__.invoke('get_memory')");
    console.log('Memory Stats Result:', JSON.stringify(memoryStats, null, 2));

    // 4. Test live chat inference through hosted API
    console.log('\n--- 4. Testing Live Inference (send_message) ---');
    const testPrompt = 'Explain in two short sentences what Orange AI does.';
    console.log(`Sending prompt: "${testPrompt}"...`);
    const chatStart = Date.now();
    const chatRes = await cdp.evaluate(
      `window.__TAURI_INTERNALS__.invoke('send_message', { text: "${testPrompt}" })`
    );
    const chatDuration = ((Date.now() - chatStart) / 1000).toFixed(2);
    console.log(`Chat Result (${chatDuration}s):`, JSON.stringify(chatRes, null, 2));

    // Wait a brief moment for UI update
    await sleep(1500);

    // 5. Capture screenshot of the installed app
    console.log('\n--- 5. Capturing App Screenshot ---');
    const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const screenshotPath = path.join(ARTIFACT_DIR, 'phase5_installed_app_live.png');
    fs.writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'));
    console.log(`Screenshot saved to: ${screenshotPath}`);

    cdp.close();

    console.log('\n=== LIVE TEST COMPLETED SUCCESSFULLY ===');
  } finally {
    // Kill all app.exe and runtime_adapter.exe instances
    try {
      execSync('taskkill /F /IM app.exe /T', { stdio: 'ignore' });
      execSync('taskkill /F /IM runtime_adapter.exe /T', { stdio: 'ignore' });
    } catch (e) {}
  }
}

main().catch(err => {
  console.error('Test failed with error:', err);
  process.exit(1);
});
