import http from 'http';

// Test reaching the real Render.com Orange API
const url = 'https://orange-api-cuuo.onrender.com/health';
console.log('Pinging:', url);
const start = Date.now();
try {
  const res = await fetch(url);
  const data = await res.json();
  const dur = Date.now() - start;
  console.log(`Render API health response in ${dur}ms:`, data);
} catch (e) {
  console.error('Failed to reach Render API:', e.message);
}
