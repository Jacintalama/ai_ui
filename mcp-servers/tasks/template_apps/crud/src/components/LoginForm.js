import { supabase, supabaseConnected } from '../lib/supabase.js';

export function loginForm() {
  return {
    mode: 'signin',
    email: '',
    password: '',
    loading: false,
    error: null,
    init() {},
    async submit() {
      this.error = null;
      this.loading = true;
      try {
        if (!supabaseConnected) {
          // Fallback: pretend we logged in
          await new Promise(r => setTimeout(r, 300));
          window.location.hash = '#/';
          return;
        }
        if (this.mode === 'signup') {
          const { error } = await supabase.auth.signUp({ email: this.email, password: this.password });
          if (error) throw error;
          this.error = null;
          // Some Supabase projects require email confirmation
          alert('Check your email to confirm your account, then sign in.');
          this.mode = 'signin';
        } else {
          const { error } = await supabase.auth.signInWithPassword({ email: this.email, password: this.password });
          if (error) throw error;
          window.location.hash = '#/';
        }
      } catch (e) {
        this.error = e?.message || 'Something went wrong.';
      } finally {
        this.loading = false;
      }
    }
  };
}
