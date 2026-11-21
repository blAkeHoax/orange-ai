import { spawn } from 'child_process';
import path from 'path';

const appPath = path.join(
  'D:/Orange AI/Orange AI Tauri/src-tauri/target/x86_64-pc-windows-gnu/debug/app.exe'
);

console.log('Spawning app.exe...');
const child = spawn(appPath, [], {
  env: { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9222' },
  stdio: 'ignore'
});

async function run() {
  await new Promise((r) => setTimeout(r, 2000));
  try {
    const res = await fetch('http://127.0.0.1:9222/json');
    const targets = await res.json();
    const page = targets.find((t) => t.type === 'page');
    if (!page) {
      console.log('No page target found');
      return;
    }
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r) => (ws.onopen = r));

    let id = 1;
    function send(method, params = {}) {
      return new Promise((resolve) => {
        const reqId = id++;
        const onMsg = (evt) => {
          const m = JSON.parse(evt.data);
          if (m.id === reqId) {
            ws.removeEventListener('message', onMsg);
            resolve(m.result);
          }
        };
        ws.addEventListener('message', onMsg);
        ws.send(JSON.stringify({ id: reqId, method, params }));
      });
    }

    await send('Runtime.enable');
    // Select settings view
    await send('Runtime.evaluate', {
      expression: `window.__orangeAi?.selectView('settings');`
    });

    // Wait 2.5 seconds for remote API health check to resolve
    await new Promise((r) => setTimeout(r, 2500));

    const check = await send('Runtime.evaluate', {
      expression: `({
        endpointText: document.querySelector('.connection-info code')?.textContent,
        statusText: document.querySelector('.status-pill-connection span')?.textContent
      })`,
      returnByValue: true
    });
    console.log('Settings View after full resolution:', check?.result?.value);

    ws.close();
  } catch (err) {
    console.error('Error during test:', err);
  } finally {
    child.kill();
  }
}

run();
