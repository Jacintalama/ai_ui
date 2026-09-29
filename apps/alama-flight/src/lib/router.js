// View router with history-stack-based back navigation.
// Used by every template's main.js via ...createRouter({ initial, views }).
export function createRouter({ initial, views }) {
  return {
    view: initial,
    history: [initial],

    setView(name) {
      if (!views.includes(name)) return;
      if (this.view !== name) {
        this.history.push(name);
        this.view = name;
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          window.scrollTo(0, 0);
        }
      }
    },

    back() {
      if (this.history.length <= 1) return;
      this.history.pop();
      this.view = this.history[this.history.length - 1];
      window.scrollTo(0, 0);
    },
  };
}
