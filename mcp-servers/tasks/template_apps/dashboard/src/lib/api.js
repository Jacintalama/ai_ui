import { supabase, supabaseConnected } from './supabase.js';

const EVENT_TYPES = ['page_view', 'signup', 'login', 'click', 'purchase', 'invite_sent', 'export'];
const USERS = ['ada@example.com', 'lin@example.com', 'maya@example.com', 'kai@example.com', 'sam@example.com', 'remy@example.com'];

function rng(seed) {
  let s = seed;
  return () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
}

function generateMockEvents(days) {
  const r = rng(days * 13 + 7);
  const now = Date.now();
  const events = [];
  const perDay = days <= 7 ? 80 : days <= 30 ? 40 : 18;
  for (let d = 0; d < days; d++) {
    for (let i = 0; i < perDay + Math.floor(r() * 25); i++) {
      const ts = now - (d * 86400000) - Math.floor(r() * 86400000);
      events.push({
        id: events.length + 1,
        user: USERS[Math.floor(r() * USERS.length)],
        event_type: EVENT_TYPES[Math.floor(r() * EVENT_TYPES.length)],
        details: { path: '/' + ['home','pricing','docs','app','signup'][Math.floor(r()*5)] },
        created_at: new Date(ts).toISOString()
      });
    }
  }
  return events.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function fetchEvents(userId, days = 30) {
  if (!supabaseConnected) return generateMockEvents(days);
  const since = new Date(Date.now() - days * 86400000).toISOString();
  const { data, error } = await supabase
    .from('events')
    .select('id, user_id, event_type, details, created_at')
    .gte('created_at', since)
    .order('created_at', { ascending: false })
    .limit(2000);
  if (error) throw error;
  return (data || []).map(e => ({ ...e, user: e.user_id }));
}

// KPI snapshot — reduced from events array
export function summarize(events, days) {
  const now = Date.now();
  const halfWindow = (days / 2) * 86400000;
  const cutoff = now - halfWindow;
  const recent = events.filter(e => new Date(e.created_at).getTime() >= cutoff);
  const prior = events.filter(e => new Date(e.created_at).getTime() < cutoff);

  const uniqueUsers = arr => new Set(arr.map(e => e.user)).size;
  const sessions = arr => arr.filter(e => e.event_type === 'page_view').length;

  const trend = (a, b) => b === 0 ? 0 : Math.round(((a - b) / b) * 100);

  // Sparkline: events per day for the window
  const buckets = new Array(days).fill(0);
  events.forEach(e => {
    const d = Math.floor((now - new Date(e.created_at).getTime()) / 86400000);
    if (d >= 0 && d < days) buckets[days - 1 - d]++;
  });

  return {
    activeUsers: { value: uniqueUsers(recent), trend: trend(uniqueUsers(recent), uniqueUsers(prior)), spark: buckets },
    sessions: { value: sessions(recent), trend: trend(sessions(recent), sessions(prior)), spark: buckets },
    avgSession: { value: '3m 42s', trend: 4, spark: buckets },
    bounce: { value: '38%', trend: -2, spark: buckets }
  };
}

// Daily series for primary chart
export function dailySeries(events, days) {
  const now = Date.now();
  const labels = [];
  const counts = new Array(days).fill(0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now - i * 86400000);
    labels.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
  }
  events.forEach(e => {
    const offset = Math.floor((now - new Date(e.created_at).getTime()) / 86400000);
    if (offset >= 0 && offset < days) counts[days - 1 - offset]++;
  });
  return { labels, counts };
}

// Top events for bar chart
export function topEvents(events) {
  const map = {};
  events.forEach(e => { map[e.event_type] = (map[e.event_type] || 0) + 1; });
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([k, v]) => ({ label: k, value: v }));
}
