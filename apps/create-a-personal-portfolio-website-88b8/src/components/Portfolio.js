export function portfolio() {
  return {
    active: 0,
    skills: [
      'TypeScript', 'Python', 'Go', 'Rust',
      'PostgreSQL', 'Redis', 'Kafka', 'Kubernetes',
      'AWS', 'Terraform', 'React', 'gRPC',
    ],
    jobs: [
      {
        company: 'Northwind Data',
        role: 'Senior Software Engineer',
        period: 'Mar 2023 — Present',
        bullets: [
          'Lead engineer on the ingestion platform processing 4B+ events/day across 30 tenants.',
          'Cut p99 query latency by 62% by redesigning the sharding strategy and adding tiered caching.',
          'Mentor a team of four engineers; own the on-call rotation and incident review process.',
        ],
      },
      {
        company: 'Ember Labs',
        role: 'Software Engineer',
        period: 'Jun 2020 — Feb 2023',
        bullets: [
          'Built the billing and metering system that powers usage-based pricing for the entire platform.',
          'Migrated the monolith to a small set of well-defined services without a single customer-visible outage.',
          'Introduced automated integration testing that reduced regression bugs shipped to prod by ~40%.',
        ],
      },
      {
        company: 'Lattice.io',
        role: 'Backend Engineer',
        period: 'Aug 2018 — May 2020',
        bullets: [
          'Owned the public REST + GraphQL APIs consumed by hundreds of enterprise customers.',
          'Designed and rolled out a fine-grained authorization model backed by a Zanzibar-style store.',
          'Wrote the first version of the internal SDK generator, now used across seven client languages.',
        ],
      },
      {
        company: 'Freelance',
        role: 'Full-stack Developer',
        period: '2017 — 2018',
        bullets: [
          'Delivered production web apps for small businesses in logistics, hospitality, and legal tech.',
          'Handled everything from initial scoping and design to deployment and ongoing maintenance.',
        ],
      },
    ],
    projects: [
      {
        icon: 'FL',
        title: 'Flotilla',
        description: 'A lightweight orchestration library for background jobs in Python, with first-class support for priorities, retries, and dead-letter queues. Used in production by a handful of small teams.',
        tags: ['Python', 'Redis', 'asyncio', 'OpenTelemetry'],
        link: 'https://github.com/jacintalama/flotilla',
      },
      {
        icon: 'PQ',
        title: 'pgquilt',
        description: 'A CLI that stitches together zero-downtime PostgreSQL migrations from a friendly declarative spec. Handles the awkward multi-step dance for adding NOT NULL columns and renaming tables.',
        tags: ['Go', 'PostgreSQL', 'CLI'],
        link: 'https://github.com/jacintalama/pgquilt',
      },
      {
        icon: 'RV',
        title: 'Riverwatch',
        description: 'A tiny self-hosted uptime and TLS-expiry monitor with a single-binary install and a clean web dashboard. Built because every existing tool wanted a database and a message broker.',
        tags: ['Rust', 'SQLite', 'HTMX'],
        link: 'https://github.com/jacintalama/riverwatch',
      },
      {
        icon: 'CB',
        title: 'Codebrief',
        description: 'A weekend project turned genuinely useful tool: generates smart daily summaries of activity across a set of GitHub repos, tuned for engineering managers who miss the forest for the PRs.',
        tags: ['TypeScript', 'Next.js', 'OpenAI'],
        link: 'https://github.com/jacintalama/codebrief',
      },
    ],
  };
}
