import { getDb, configured } from './lib/supabase.js';
import { fetchTasks, insertTask, updateTask, deleteTask } from './lib/api.js';
import { renderTasks } from './components/TaskList.js';
import { initAuth } from './components/Auth.js';

const errorBanner = document.getElementById('error-banner');
const authSection = document.getElementById('auth-section');
const appSection = document.getElementById('app-section');
const loading = document.getElementById('loading');
const openSection = document.getElementById('open-section');
const doneSection = document.getElementById('done-section');
const openList = document.getElementById('open-tasks');
const doneList = document.getElementById('done-tasks');
const addForm = document.getElementById('add-form');
const newTitle = document.getElementById('new-title');
const newDesc = document.getElementById('new-desc');
const newDue = document.getElementById('new-due');
const titleError = document.getElementById('title-error');
const editOverlay = document.getElementById('edit-overlay');
const editTitle = document.getElementById('edit-title');
const editDesc = document.getElementById('edit-desc');
const editDue = document.getElementById('edit-due');

function showError(msg) {
  errorBanner.textContent = msg;
  errorBanner.style.display = 'block';
}

let tasks = [];
let editingId = null;

const listRefs = { loading, openSection, doneSection, openList, doneList };

async function loadTasks() {
  if (!getDb()) return;
  const { data, error } = await fetchTasks();
  if (error) { showError('Failed to load tasks: ' + error.message); return; }
  tasks = data || [];
  renderTasks(tasks, listRefs);
}

function getTaskId(el) {
  return el.closest('.task-item')?.dataset.id;
}

document.addEventListener('change', async (e) => {
  if (e.target.dataset.action !== 'toggle') return;
  const id = getTaskId(e.target);
  if (!id) return;
  const { error } = await updateTask(id, { done: e.target.checked });
  if (error) showError('Update failed: ' + error.message);
  else await loadTasks();
});

document.addEventListener('click', async (e) => {
  const action = e.target.dataset.action;
  if (!action) return;
  const id = getTaskId(e.target);
  if (!id) return;

  if (action === 'delete') {
    const { error } = await deleteTask(id);
    if (error) showError('Delete failed: ' + error.message);
    else await loadTasks();
  }

  if (action === 'edit') {
    const task = tasks.find(t => t.id === id);
    if (!task) return;
    editingId = id;
    editTitle.value = task.title;
    editDesc.value = task.description || '';
    editDue.value = task.due_date || '';
    editOverlay.classList.add('open');
    editTitle.focus();
  }
});

addForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const title = newTitle.value.trim();
  if (!title) { titleError.style.display = 'block'; newTitle.focus(); return; }
  titleError.style.display = 'none';

  const { error } = await insertTask({
    title,
    description: newDesc.value.trim() || null,
    due_date: newDue.value || null,
    done: false,
  });
  if (error) { showError('Insert failed: ' + error.message); return; }

  newTitle.value = '';
  newDesc.value = '';
  newDue.value = '';
  await loadTasks();
  newTitle.focus();
});

newTitle.addEventListener('input', () => {
  if (newTitle.value.trim()) titleError.style.display = 'none';
});

document.getElementById('edit-cancel').addEventListener('click', () => {
  editOverlay.classList.remove('open');
  editingId = null;
});

editOverlay.addEventListener('click', (e) => {
  if (e.target === editOverlay) { editOverlay.classList.remove('open'); editingId = null; }
});

document.getElementById('edit-save').addEventListener('click', async () => {
  const title = editTitle.value.trim();
  if (!title || !editingId) return;

  const { error } = await updateTask(editingId, {
    title,
    description: editDesc.value.trim() || null,
    due_date: editDue.value || null,
  });
  if (error) { showError('Update failed: ' + error.message); return; }

  editOverlay.classList.remove('open');
  editingId = null;
  await loadTasks();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && editOverlay.classList.contains('open')) {
    editOverlay.classList.remove('open');
    editingId = null;
  }
});

initAuth({ getDb, configured, authSection, appSection, onSignedIn: loadTasks });
