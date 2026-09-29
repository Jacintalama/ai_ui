export function landingPage() {
  return {
    mobileMenu: false,
    openFaq: 0,
    brands: ['Northwind', 'Acme Co.', 'Globex', 'Initech', 'Hooli', 'Vercept'],
    features: [
      { icon: 'message-square', title: 'Natural language control', description: 'Tell AIUI what you want — “draft a launch email”, “summarize this PDF”, “book a flight to Paris” — and it routes to the right tool, instantly.' },
      { icon: 'workflow', title: 'Multi-step agent runs', description: 'AIUI Bot chains tool calls, files, and APIs into a single run. Plan, execute, course-correct, and report back without babysitting.' },
      { icon: 'plug', title: '40+ native connectors', description: 'Gmail, Google Drive, Slack, Notion, Linear, GitHub, Stripe, HubSpot, and more — all one OAuth click away.' },
      { icon: 'shield-check', title: 'Private by default', description: 'Your data never trains a public model. SOC 2 Type II, end-to-end TLS, scoped tokens, and one-click memory wipe.' },
      { icon: 'gauge', title: 'Fast, cheap, or both', description: 'Routes simple turns to Haiku and hard turns to Opus automatically. Same wrapper, 70% lower spend.' },
      { icon: 'sparkles', title: 'Custom skills in minutes', description: 'Author a skill in a markdown file. AIUI loads it, scopes its permissions, and surfaces it to teammates on day one.' }
    ],
    steps: [
      { title: 'Connect what you use', description: 'Click to authorize Gmail, Drive, Slack, GitHub, or any of our 40+ connectors. Scopes are read-only by default.' },
      { title: 'Just ask AIUI', description: 'Type or speak. The bot picks the right tools, asks clarifying questions only when it matters, and shows its work.' },
      { title: 'Ship the result', description: 'Send the draft, file the ticket, post the summary. AIUI logs every action so you can audit or undo with one click.' }
    ],
    testimonials: [
      { name: 'Maya Patel', role: 'Head of Ops, Northwind', avatar: 'https://i.pravatar.cc/80?img=47', quote: 'AIUI Bot replaced four browser tabs and a Zapier mess. My inbox triage now takes seven minutes instead of an hour.' },
      { name: 'Jordan Lee', role: 'Staff Engineer, Globex', avatar: 'https://i.pravatar.cc/80?img=12', quote: 'I gave it our internal docs and a GitHub token. By Friday it was filing better bug reports than half the team.' },
      { name: 'Sara Chen', role: 'Founder, Loftwork', avatar: 'https://i.pravatar.cc/80?img=32', quote: 'The clarifying questions are the magic. Other bots guess and break things. AIUI asks once, then nails it.' }
    ],
    plans: [
      {
        name: 'Hobby', price: '$0', cadence: '/forever', cta: 'Start free', featured: false,
        description: 'For curious individuals and side projects.',
        features: ['300 messages / month', '3 connectors', 'Community Discord', 'Claude Haiku 4.5']
      },
      {
        name: 'Pro', price: '$20', cadence: '/user / month', cta: 'Start 14-day trial', featured: true,
        description: 'For builders who use AIUI all day.',
        features: ['Unlimited messages', 'All 40+ connectors', 'Opus 4.7 on demand', 'Custom skills', 'Memory across sessions']
      },
      {
        name: 'Team', price: '$45', cadence: '/user / month', cta: 'Talk to sales', featured: false,
        description: 'For teams that want governance.',
        features: ['SSO + SCIM', 'Audit logs', 'Shared skills library', 'Private model routing', 'SOC 2 reports + DPA']
      }
    ],
    faqs: [
      { q: 'Which model does AIUI Bot use?', a: 'AIUI routes between Claude Haiku 4.5, Sonnet 4.6, and Opus 4.7 automatically based on task difficulty. Pro and Team users can pin a specific model per skill if they prefer.' },
      { q: 'Does AIUI train on my data?', a: 'No. Your prompts, files, and connector data are never used to train any model — ours or our providers’. Memory is per-workspace and you can wipe it any time from settings.' },
      { q: 'How do connectors work?', a: 'Each connector is a scoped OAuth integration. You approve a specific set of permissions, AIUI stores a short-lived token, and you can revoke it from your dashboard or directly from Google/Slack/etc.' },
      { q: 'Can I write my own skills?', a: 'Yes. Skills are markdown files with a short YAML header. Drop one in your workspace and AIUI loads it on the next turn. The full SDK and examples are on our docs site.' },
      { q: 'Is there an API?', a: 'Yes — Pro and Team plans include a REST + websocket API so you can embed AIUI inside your own product, CLI, or CI pipeline. Rate limits scale with seat count.' },
      { q: 'What happens if AIUI gets something wrong?', a: 'Every tool call is logged with inputs, outputs, and a one-click revert. Destructive actions (send, delete, charge) always confirm before executing on Hobby and Pro, and require approval policies on Team.' },
      { q: 'Do you offer self-hosting?', a: 'Team plans on annual contracts can self-host the orchestrator inside your VPC while continuing to call Claude’s hosted API. Talk to sales for the deployment guide.' }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
