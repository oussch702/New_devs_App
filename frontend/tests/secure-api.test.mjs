import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';

function token(tenant) {
  return `header.${Buffer.from(JSON.stringify({ sub: tenant, email: `${tenant}@example.com`, tenant_id: tenant })).toString('base64url')}.signature`;
}

async function loadAPI() {
  const source = await readFile(new URL('../src/lib/secureApi.ts', import.meta.url), 'utf8');
  // Keep the actual request/cache code, replacing only its unrelated auth dependencies.
  const isolated = source.replace(/^import .*;$/gm, '').replaceAll('import.meta.env', '({})');
  const stubs = `const supabase = {auth: {getSession: async () => ({data: {session: null}})}}; const sessionManager = {};`;
  const compiled = stripTypeScriptTypes(stubs + isolated);
  const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${Math.random()}`);
  return module.SecureAPI;
}

test('cached property summaries are isolated by tenant and reporting period', async () => {
  const api = await loadAPI();
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, authorization: options.headers.Authorization });
    return Response.json({ total_revenue: options.headers.Authorization === `Bearer ${token('tenant-a')}` ? '2250.00' : '0.00' });
  };
  api.setAccessToken(token('tenant-a'));
  assert.equal((await api.getDashboardSummary('prop-001', { year: 2024, month: 3 })).total_revenue, '2250.00');
  await api.getDashboardSummary('prop-001', { year: 2024, month: 3 });
  assert.equal(calls.length, 1, 'opaque tenant IDs should receive an isolated cache hit');
  await api.getDashboardSummary('prop-001', { year: 2024, month: 2 });
  assert.equal(calls.length, 2);
  api.setAccessToken(token('tenant-b'));
  assert.equal((await api.getDashboardSummary('prop-001', { year: 2024, month: 3 })).total_revenue, '0.00');
  assert.equal(calls.length, 3);
  assert.equal(calls[2].authorization, `Bearer ${token('tenant-b')}`);
});

test('a delayed prior-account response is rejected and cannot refill a cleared cache', async () => {
  const api = await loadAPI();
  let complete;
  let markStarted;
  const started = new Promise(resolve => { markStarted = resolve; });
  globalThis.fetch = () => {
    markStarted();
    return new Promise(resolve => { complete = resolve; });
  };
  api.setAccessToken(token('tenant-a'));
  const pending = api.getDashboardSummary('prop-001', { year: 2024, month: 3 });
  await started;
  api.setAccessToken(token('tenant-b'));
  complete(Response.json({ total_revenue: '2250.00' }));
  await assert.rejects(pending, /Session changed/);
  assert.equal(api.getCacheDiagnostics().totalCacheEntries, 0);
  globalThis.fetch = async () => Response.json({ total_revenue: '0.00' });
  assert.equal((await api.getDashboardSummary('prop-001', { year: 2024, month: 3 })).total_revenue, '0.00');
});

test('a forbidden request is not retried', async () => {
  const api = await loadAPI();
  let calls = 0;
  api.setAccessToken(token('tenant-a'));
  globalThis.fetch = async () => {
    calls++;
    return Response.json({ detail: 'Forbidden' }, { status: 403 });
  };
  await assert.rejects(api.getDashboardProperties(), /Forbidden/);
  assert.equal(calls, 1);
});

test('reading an old unauthorized response body cannot clear a new login', async () => {
  const api = await loadAPI();
  let completeBody;
  let bodyStarted;
  const started = new Promise(resolve => { bodyStarted = resolve; });
  api.setAccessToken(token('tenant-a'));
  globalThis.fetch = async () => ({
    ok: false, status: 401,
    text: () => {
      bodyStarted();
      return new Promise(resolve => { completeBody = resolve; });
    },
  });
  const pending = api.getDashboardProperties();
  await started;
  api.setAccessToken(token('tenant-b'));
  completeBody('{"detail":"Expired token"}');
  await assert.rejects(pending, /Session changed/);
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.headers.Authorization, `Bearer ${token('tenant-b')}`);
    return Response.json({ properties: [] });
  };
  assert.deepEqual(await api.getDashboardProperties(), { properties: [] });
});
