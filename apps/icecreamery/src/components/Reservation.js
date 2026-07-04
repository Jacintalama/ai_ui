export function reservation() {
  return {
    submitted: false,
    form: { name: '', email: '', date: '', time: '', guests: '', notes: '' },
    errors: {},

    validate() {
      this.errors = {};
      if (!this.form.name.trim()) this.errors.name = 'Please enter your name.';
      if (!this.form.email.trim() || !this.form.email.includes('@')) this.errors.email = 'Please enter a valid email.';
      if (!this.form.date) this.errors.date = 'Please choose a date.';
      if (!this.form.time) this.errors.time = 'Please choose a time.';
      const g = parseInt(this.form.guests, 10);
      if (!g || g < 1 || g > 12) this.errors.guests = 'Please enter between 1 and 12 guests.';
      return Object.keys(this.errors).length === 0;
    },

    submit() {
      if (!this.validate()) return;
      this.submitted = true;
    },
  };
}
