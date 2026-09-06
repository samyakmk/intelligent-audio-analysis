type KeyFactory = () => string;

const pendingKeys = new Map<string, string>();

/**
 * Return one stable key for an operation until the caller observes a
 * definitive response. This covers the important case where the server commits
 * but the response is lost and the user retries the same action.
 */
export function acquireOperationKey(signature: string, create: KeyFactory): string {
  const existing = pendingKeys.get(signature);
  if (existing) return existing;
  const created = create();
  pendingKeys.set(signature, created);
  return created;
}

/** Only the request that owns the current key may retire it. */
export function retireOperationKey(signature: string, key: string): void {
  if (pendingKeys.get(signature) === key) pendingKeys.delete(signature);
}

export function operationSignature(
  sessionScope: string | undefined,
  method: string,
  path: string,
  body: unknown,
): string {
  return JSON.stringify([sessionScope ?? 'anonymous', method, path, body ?? null]);
}

export function resetOperationKeysForTests(): void {
  pendingKeys.clear();
}
