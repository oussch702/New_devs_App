import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';

async function loadClient() {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const source = await readFile(new URL('../src/lib/localAuthClient.ts', import.meta.url), 'utf8');
  const compiled = stripTypeScriptTypes(source.replaceAll('import.meta.env', '({})'));
  const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${Math.random()}`);
  return module.localAuthClient;
}

const session = name => ({
  access_token: `token-${name}`,
  token_type: 'bearer',
  user: { id: name, email: `${name}@example.com`, tenant_id: `tenant-${name}` },
});

test('login returns the response shape consumed by AuthContext', async () => {
  const client = await loadClient();
  globalThis.fetch = async () => Response.json(session('a'));
  const result = await client.auth.signInWithPassword({ email: 'a@example.com', password: 'test' });
  assert.equal(result.error, null);
  assert.equal(result.data?.session?.user.id, 'a');
});

test('getUser returns the response shape consumed by session validation', async () => {
  const client = await loadClient();
  globalThis.fetch = async () => Response.json(session('a').user);
  const result = await client.auth.getUser('token-a');
  assert.equal(result.data?.user?.id, 'a');
  assert.equal(result.error, null);
});

test('an older failed validation cannot sign out a newer account', async () => {
  const client = await loadClient();
  await client.auth.setSession(session('a'));
  let complete;
  globalThis.fetch = () => new Promise(resolve => { complete = resolve; });
  const pending = client.auth.getSession();
  await client.auth.setSession(session('b'));
  complete(new Response(null, { status: 401 }));
  await pending;
  globalThis.fetch = async () => Response.json(session('b').user);
  const result = await client.auth.getSession();
  assert.equal(result.data.session?.user.id, 'b');
});

test('logout clears local session before waiting for the server', async () => {
  const client = await loadClient();
  await client.auth.setSession(session('a'));
  let complete;
  globalThis.fetch = () => new Promise(resolve => { complete = resolve; });
  const pending = client.auth.signOut();
  assert.equal(localStorage.getItem('base360-auth-token'), null);
  complete(new Response(null, { status: 204 }));
  await pending;
});

test('a login response arriving after logout cannot restore authentication', async () => {
  const client = await loadClient();
  let complete;
  globalThis.fetch = () => new Promise(resolve => { complete = resolve; });
  const pending = client.auth.signInWithPassword({ email: 'a@example.com', password: 'test' });
  await client.auth.signOut();
  complete(Response.json(session('a')));
  const result = await pending;
  assert.ok(result.error);
  assert.equal(result.data.session, null);
  assert.equal(localStorage.getItem('base360-auth-token'), null);
});
