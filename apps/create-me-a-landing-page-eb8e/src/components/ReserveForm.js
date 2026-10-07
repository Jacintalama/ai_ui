export function reserveForm() {
  return {
    status: 'idle',
    tier: '',
    email: '',
    open(tier) {
      this.tier = tier;
      this.status = 'open';
      this.$nextTick(() => {
        const el = document.querySelector('#pricing input[type=email]');
        if (el) el.focus();
      });
    },
    submit() {
      if (!this.email) return;
      const reservations = JSON.parse(localStorage.getItem('legendary_reservations') || '[]');
      reservations.push({ tier: this.tier, email: this.email, at: new Date().toISOString() });
      localStorage.setItem('legendary_reservations', JSON.stringify(reservations));
      this.status = 'done';
    }
  };
}
