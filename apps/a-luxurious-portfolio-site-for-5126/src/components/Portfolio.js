export function portfolio() {
  return {
    name: 'Jacint Alama',
    initials: 'JA',
    theme: 'dark',
    filter: 'All',
    contact: { name: '', email: '', message: '', sending: false },
    toast: { visible: false, message: '' },
    projects: [
      { title: 'Swiss E-commerce Platform', summary: 'Built a production Next.js e-commerce storefront for a Swiss client, integrating Claude Code-driven workflows and LLM features end-to-end.', year: '2025', category: 'Web', seed: 'swiss-ecom', tags: ['Next.js', 'TypeScript', 'Claude Code'] },
      { title: 'Open WebUI Deployment', summary: 'Delivered a US-based Open WebUI deployment with custom LLM integrations and automation pipelines for an AI-first team.', year: '2025', category: 'Backend', seed: 'open-webui', tags: ['Open WebUI', 'LLM', 'Node.js'] },
      { title: 'Puppeteer Automation Suite', summary: 'Designed a browser-automation system that handles scraping, form submission, and scheduled workflows — cutting manual effort and improving data reliability.', year: '2025', category: 'Infra', seed: 'puppeteer', tags: ['Puppeteer', 'Node.js', 'Automation'] },
      { title: 'Online Job Application (Capstone)', summary: 'Led a team building a dual-role job platform with a weighted matching algorithm that scores candidate-to-role fit by skills, experience, and qualifications.', year: '2024', category: 'Web', seed: 'jobapp', tags: ['React', 'Node.js', 'Relational DB'] },
      { title: 'GSCWD Hydraulic Analysis', summary: 'Built an EPANET.js-style tool that reads .INP files and visualizes real-time GIS data for water-distribution engineers.', year: '2024', category: 'Web', seed: 'gscwd', tags: ['JavaScript', 'GIS', 'EPANET'] },
      { title: 'Print & Brand System', summary: 'Production layouts and vector identity work for Starbright Printing Press — calendars, business cards, company IDs, and BIR ATP documentation.', year: '2024', category: 'Infra', seed: 'starbright', tags: ['Illustrator', 'Photoshop', 'Vector'] }
    ],
    skills: {
      languages: ['TypeScript', 'JavaScript', 'Python'],
      systems: ['Next.js', 'React', 'Node.js', 'Puppeteer', 'Open WebUI', 'Claude Code', 'LLM Integration', 'Relational Databases'],
      craft: ['Full-stack development', 'AI automation', 'IT support & troubleshooting', 'Adobe Photoshop', 'Adobe Illustrator', 'Vector art']
    },
    posts: [
      { title: 'Shipping production features with Claude Code', date: 'Mar 2026', read: '6 min' },
      { title: 'Puppeteer in practice: reliable browser automation', date: 'Jan 2026', read: '8 min' },
      { title: 'From graphic design to full-stack: a non-linear path', date: 'Nov 2025', read: '5 min' }
    ],
    get filteredProjects() {
      if (this.filter === 'All') return this.projects;
      return this.projects.filter(p => p.category === this.filter);
    },
    init() {
      const stored = localStorage.getItem('portfolio-theme');
      if (stored) this.theme = stored;

      this.$nextTick(() => window.lucide && window.lucide.createIcons());
      this.$watch('filter', () => this.$nextTick(() => window.lucide && window.lucide.createIcons()));

      const ids = ['top', 'work', 'about', 'skills', 'writing', 'contact'];
      window.addEventListener('keydown', (e) => {
        if (e.target.matches('input, textarea')) return;
        if (e.key !== 'j' && e.key !== 'k') return;
        const y = window.scrollY + 80;
        const positions = ids.map(id => {
          const el = id === 'top' ? document.body : document.getElementById(id);
          return { id, top: el ? el.getBoundingClientRect().top + window.scrollY : 0 };
        });
        let idx = 0;
        for (let i = 0; i < positions.length; i++) {
          if (positions[i].top <= y) idx = i;
        }
        const next = e.key === 'j' ? Math.min(idx + 1, ids.length - 1) : Math.max(idx - 1, 0);
        const target = ids[next] === 'top' ? document.body : document.getElementById(ids[next]);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('portfolio-theme', this.theme);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },
    async submitContact() {
      this.contact.sending = true;
      await new Promise(r => setTimeout(r, 700));
      this.contact.sending = false;
      this.contact.name = '';
      this.contact.email = '';
      this.contact.message = '';
      this.toast = { visible: true, message: 'Message received. I\'ll reply within 24 hours.' };
      setTimeout(() => { this.toast.visible = false; }, 3500);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
