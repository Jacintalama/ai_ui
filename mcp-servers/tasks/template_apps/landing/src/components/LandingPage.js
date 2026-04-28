export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Northwind', 'Acme Co.', 'Globex', 'Initech', 'Hooli'],
    features: [
      { icon: 'layout-dashboard', title: 'Unified workspace', description: 'Roadmap, sprints, docs, and reviews — one place, one source of truth.' },
      { icon: 'workflow', title: 'Automations that fit', description: 'Trigger handoffs, status changes, and reminders without writing scripts.' },
      { icon: 'gauge', title: 'Insights at a glance', description: 'Velocity, throughput, and risk surfaced before standup, not after.' },
      { icon: 'shield-check', title: 'Enterprise-grade security', description: 'SSO, SCIM, audit logs, and SOC 2 Type II — out of the box.' },
      { icon: 'plug', title: 'Plays with your stack', description: 'Native integrations with GitHub, Linear, Slack, Figma, and 40+ more.' },
      { icon: 'sparkles', title: 'AI that earns its keep', description: 'Summaries, prioritization, and standups drafted from real activity.' }
    ],
    steps: [
      { title: 'Sign up in 60 seconds', description: 'Create your workspace with email or Google. No setup call required.' },
      { title: 'Import what you have', description: 'Pull issues from GitHub, Linear, Jira, or a CSV. Mappings stay editable.' },
      { title: 'Invite your team and ship', description: 'Roles, permissions, and notifications come with sensible defaults.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Head of Product, Northwind', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'We replaced four tools and our weekly planning is finally calm. The team actually wants to use it.' },
      { name: 'Jordan Lee', role: 'Engineering Manager, Globex', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'Sprint reports used to take half a day. Now they’re just there. Velocity is up 22% since we switched.' },
      { name: 'Sara Chen', role: 'Founder, Loftwork', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'The AI summaries are the only standup notes I actually read. Worth it for that alone.' }
    ],
    plans: [
      {
        name: 'Free', price: '$0', cadence: '/forever', cta: 'Start free', featured: false,
        description: 'For individuals trying things out.',
        features: ['1 workspace', 'Up to 3 members', 'Unlimited tasks', 'Community support']
      },
      {
        name: 'Pro', price: '$12', cadence: '/user / month', cta: 'Start 14-day trial', featured: true,
        description: 'For growing teams that need more.',
        features: ['Unlimited members', 'Custom workflows', 'Advanced analytics', 'Priority support', 'GitHub & Slack integrations']
      },
      {
        name: 'Team', price: '$24', cadence: '/user / month', cta: 'Talk to sales', featured: false,
        description: 'For organizations with stricter needs.',
        features: ['SSO + SCIM', 'Audit logs', 'Custom retention', 'Dedicated CSM', 'SOC 2 reports']
      }
    ],
    faqs: [
      { q: 'Do I need a credit card to start?', a: 'No. The free plan and the 14-day Pro trial both work without a card on file. We will only ask once you choose to upgrade.' },
      { q: 'Can I import from another tool?', a: 'Yes. We support imports from Linear, Jira, GitHub Issues, Asana, Trello, and CSV. Mappings are previewed before anything is created.' },
      { q: 'How does pricing scale?', a: 'You only pay for active members. Guests and read-only viewers are always free. Annual plans get a 20% discount.' },
      { q: 'Is my data secure?', a: 'All data is encrypted in transit and at rest. We are SOC 2 Type II audited and offer a signed DPA on request.' },
      { q: 'Do you offer discounts for non-profits or students?', a: 'Yes — non-profits and verified educators get 50% off Pro. Students get the Pro plan free for two years.' },
      { q: 'What happens to my data if I cancel?', a: 'You can export everything to JSON or CSV at any time. After cancellation we keep an archive for 30 days, then permanently delete it.' }
    ],
    init() {
      // Re-create Lucide icons after Alpine has populated x-for items
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
