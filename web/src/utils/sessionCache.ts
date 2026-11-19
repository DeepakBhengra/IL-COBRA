const buckets = new Map<string, Map<string, unknown>>();

export function readSessionCache<T>(bucket: string, key: string): T | undefined {
  const value = buckets.get(bucket)?.get(key);
  return value as T | undefined;
}

export function writeSessionCache<T>(bucket: string, key: string, value: T): void {
  let store = buckets.get(bucket);
  if (!store) {
    store = new Map();
    buckets.set(bucket, store);
  }
  store.set(key, value);
}
