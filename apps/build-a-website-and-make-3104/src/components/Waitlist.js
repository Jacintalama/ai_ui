export function waitlist() {
  return {
    email: '',
    submit() {
      if (!this.email) return;
      const store = window.Alpine.store('waitlist');
      const list = JSON.parse(localStorage.getItem('lumen-waitlist') || '[]');
      if (!list.includes(this.email)) list.push(this.email);
      localStorage.setItem('lumen-waitlist', JSON.stringify(list));
      store.count = list.length;
      store.message = `You're in — spot #${list.length}. Watch ${this.email} for your invite.`;
      this.email = '';
    }
  };
}
