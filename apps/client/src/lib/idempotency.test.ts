import { beforeEach, describe, expect, it } from 'vitest';

import {
  acquireOperationKey,
  operationSignature,
  resetOperationKeysForTests,
  retireOperationKey,
} from './idempotency';

describe('idempotent client operations', () => {
  beforeEach(resetOperationKeysForTests);

  it('reuses a key until a definitive response retires it', () => {
    const signature = operationSignature('session-a', 'POST', '/v1/recaps', {
      kind: 'daily',
    });
    let sequence = 0;
    const create = () => `key-${++sequence}`;

    const first = acquireOperationKey(signature, create);
    expect(acquireOperationKey(signature, create)).toBe(first);

    retireOperationKey(signature, first);
    expect(acquireOperationKey(signature, create)).toBe('key-2');
  });

  it('does not let a stale completion retire a newer operation key', () => {
    const signature = operationSignature('session-a', 'POST', '/v1/ask', {
      content: 'What changed?',
    });
    const first = acquireOperationKey(signature, () => 'first');
    retireOperationKey(signature, first);
    expect(acquireOperationKey(signature, () => 'second')).toBe('second');

    retireOperationKey(signature, first);
    expect(acquireOperationKey(signature, () => 'third')).toBe('second');
  });

  it('scopes otherwise identical operations to the active session', () => {
    const body = { kind: 'daily' };
    const alpha = operationSignature('csrf-alpha', 'POST', '/v1/recaps', body);
    const beta = operationSignature('csrf-beta', 'POST', '/v1/recaps', body);

    expect(alpha).not.toBe(beta);
  });
});
