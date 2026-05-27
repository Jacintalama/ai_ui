// localStorage hydration/save scoped by namespace.
// Wraps every read/write in try/catch — private browsing or quota issues
// must NOT crash the app.
export function createPersistence({ namespace, keys }) {
  const ns = (k) => `io-template:${namespace}:${k}`;
  const obj = {
    _hydrate() {
      for (const k of keys) {
        try {
          const raw = localStorage.getItem(ns(k));
          if (raw !== null) this[k] = JSON.parse(raw);
        } catch { /* private browsing / corrupted entry: ignore */ }
      }
    },
    _save(k) {
      try {
        localStorage.setItem(ns(k), JSON.stringify(this[k]));
      } catch { /* quota exceeded or disabled: ignore */ }
    },
  };
  for (const k of keys) obj[k] = [];   // default empty array per key
  return obj;
}
