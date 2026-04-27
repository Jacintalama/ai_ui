import { listTodos, createTodo, updateTodo, deleteTodo, subscribeTodos } from '../lib/api.js';

export function todoApp() {
  return {
    todos: [],
    newTitle: '',
    filter: 'All',
    loading: false,
    _unsub: null,
    async init() {
      const userId = this.$root.session?.user?.id || 'local';
      try {
        this.todos = await listTodos(userId);
      } catch (e) {
        console.error('Load todos failed', e);
      }
      this._unsub = subscribeTodos(userId, () => this.refresh());
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    destroy() { if (this._unsub) this._unsub(); },
    async refresh() {
      const userId = this.$root.session?.user?.id || 'local';
      this.todos = await listTodos(userId);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    get filteredTodos() {
      if (this.filter === 'Active') return this.todos.filter(t => !t.completed);
      if (this.filter === 'Completed') return this.todos.filter(t => t.completed);
      return this.todos;
    },
    get remaining() { return this.todos.filter(t => !t.completed).length; },
    get anyCompleted() { return this.todos.some(t => t.completed); },
    async addTodo() {
      const title = this.newTitle.trim();
      if (!title) return;
      const userId = this.$root.session?.user?.id || 'local';
      try {
        const created = await createTodo(userId, title);
        // optimistic prepend if not already there
        if (!this.todos.find(t => t.id === created.id)) this.todos.unshift(created);
        this.newTitle = '';
        this.$nextTick(() => window.lucide && window.lucide.createIcons());
      } catch (e) {
        alert('Could not add todo: ' + (e?.message || e));
      }
    },
    async toggle(t) {
      try {
        const updated = await updateTodo(t.id, { completed: !t.completed });
        Object.assign(t, updated);
      } catch (e) { alert('Update failed: ' + (e?.message || e)); }
    },
    async remove(t) {
      try {
        await deleteTodo(t.id);
        this.todos = this.todos.filter(x => x.id !== t.id);
      } catch (e) { alert('Delete failed: ' + (e?.message || e)); }
    },
    async clearCompleted() {
      const done = this.todos.filter(t => t.completed);
      for (const t of done) await deleteTodo(t.id);
      this.todos = this.todos.filter(t => !t.completed);
    }
  };
}
