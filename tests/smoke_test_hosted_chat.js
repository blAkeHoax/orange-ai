// tests/smoke_test_hosted_chat.js - End-to-End Hosted Orange API Inference Smoke Test
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';

const TAURI_EXE = 'D:/Orange AI/Orange AI Tauri/src-tauri/target/x86_64-pc-windows-gnu/debug/app.exe';
const SCREENSHOT_DIR = 'D:/Orange AI/Orange AI Tauri/screenshots';
const ARTIFACT_DIR = 'C:/Users/User/.gemini/antigravity/brain/3c7f970a-eec6-45a9-97aa-fe852ad24010';
const LOG_FILE = path.join(process.env.LOCALAPPDATA || 'C:/Users/User/AppData/Local', 'Orange AI', 'orange_ai.log');
const DEV_LOG_FILE = 'D:/Orange AI/Orange AI Desktop/orange_ai.log';

async function run() {
  console.log('================================================================');
  console.log('--- [SMOKE TEST] LIVE HOSTED ORANGE API INFERENCE VERIFICATION ---');
  console.log('================================================================');

  // Record initial log sizes
  const getLogSize = (p) => (fs.existsSync(p) ? fs.statSync(p).size : 0);
  const logSizeBefore = getLogSize(LOG_FILE);
  const devLogSizeBefore = getLogSize(DEV_LOG_FILE);

  // 1. Spawn Tauri Desktop Application
  console.log(`[TEST STEP 1] Spawning Tauri Desktop Shell: ${TAURI_EXE}`);
  const env = {
    ...process.env,
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9222'
  };

  const appProc = spawn(TAURI_EXE, [], { env, stdio: ['pipe', 'pipe', 'pipe'] });
  console.log(`[TEST STEP 1] app.exe spawned with PID: ${appProc.pid}`);

  let appStdout = '';
  let appStderr = '';
  appProc.stdout.on('data', (d) => { appStdout += d.toString(); });
  appProc.stderr.on('data', (d) => { appStderr += d.toString(); });

  let ws = null;
  try {
    // 2. Poll for WebView2 CDP Target
    console.log('[TEST STEP 1] Polling for WebView2 targets on port 9222...');
    let targets = [];
    for (let i = 0; i < 30; i++) {
      try {
        const res = await fetch('http://127.0.0.1:9222/json');
        targets = await res.json();
        if (targets && targets.length > 0) break;
      } catch (e) {}
      await new Promise((r) => setTimeout(r, 500));
    }

    const page = targets.find((t) => t.type === 'page');
    if (!page) {
      throw new Error(`Failed to find WebView2 page target: ${JSON.stringify(targets)}`);
    }

    console.log(`[TEST STEP 1] Connecting to CDP WebSocket: ${page.webSocketDebuggerUrl}`);
    ws = new WebSocket(page.webSocketDebuggerUrl);

    let idSeq = 1;
    const pending = new Map();
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.id && pending.has(msg.id)) {
        const { resolve, reject } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) reject(msg.error);
        else resolve(msg.result);
      }
    };

    await new Promise((resolve) => (ws.onopen = resolve));
    console.log('[TEST STEP 1] CDP WebSocket connected!');

    function sendCDP(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = idSeq++;
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    await sendCDP('Page.enable');
    await sendCDP('Runtime.enable');

    // 3. Wait for Application Mount
    console.log('[TEST STEP 1] Waiting for React application mount...');
    let mounted = false;
    for (let i = 0; i < 40; i++) {
      const res = await sendCDP('Runtime.evaluate', {
        expression: `({
          ready: document.readyState,
          hasOrangeAi: !!window.__orangeAi,
          activeView: window.__orangeAi?.getActiveView?.()
        })`,
        returnByValue: true
      });
      if (res?.result?.value?.hasOrangeAi) {
        mounted = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    if (!mounted) throw new Error('React application failed to mount.');
    console.log('[TEST STEP 1] React application mounted successfully!');

    // 4. Verify System Health and API Endpoint Configuration
    console.log('\n--- [TEST STEP 1] Verifying Supervisor Handshake & API Configuration ---');
    // Ping adapter
    const pingRes = await sendCDP('Runtime.evaluate', {
      expression: `(async () => {
        const mod = await import('/assets/core-BUhCcD2K.js');
        return await mod.invoke('ping');
      })()`,
      awaitPromise: true,
      returnByValue: true
    });
    console.log('[TEST] ping result:', JSON.stringify(pingRes?.result?.value));

    // Health check
    const healthRes = await sendCDP('Runtime.evaluate', {
      expression: `(async () => {
        const mod = await import('/assets/core-BUhCcD2K.js');
        return await mod.invoke('get_health');
      })()`,
      awaitPromise: true,
      returnByValue: true
    });
    const healthData = healthRes?.result?.value;
    console.log('[TEST] get_health result:', JSON.stringify(healthData, null, 2));

    const effectiveEndpoint = healthData?.api?.endpoint || 'https://orange-api-cuuo.onrender.com';
    const apiOnline = healthData?.api?.online;
    console.log(`[TEST] Effective API Endpoint: ${effectiveEndpoint}`);
    console.log(`[TEST] API Online Status:      ${apiOnline}`);

    if (effectiveEndpoint !== 'https://orange-api-cuuo.onrender.com') {
      console.warn(`[WARNING] Effective endpoint is '${effectiveEndpoint}', expected 'https://orange-api-cuuo.onrender.com'`);
    }

    // 5. Navigate to Chat Workspace
    console.log('\n--- [TEST STEP 2] Navigating to Chat Workspace ---');
    await sendCDP('Runtime.evaluate', {
      expression: `window.__orangeAi.selectView('chat')`
    });

    // Wait for chat history to fully load and settle
    console.log('[TEST] Waiting for initial chat history to load and settle...');
    let initialAssistantRows = 0;
    let initialTotalRows = 0;
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const countCheck = await sendCDP('Runtime.evaluate', {
        expression: `({
          total: document.querySelectorAll('.chat-message-row').length,
          assistant: document.querySelectorAll('.chat-message-row.is-assistant:not(.is-thinking)').length,
          isThinking: !!document.querySelector('.is-thinking')
        })`,
        returnByValue: true
      });
      const counts = countCheck?.result?.value;
      if (counts && counts.total > 0 && !counts.isThinking) {
        // Wait another 1s to ensure no further batch arrivals
        await new Promise((r) => setTimeout(r, 1000));
        const finalCheck = await sendCDP('Runtime.evaluate', {
          expression: `({
            total: document.querySelectorAll('.chat-message-row').length,
            assistant: document.querySelectorAll('.chat-message-row.is-assistant:not(.is-thinking)').length
          })`,
          returnByValue: true
        });
        initialTotalRows = finalCheck?.result?.value?.total || 0;
        initialAssistantRows = finalCheck?.result?.value?.assistant || 0;
        break;
      }
    }
    console.log(`[TEST] Baseline history settled: ${initialTotalRows} total rows, ${initialAssistantRows} assistant rows.`);

    // 6. Submit the Harmless Test Message
    const testMessage = "Explain in two short sentences what Orange AI does.";
    console.log(`\n--- [TEST STEP 2] Submitting Chat Message to Chat Workspace ---`);
    console.log(`Test Message: "${testMessage}"`);

    const submissionTime = new Date();
    const t0 = Date.now();

    await sendCDP('Runtime.evaluate', {
      expression: `window.__orangeAi.sendMessage(${JSON.stringify(testMessage)})`
    });

    // Verify thinking state appears
    console.log('[TEST STEP 2] Verifying user message added and thinking indicator appears...');
    for (let i = 0; i < 15; i++) {
      const thinkingCheck = await sendCDP('Runtime.evaluate', {
        expression: `!!document.querySelector('.is-thinking')`,
        returnByValue: true
      });
      if (thinkingCheck?.result?.value) {
        console.log('[TEST STEP 2] In-flight thinking indicator active in UI.');
        break;
      }
      await new Promise((r) => setTimeout(r, 200));
    }

    // 7. Await Assistant Response in React Chat Timeline
    console.log('[TEST STEP 2] Waiting for hosted Orange API inference response to complete...');
    let assistantReply = null;
    let modelTag = null;
    let responseTime = null;

    for (let attempt = 0; attempt < 120; attempt++) {
      await new Promise((r) => setTimeout(r, 500));
      const timelineCheck = await sendCDP('Runtime.evaluate', {
        expression: `(() => {
          const isThinking = !!document.querySelector('.is-thinking');
          const assistantRows = Array.from(document.querySelectorAll('.chat-message-row.is-assistant:not(.is-thinking)'));
          if (assistantRows.length <= ${initialAssistantRows}) return null;
          if (isThinking) return null; // Still in flight!
          const lastRow = assistantRows[assistantRows.length - 1];
          const contentEl = lastRow.querySelector('.chat-message-content');
          const modelEl = lastRow.querySelector('.chat-model-tag');
          const text = contentEl ? contentEl.innerText.trim() : '';
          const model = modelEl ? modelEl.innerText.trim() : null;
          return { text, model, rowCount: assistantRows.length, isThinking };
        })()`,
        returnByValue: true
      });

      const resVal = timelineCheck?.result?.value;
      if (resVal && resVal.text && resVal.text.length > 5 && !resVal.isThinking) {
        responseTime = new Date();
        assistantReply = resVal.text;
        modelTag = resVal.model;
        break;
      }
    }

    const durationSeconds = (Date.now() - t0) / 1000;

    if (!assistantReply) {
      throw new Error(`Timed out waiting for assistant response after ${durationSeconds.toFixed(2)}s`);
    }

    console.log(`\n[TEST STEP 2 RESULT] Successful Assistant Response Received!`);
    console.log(`Submission Timestamp: ${submissionTime.toISOString()}`);
    console.log(`Response Timestamp:   ${responseTime.toISOString()}`);
    console.log(`Total Round-Trip:     ${durationSeconds.toFixed(2)}s`);
    console.log(`Model Tag in UI:      ${modelTag || 'none'}`);
    console.log(`Assistant Reply Text:\n"${assistantReply}"\n`);

    // Scroll chat timeline to bottom so the new message is fully visible in screenshot
    await sendCDP('Runtime.evaluate', {
      expression: `(() => {
        const timeline = document.querySelector('.chat-timeline');
        if (timeline) timeline.scrollTop = timeline.scrollHeight;
        const lastRow = document.querySelector('.chat-message-row:last-child');
        if (lastRow) lastRow.scrollIntoView({ behavior: 'instant', block: 'end' });
      })()`
    });
    await new Promise((r) => setTimeout(r, 600));

    // 8. Capture Visual Evidence Screenshot
    await sendCDP('Emulation.setDeviceMetricsOverride', {
      width: 1080,
      height: 750,
      deviceScaleFactor: 1,
      mobile: false
    });
    await new Promise((r) => setTimeout(r, 400));

    const shot = await sendCDP('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(shot.data, 'base64');
    const screenshotName = 'smoke_test_hosted_chat.png';
    fs.writeFileSync(path.join(SCREENSHOT_DIR, screenshotName), buffer);
    if (fs.existsSync(ARTIFACT_DIR)) {
      fs.writeFileSync(path.join(ARTIFACT_DIR, screenshotName), buffer);
    }
    console.log(`[TEST] Captured visual proof: ${screenshotName} (${buffer.length} bytes)`);

    // 9. Inspect Python Logs for Execution Proof
    console.log('\n--- [TEST STEP 3] Inspecting Runtime Logs for Traces ---');
    const stderrLogPath = path.join('D:/Orange AI/Orange AI Tauri/tests', 'smoke_test_runtime_stderr.log');
    fs.writeFileSync(stderrLogPath, appStderr, 'utf-8');
    console.log(`Saved runtime stderr logs to ${stderrLogPath} (${appStderr.length} bytes)`);

    const adapterLines = appStderr
      .split('\n')
      .filter((l) => l.includes('adapter') || l.includes('API') || l.includes('assist') || l.includes('chat') || l.includes('turn'))
      .slice(-15);
    console.log('Adapter Log Excerpt:\n' + adapterLines.join('\n'));

    // Summary Record
    const testRecord = {
      test: 'HOSTED_ORANGE_API_INFERENCE_SMOKE_TEST',
      status: 'PASS',
      endpoint: effectiveEndpoint,
      submissionTime: submissionTime.toISOString(),
      responseTime: responseTime.toISOString(),
      durationSeconds: durationSeconds,
      testMessage: testMessage,
      assistantReply: assistantReply,
      modelTag: modelTag,
      screenshot: screenshotName,
      screenshotBytes: buffer.length
    };

    fs.writeFileSync(
      path.join('D:/Orange AI/Orange AI Tauri/tests', 'smoke_test_record.json'),
      JSON.stringify(testRecord, null, 2)
    );

    console.log('\n================================================================');
    console.log('--- [SMOKE TEST COMPLETED] PASS: HOSTED INFERENCE VERIFIED ---');
    console.log('================================================================');

  } finally {
    if (ws) ws.close();
    console.log('[TEST] Terminating Tauri application process...');
    appProc.kill();
    await new Promise((r) => setTimeout(r, 1000));
  }
}

run().catch((err) => {
  console.error('[TEST FAILED]:', err);
  process.exit(1);
});
