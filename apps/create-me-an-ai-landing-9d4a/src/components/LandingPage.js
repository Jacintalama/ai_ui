export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Northwind', 'Acme Co.', 'Globex', 'Initech', 'Hooli', 'Vantage'],
    features: [
      { icon: 'brain-circuit', title: 'Frontier reasoning', description: 'A multi-step reasoning engine that plans, drafts, and self-reviews before it answers — not a one-shot autocomplete.' },
      { icon: 'database', title: 'Grounded in your data', description: 'Connect Notion, Drive, Slack, and your warehouse. Lumen answers from your context, with citations on every claim.' },
      { icon: 'workflow', title: 'Agents that take action', description: 'Move beyond chat. Spin up agents that draft PRs, triage tickets, refresh dashboards, and email the result.' },
      { icon: 'shield-check', title: 'Private by default', description: 'SOC 2 Type II, end-to-end encryption, customer-managed keys, and zero training on your data. Period.' },
      { icon: 'gauge', title: 'Sub-second latency', description: 'Streamed responses begin in under 300ms on a fine-tuned inference stack — even for 200-page documents.' },
      { icon: 'plug', title: '40+ native integrations', description: 'GitHub, Linear, Salesforce, HubSpot, Snowflake, Zendesk, and more. OAuth in two clicks, no IT ticket required.' }
    ],
    steps: [
      { title: 'Connect your sources', description: 'Pick the apps your team already lives in. Lumen indexes incrementally — no migration weekend, no data leaves your tenant.' },
      { title: 'Train on your voice', description: 'Upload a handful of docs and we calibrate tone, glossary, and guardrails so Lumen sounds like your best teammate.' },
      { title: 'Deploy across the org', description: 'Ship via web, Slack, browser sidebar, or API. Role-based access and audit logs are on from day one.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Head of Product, Northwind', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'Lumen replaced four point tools and cut our weekly research time in half. The citations are what finally got legal on board.' },
      { name: 'Jordan Lee', role: 'Engineering Manager, Globex', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'The agent SDK is the cleanest I have used. We shipped an internal support bot in a weekend and it handles 60% of L1 tickets.' },
      { name: 'Sara Chen', role: 'Founder, Loftwork', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'Onboarding was three clicks. By Monday morning the whole team was drafting briefs with it — and the output sounded like us.' }
    ],
    plans: [
      {
        name: 'Starter', price: '$0', cadence: '/forever', cta: 'Start free', featured: false,
        description: 'For curious individuals and weekend builders.',
        features: ['500 messages / month', '2 connected sources', 'Standard models', 'Community Discord']
      },
      {
        name: 'Pro', price: '$24', cadence: '/user / month', cta: 'Start 14-day trial', featured: true,
        description: 'For teams putting AI into daily work.',
        features: ['Unlimited messages', 'Unlimited sources & agents', 'Frontier + reasoning models', 'Slack & browser extension', 'Priority email support']
      },
      {
        name: 'Enterprise', price: 'Custom', cadence: '/annual', cta: 'Talk to sales', featured: false,
        description: 'For regulated industries and large orgs.',
        features: ['SSO + SCIM provisioning', 'Customer-managed keys', 'Private VPC deployment', 'SOC 2 + HIPAA reports', 'Dedicated solutions engineer']
      }
    ],
    faqs: [
      { q: 'Which models power Lumen?', a: 'Lumen routes between frontier models from Anthropic, OpenAI, and our own fine-tunes based on the task — reasoning for analysis, fast models for chat, and code-specialized models for engineering. You can pin a specific model on Pro and above.' },
      { q: 'Do you train on my data?', a: 'Never. Your prompts, completions, and connected documents are isolated to your tenant and excluded from any training run. We sign DPAs and offer customer-managed keys on Enterprise.' },
      { q: 'How does Lumen avoid hallucinating?', a: 'Every grounded answer cites the source paragraphs it was built from. When confidence is low, Lumen asks a clarifying question instead of guessing. You can also enforce a citations-required mode org-wide.' },
      { q: 'Can I build my own agents?', a: 'Yes. The TypeScript and Python SDKs expose tool-calling, memory, and the same evaluation harness our team uses. Most customers ship their first internal agent within a week.' },
      { q: 'What about latency on long documents?', a: 'We pre-chunk and embed on ingest, then stream tokens as soon as the first relevant chunk is retrieved. P50 time-to-first-token sits under 300ms even on 200-page PDFs.' },
      { q: 'Is there an on-prem option?', a: 'Enterprise customers can deploy Lumen into a dedicated VPC in AWS, GCP, or Azure. Air-gapped deployments are available on request for government and defense customers.' },
      { q: 'How is pricing counted?', a: 'Per active user, per month. Read-only viewers and guests are free. Annual contracts include a 20% discount and unlock the higher-tier model pool.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
