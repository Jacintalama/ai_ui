export function contactForm() {
  return {
    name: '',
    email: '',
    subject: '',
    message: '',
    sent: false,
    submit() {
      if (!this.name || !this.email || !this.message) return;
      this.sent = true;
      this.name = '';
      this.email = '';
      this.subject = '';
      this.message = '';
    },
  };
}
