import { getDb } from './supabase.js';

export async function fetchTasks() {
  return getDb().from('tasks').select('*').order('done', { ascending: true }).order('created_at', { ascending: true });
}

export async function insertTask(row) {
  return getDb().from('tasks').insert([row]);
}

export async function updateTask(id, patch) {
  return getDb().from('tasks').update(patch).eq('id', id);
}

export async function deleteTask(id) {
  return getDb().from('tasks').delete().eq('id', id);
}
