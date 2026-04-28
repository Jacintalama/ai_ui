import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const SUPABASE_URL = window.SUPABASE_URL || window.ENV?.SUPABASE_URL;
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || window.ENV?.SUPABASE_ANON_KEY;

export const db = (SUPABASE_URL && SUPABASE_ANON_KEY)
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;

export const configured = !!(SUPABASE_URL && SUPABASE_ANON_KEY);
