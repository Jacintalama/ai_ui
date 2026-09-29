export function contactForm() {
  return {
    name: '',
    email: '',
    message: '',
    sent: false,
    submit() {
      const submissions = JSON.parse(localStorage.getItem('test_water_messages') || '[]');
      submissions.push({ name: this.name, email: this.email, message: this.message, at: new Date().toISOString() });
      localStorage.setItem('test_water_messages', JSON.stringify(submissions));
      this.sent = true;
      this.name = this.email = this.message = '';
      setTimeout(() => { this.sent = false; }, 5000);
    },
  };
}
