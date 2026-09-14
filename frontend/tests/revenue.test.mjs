import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';

const source = await readFile(new URL('../src/utils/revenue.ts', import.meta.url), 'utf8');
const { formatRevenueAmount } = await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`);

test('revenue formatting preserves cents even beyond JavaScript safe integers', () => {
  assert.equal(formatRevenueAmount('9007199254740993.27'), '9,007,199,254,740,993.27');
  assert.equal(formatRevenueAmount('1000.00'), '1,000.00');
  assert.equal(formatRevenueAmount('0.00'), '0.00');
  assert.equal(formatRevenueAmount('-1234.05'), '-1,234.05');
});

test('formatting refuses amounts that have not been rounded by the server', () => {
  assert.throws(() => formatRevenueAmount('333.333'));
  assert.throws(() => formatRevenueAmount('NaN'));
});
