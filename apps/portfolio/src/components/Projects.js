export function projects() {
  return {
    list: [
      {
        name: 'Ops Dashboard',
        description: 'Internal operations dashboard for a logistics startup — tracks shipment status, SLA breaches, and team workload in real time with role-based access control.',
        tags: ['React', 'FastAPI', 'PostgreSQL'],
        link: '#',
      },
      {
        name: 'dep-audit',
        description: 'CLI tool that scans a monorepo\'s dependency graph, flags outdated or vulnerable packages across services, and outputs a prioritised remediation report.',
        tags: ['Go', 'Docker', 'GitHub Actions'],
        link: '#',
      },
      {
        name: 'SupportBot',
        description: 'Customer support chatbot integration that routes incoming tickets through an LLM for triage, auto-drafts replies for common queries, and escalates edge cases to human agents.',
        tags: ['Python', 'FastAPI', 'n8n', 'PostgreSQL'],
        link: '#',
      },
      {
        name: 'Invoiceflow',
        description: 'Lightweight SaaS app for freelancers to create, send, and track invoices — with automated payment reminders and a simple revenue analytics view.',
        tags: ['TypeScript', 'Node.js', 'React', 'AWS'],
        link: '#',
      },
    ],
  };
}
