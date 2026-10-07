const SUPABASE_URL = window.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || '';

export const supabaseConnected = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY && window.supabase);

export const supabase = supabaseConnected
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;
