export function contactForm() {
  return {
    submitted: false,
    form: { name: '', email: '', subject: '', message: '' },
    errors: {},

    validate() {
      this.errors = {};
      if (!this.form.name.trim()) this.errors.name = 'Please enter your name.';
      if (!this.form.email.trim() || !this.form.email.includes('@')) this.errors.email = 'Please enter a valid email.';
      if (!this.form.message.trim()) this.errors.message = 'Please enter a message.';
      return Object.keys(this.errors).length === 0;
    },

    submit() {
      if (!this.validate()) return;
      this.submitted = true;
    },
  };
}
