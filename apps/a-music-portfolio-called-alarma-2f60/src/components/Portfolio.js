export function portfolio() {
  return {
    name: 'Alarma',
    initials: 'AL',
    theme: 'dark',
    filter: 'All',
    contact: { name: '', email: '', message: '', sending: false },
    toast: { visible: false, message: '' },
    projects: [
      { title: 'Siren Hours', summary: 'A late-night EP of warm analog synths and slow-burn rhythms, recorded in a converted boiler room over three winter weekends.', year: '2025', category: 'EP', seed: 'siren', tags: ['Synthwave', 'Ambient', 'Self-released'] },
      { title: 'Bell Tower (Single)', summary: 'Lead single from the forthcoming LP — chopped vocal loops, granular pads, and a drum kit built entirely from kitchenware.', year: '2025', category: 'Single', seed: 'belltower', tags: ['Electronic', 'Sample-based'] },
      { title: 'Score: "Midnight Garage"', summary: 'Original score for a short film about an all-night mechanic. Strings, tape hiss, and a single distorted guitar carry the whole runtime.', year: '2024', category: 'Score', seed: 'garage', tags: ['Film score', 'Cinematic'] },
      { title: 'Low Frequency Club Vol. 1', summary: 'Bi-monthly DJ mix series featuring deep house, downtempo, and the occasional left-field cover. Recorded live, mistakes left in.', year: '2024', category: 'Mix', seed: 'lfc', tags: ['DJ mix', 'House', 'Downtempo'] },
      { title: 'Vapor / Glass (Remix)', summary: 'Reworked an indie ballad into a six-minute breakbeat hybrid — released through a Berlin micro-label on limited 12".', year: '2024', category: 'Single', seed: 'vapor', tags: ['Remix', 'Breakbeat', 'Vinyl'] },
      { title: 'Quiet Rooms', summary: 'Debut full-length: nine pieces written for empty buildings. Field recordings from Lisbon, Porto, and a cathedral outside Évora.', year: '2023', category: 'EP', seed: 'quiet', tags: ['Ambient', 'Field recording', 'LP'] }
    ],
    skills: {
      design: ['Songwriting', 'Composition', 'Arrangement', 'Sound design', 'Mixing', 'Mastering'],
      eng: ['Ableton Live', 'Logic Pro', 'Pro Tools', 'Reaper', 'Max/MSP', 'Eurorack modular'],
      tools: ['Moog Sub 37', 'Juno-60', 'Rhodes Mk II', 'SP-404', 'Neumann TLM-103', 'UAD Apollo']
    },
    get filteredProjects() {
      if (this.filter === 'All') return this.projects;
      return this.projects.filter(p => p.category === this.filter);
    },
    init() {
      const stored = localStorage.getItem('portfolio-theme');
      if (stored) this.theme = stored;
      else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) this.theme = 'dark';

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
      await new Promise(r => setTimeout(r, 700));
      this.contact.sending = false;
      this.contact.name = '';
      this.contact.email = '';
      this.contact.message = '';
      this.toast = { visible: true, message: 'Thanks! I’ll be in touch within 48 hours.' };
      setTimeout(() => { this.toast.visible = false; }, 3500);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
