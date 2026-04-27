export function portfolio() {
  return {
    name: 'Ralph Benitez',
    initials: 'RB',
    theme: 'light',
    filter: 'All',
    contact: { name: '', email: '', message: '', sending: false },
    toast: { visible: false, message: '' },
    projects: [
      { title: 'Northwind Banking', summary: 'A friendlier dashboard for personal banking.', year: '2025', category: 'Web', seed: 1, tags: ['Product design', 'Webflow'] },
      { title: 'Loftwork iOS', summary: 'Native app for a community of independent designers.', year: '2025', category: 'Mobile', seed: 2, tags: ['iOS', 'SwiftUI'] },
      { title: 'Mira Identity', summary: 'Visual identity and packaging for a sleep brand.', year: '2024', category: 'Branding', seed: 3, tags: ['Brand', 'Print'] },
      { title: 'Globex Admin', summary: 'Internal tooling overhaul for an ops team of 80.', year: '2024', category: 'Web', seed: 4, tags: ['Design system', 'React'] },
      { title: 'Parlour', summary: 'Reservation app for a small chain of cafés.', year: '2023', category: 'Mobile', seed: 5, tags: ['React Native', 'Stripe'] },
      { title: 'Kiln Studio', summary: 'Visual identity and site for a ceramics studio.', year: '2023', category: 'Branding', seed: 6, tags: ['Brand', 'Webflow'] }
    ],
    skills: {
      design: ['Product design', 'Brand identity', 'Figma', 'Design systems', 'Prototyping'],
      eng: ['HTML/CSS', 'JavaScript', 'TypeScript', 'React', 'Tailwind', 'SwiftUI'],
      tools: ['Figma', 'Linear', 'Notion', 'Cursor', 'Vercel', 'Supabase']
    },
    get filteredProjects() {
      if (this.filter === 'All') return this.projects;
      return this.projects.filter(p => p.category === this.filter);
    },
    init() {
      const stored = localStorage.getItem('portfolio-theme');
      if (stored) this.theme = stored;
      else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) this.theme = 'dark';

      // refresh icons after templates render
      this.$nextTick(() => window.lucide && window.lucide.createIcons());

      this.$watch('filter', () => this.$nextTick(() => window.lucide && window.lucide.createIcons()));
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('portfolio-theme', this.theme);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    async submitContact() {
      this.contact.sending = true;
      // Simulate network round-trip
      await new Promise(r => setTimeout(r, 700));
      this.contact.sending = false;
      this.contact.name = '';
      this.contact.email = '';
      this.contact.message = '';
      this.toast = { visible: true, message: 'Thanks! I’ll be in touch within 24 hours.' };
      setTimeout(() => { this.toast.visible = false; }, 3500);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
