import { supabase, supabaseConnected } from './supabase.js';

const LS_KEY = 'todo-list-fallback-v1';

function readLocal() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); }
  catch { return []; }
}
function writeLocal(items) { localStorage.setItem(LS_KEY, JSON.stringify(items)); }

export async function listTodos(userId) {
  if (!supabaseConnected) return readLocal();
  const { data, error } = await supabase
    .from('todos')
    .select('id, title, completed, created_at')
    .eq('user_id', userId)
    .order('created_at', { ascending: false });
  if (error) throw error;
  return data || [];
}

export async function createTodo(userId, title) {
  if (!supabaseConnected) {
    const items = readLocal();
    const t = { id: crypto.randomUUID(), title, completed: false, created_at: new Date().toISOString() };
    items.unshift(t);
    writeLocal(items);
    return t;
  }
  const { data, error } = await supabase
    .from('todos')
    .insert({ user_id: userId, title })
    .select('id, title, completed, created_at')
    .single();
  if (error) throw error;
  return data;
}

export async function updateTodo(id, patch) {
  if (!supabaseConnected) {
    const items = readLocal().map(t => t.id === id ? { ...t, ...patch } : t);
    writeLocal(items);
    return items.find(t => t.id === id);
  }
  const { data, error } = await supabase
    .from('todos')
    .update(patch)
    .eq('id', id)
    .select('id, title, completed, created_at')
    .single();
  if (error) throw error;
  return data;
}

export async function deleteTodo(id) {
  if (!supabaseConnected) {
    writeLocal(readLocal().filter(t => t.id !== id));
    return;
  }
  const { error } = await supabase.from('todos').delete().eq('id', id);
  if (error) throw error;
}

export function subscribeTodos(userId, onChange) {
  if (!supabaseConnected) return () => {};
  const channel = supabase
    .channel('todos')
    .on('postgres_changes',
        { event: '*', schema: 'public', table: 'todos', filter: `user_id=eq.${userId}` },
        payload => onChange(payload))
    .subscribe();
  return () => supabase.removeChannel(channel);
}
