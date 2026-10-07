export function site() {
  return {
    sent: false,
    form: { name: '', email: '', message: '' },
    services: [
      { icon: 'compass', title: 'Product strategy', body: 'Positioning, scope, and roadmap work for early-stage teams who need a thinking partner, not a deck factory.' },
      { icon: 'palette', title: 'Brand & UI design', body: 'Identity systems, marketing sites, and product UI built in Figma — handed off as living component libraries.' },
      { icon: 'code', title: 'Web engineering', body: 'TypeScript, React, Next.js, and Supabase. We write the kind of code you can read a year later without wincing.' },
      { icon: 'gauge', title: 'Performance & SEO', body: 'Audits, Core Web Vitals work, and structured-data tune-ups for marketing sites that need to actually rank.' },
    ],
    projects: [
      { title: 'Halcyon', year: '2026', body: 'A scheduling product for independent therapists. Designed and built end-to-end in 11 weeks; now serving 1,400 practitioners.', tags: ['Product design', 'Next.js', 'Supabase'], gradient: 'linear-gradient(135deg,#6366f1,#a855f7)' },
      { title: 'Fernway', year: '2025', body: 'Marketing site, dashboard, and design system for a Series A logistics startup. Rebuilt their billing UX from scratch.', tags: ['Design system', 'React', 'Stripe'], gradient: 'linear-gradient(135deg,#0ea5e9,#22d3ee)' },
      { title: 'Orcastra', year: '2025', body: 'An AI-assisted writing tool for non-fiction authors. We led product strategy and shipped the V1 editor and onboarding.', tags: ['Strategy', 'TypeScript', 'OpenAI'], gradient: 'linear-gradient(135deg,#f43f5e,#fb923c)' },
      { title: 'Pinebox', year: '2024', body: 'B2B portal for a wholesale lumber supplier. Replaced a 14-year-old internal tool. Sales cycle dropped from 9 days to 2.', tags: ['Web app', 'Postgres', 'Tailwind'], gradient: 'linear-gradient(135deg,#10b981,#84cc16)' },
    ],
    steps: [
      { title: 'Discovery week', body: 'A focused 5-day sprint: stakeholder interviews, competitive teardown, and a written scoping doc you keep regardless of what comes next.' },
      { title: 'Design in public', body: 'Weekly Figma walkthroughs. You see iterations as they happen — no "big reveal" theater, no surprises at the end.' },
      { title: 'Ship in chunks', body: 'We deploy from day one. Every Friday you get a working build at a real URL, not a screenshot in a PDF.' },
      { title: 'Hand off cleanly', body: 'Documentation, a recorded walkthrough, and 30 days of post-launch support are included on every engagement.' },
    ],
    team: [
      { name: 'Maya Okafor', role: 'Founder, Design', bio: 'Previously design lead at Stripe and Linear. Twelve years designing tools for technical users.', gradient: 'linear-gradient(135deg,#6366f1,#ec4899)' },
      { name: 'Theo Larsen', role: 'Engineering Lead', bio: 'Full-stack engineer with a decade across fintech and devtools. Writes the TypeScript types you wish you had.', gradient: 'linear-gradient(135deg,#0ea5e9,#10b981)' },
      { name: 'Priya Raman', role: 'Product Strategy', bio: 'Ex-PM at Notion and a YC alum. Specializes in helping founders scope V1 down to something actually shippable.', gradient: 'linear-gradient(135deg,#f59e0b,#f43f5e)' },
      { name: 'Jonas Weber', role: 'Senior Designer', bio: 'Identity, motion, and marketing. Background in editorial design — every project gets a real typographic point of view.', gradient: 'linear-gradient(135deg,#8b5cf6,#22d3ee)' },
    ],
    submit() {
      try {
        const log = JSON.parse(localStorage.getItem('northwind-leads') || '[]');
        log.push({ ...this.form, at: new Date().toISOString() });
        localStorage.setItem('northwind-leads', JSON.stringify(log));
      } catch (e) {}
      this.sent = true;
      this.form = { name: '', email: '', message: '' };
      setTimeout(() => { this.sent = false; }, 6000);
    },
  };
}
