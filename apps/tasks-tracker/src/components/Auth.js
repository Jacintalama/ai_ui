export function initAuth({ getDb, configured, authSection, appSection, onSignedIn }) {
  const errorBannerAuth = document.getElementById('error-banner-auth');
  const authSubmit = document.getElementById('auth-submit');
  const authToggleLink = document.getElementById('auth-toggle-link');
  const authToggleText = document.getElementById('auth-toggle-text');

  function showAuthError(msg) {
    errorBannerAuth.textContent = msg;
    errorBannerAuth.style.display = 'block';
  }

  if (!configured()) {
    authSection.style.display = 'block';
    showAuthError('Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in the environment.');
    return;
  }

  let authMode = 'signin';

  authToggleLink.addEventListener('click', () => {
    authMode = authMode === 'signin' ? 'signup' : 'signin';
    authSubmit.textContent = authMode === 'signin' ? 'Sign in' : 'Sign up';
    authToggleText.textContent = authMode === 'signin' ? 'No account?' : 'Already have an account?';
    authToggleLink.textContent = authMode === 'signin' ? 'Sign up' : 'Sign in';
    errorBannerAuth.style.display = 'none';
  });

  authSubmit.addEventListener('click', async () => {
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!email || !password) { showAuthError('Email and password are required.'); return; }
    errorBannerAuth.style.display = 'none';
    authSubmit.disabled = true;

    const db = getDb();
    const { error } = authMode === 'signin'
      ? await db.auth.signInWithPassword({ email, password })
      : await db.auth.signUp({ email, password });

    authSubmit.disabled = false;
    if (error) { showAuthError(error.message); return; }
  });

  document.getElementById('signout-btn').addEventListener('click', async () => {
    await getDb().auth.signOut();
  });

  function handleSession(session) {
    if (session) {
      authSection.style.display = 'none';
      appSection.style.display = 'block';
      onSignedIn();
    } else {
      authSection.style.display = 'block';
      appSection.style.display = 'none';
    }
  }

  const authDb = getDb();
  authDb.auth.onAuthStateChange((_event, session) => handleSession(session));
  authDb.auth.getSession().then(({ data }) => handleSession(data.session));
}
