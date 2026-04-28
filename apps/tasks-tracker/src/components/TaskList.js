export function escapeHTML(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

export function taskItemHTML(t, today) {
  const overdue = t.due_date && t.due_date < today && !t.done;
  const dueBadge = t.due_date
    ? `<span class="due-badge${overdue ? ' overdue' : ''}">${t.due_date}</span>`
    : '';
  const desc = t.description
    ? `<div class="task-desc">${escapeHTML(t.description)}</div>`
    : '';
  return `<div class="task-item${t.done ? ' task-done' : ''}" data-id="${t.id}">
    <input type="checkbox"${t.done ? ' checked' : ''} data-action="toggle" />
    <div class="task-body">
      <div class="task-title">${escapeHTML(t.title)}</div>
      ${desc}
      ${dueBadge}
    </div>
    <div class="task-actions">
      <button class="btn-ghost" data-action="edit" title="Edit">&#9998;</button>
      <button class="btn-danger" data-action="delete" title="Delete">&#x2715;</button>
    </div>
  </div>`;
}

export function renderTasks(tasks, { loading, openSection, doneSection, openList, doneList }) {
  loading.style.display = 'none';
  const today = new Date().toISOString().slice(0, 10);
  const open = tasks.filter(t => !t.done);
  const done = tasks.filter(t => t.done);

  openSection.style.display = 'block';
  openList.innerHTML = open.length
    ? open.map(t => taskItemHTML(t, today)).join('')
    : '<p class="empty-state">No tasks yet</p>';

  if (done.length) {
    doneSection.style.display = 'block';
    doneList.innerHTML = done.map(t => taskItemHTML(t, today)).join('');
  } else {
    doneSection.style.display = 'none';
    doneList.innerHTML = '';
  }
}
