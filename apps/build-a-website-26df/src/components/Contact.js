export function contact() {
  return {
    name: '',
    email: '',
    company: '',
    message: '',
    sent: false,
    submit() {
      const payload = { name: this.name, email: this.email, company: this.company, message: this.message, at: new Date().toISOString() };
      const log = JSON.parse(localStorage.getItem('lumen.inquiries') || '[]');
      log.push(payload);
      localStorage.setItem('lumen.inquiries', JSON.stringify(log));
      this.sent = true;
      this.name = this.email = this.company = this.message = '';
    },
  };
}
