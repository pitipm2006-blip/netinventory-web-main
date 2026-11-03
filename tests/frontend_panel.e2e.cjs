// Prueba E2E del panel "Alertas y reportes" en Chromium real, con la API simulada.
// Requiere esbuild, react, react-dom y playwright (p. ej. instalados globalmente):
//   NODE_PATH=$(npm root -g) node tests/frontend_panel.e2e.cjs
const path = require('path');
const assert = require('assert');
const G = process.env.NODE_PATH || require('child_process').execSync('npm root -g').toString().trim();
const esbuild = require(path.join(G, 'tsx/node_modules/esbuild'));
const { chromium } = require(path.join(G, 'playwright'));

const ROOT = path.resolve(__dirname, '..', 'frontend', 'src');
const ALERTS = [
  { id_alerta: 2, nombre_host: 'sw-core-01', tipo: 'caida', mensaje: 'sw-core-01: 3 sondeos consecutivos sin respuesta', estado: 'abierta', fecha_apertura: '2026-11-02T10:00:00Z' },
  { id_alerta: 1, nombre_host: 'srv-db-02', tipo: 'latencia_alta', mensaje: 'srv-db-02: latencia superior a 200 ms en 3 sondeos', estado: 'resuelta', fecha_apertura: '2026-11-02T09:00:00Z' },
];

(async () => {
  const bundle = await esbuild.build({
    stdin: {
      contents: `import React from 'react'; import { createRoot } from 'react-dom/client';
        import Panel from './components/AlertsReportsPanel.jsx';
        window.apiCalls = [];
        const apiRequest = async (p) => { window.apiCalls.push(p); return window.__ALERTS__; };
        createRoot(document.getElementById('root')).render(<Panel apiRequest={apiRequest} />);`,
      resolveDir: ROOT, loader: 'jsx', sourcefile: 'entry.jsx',
    },
    bundle: true, write: false, format: 'iife', nodePaths: [G], jsx: 'automatic',
    define: { 'import.meta.env.VITE_API_URL': '"http://api.test"', 'process.env.NODE_ENV': '"production"' },
  });
  const js = bundle.outputFiles[0].text;

  const browser = await chromium.launch();
  const page = await browser.newPage({ acceptDownloads: true });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const seen = [];
  let failReports = false;
  await page.route('http://api.test/**', async (route) => {
    const req = route.request();
    seen.push({ url: req.url(), auth: req.headers()['authorization'] });
    if (failReports) return route.fulfill({ status: 500, body: 'boom' });
    const pdf = req.url().includes('formato=pdf');
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': pdf ? 'application/pdf' : 'text/csv' },
      body: pdf ? '%PDF-1.4 fake' : 'Host,IP\nsw-core-01,10.0.0.1\n',
    });
  });
  await page.route('http://app.test/', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' }));

  await page.goto('http://app.test/');
  await page.evaluate((a) => { window.__ALERTS__ = a; localStorage.setItem('netinventory_token', 'tok-123'); }, ALERTS);
  await page.addScriptTag({ content: js });

  await page.waitForSelector('text=sw-core-01');
  const rows = await page.locator('section:has-text("Alertas recientes") tbody tr').count();
  assert.strictEqual(rows, 2, 'deben verse 2 alertas');
  assert.ok(await page.locator('text=abierta').count() >= 1);
  assert.ok((await page.evaluate(() => window.apiCalls)).includes('/api/v1/alerts?limit=50'));
  console.log('ok  tabla de alertas renderiza 2 filas y consulta /api/v1/alerts');

  const reports = await page.locator('section:has-text("Exportar reportes") tbody tr').count();
  assert.strictEqual(reports, 3);
  console.log('ok  3 reportes disponibles (activos, IPAM, alertas)');

  const downloads = [];
  for (const [row, fmt] of [['Inventario de activos', 'CSV'], ['Estado de IPAM', 'PDF'], ['Historial de alertas', 'CSV']]) {
    const [dl] = await Promise.all([
      page.waitForEvent('download'),
      page.locator(`tr:has-text("${row}") button:text-is("${fmt}")`).click(),
    ]);
    downloads.push(dl.suggestedFilename());
  }
  assert.deepStrictEqual(downloads, ['devices.csv', 'ipam.pdf', 'alerts.csv']);
  const reportCalls = seen.filter((s) => s.url.includes('/reports/'));
  assert.deepStrictEqual(reportCalls.map((s) => s.url), [
    'http://api.test/api/v1/reports/devices?formato=csv',
    'http://api.test/api/v1/reports/ipam?formato=pdf',
    'http://api.test/api/v1/reports/alerts?formato=csv',
  ]);
  assert.ok(reportCalls.every((s) => s.auth === 'Bearer tok-123'), 'debe enviar el token');
  console.log('ok  descargas con nombre correcto, URL correcta y token Bearer');

  failReports = true;
  await page.locator('tr:has-text("Estado de IPAM") button:text-is("CSV")').click();
  await page.waitForSelector('.error-box');
  assert.ok((await page.locator('.error-box').innerText()).includes('HTTP 500'));
  console.log('ok  un error del servidor se muestra al usuario (HTTP 500)');

  assert.deepStrictEqual(errors, [], 'sin errores de JavaScript en la página');
  console.log('ok  sin errores de JavaScript en consola');
  await browser.close();
})().catch((e) => { console.error('FALLO:', e.message); process.exit(1); });
