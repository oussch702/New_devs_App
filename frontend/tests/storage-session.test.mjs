import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';

for (const version of [null, '1.0.0', 'unknown-version']) {
  test(`storage migration preserves local login when version is ${version}`, async () => {
    const serializedSession = JSON.stringify({ access_token: 'test-token', user: { id: 'ocean' } });
    const storage = new Map([['base360-auth-token', serializedSession]]);
    if (version) storage.set('app_storage_version', version);
    globalThis.localStorage = {
      get length() { return storage.size; },
      key: index => [...storage.keys()][index],
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
      clear: () => storage.clear(),
    };
    const source = await readFile(new URL('../src/utils/localStorageManager.ts', import.meta.url), 'utf8');
    const isolated = source.replace(/^import .*;$/gm, '').replace(/^export \{.*from .*;$/gm, '');
    const compiled = stripTypeScriptTypes(isolated);
    await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${version}`);
    assert.equal(localStorage.getItem('base360-auth-token'), serializedSession);
    assert.equal(localStorage.getItem('app_storage_version'), '2.0.0');
  });
}
