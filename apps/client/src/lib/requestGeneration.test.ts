import { describe, expect, it } from 'vitest';

import { RequestGeneration } from './requestGeneration';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('latest request generation', () => {
  it('rejects a stale response that completes after a newer workspace request', async () => {
    const gate = new RequestGeneration();
    const oldWorkspace = deferred<string>();
    const newWorkspace = deferred<string>();
    const committed: string[] = [];

    const track = async (promise: Promise<string>) => {
      const generation = gate.begin();
      const value = await promise;
      if (gate.isCurrent(generation)) committed.push(value);
    };

    const oldLoad = track(oldWorkspace.promise);
    const newLoad = track(newWorkspace.promise);
    newWorkspace.resolve('workspace-beta');
    await newLoad;
    oldWorkspace.resolve('workspace-alpha');
    await oldLoad;

    expect(committed).toEqual(['workspace-beta']);
  });

  it('invalidates an in-flight response when local data replaces it', () => {
    const gate = new RequestGeneration();
    const pending = gate.begin();
    gate.invalidate();
    expect(gate.isCurrent(pending)).toBe(false);
  });
});
