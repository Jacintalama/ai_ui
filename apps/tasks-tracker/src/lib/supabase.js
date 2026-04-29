// Returns the shared Supabase client initialised in index.html.
// Never call createClient here — the module re-evaluates on hot-reload.
export function getDb() {
  return window.supabase || null;
}

export function configured() {
  return !!(window.SUPABASE_URL && window.SUPABASE_ANON_KEY);
}
