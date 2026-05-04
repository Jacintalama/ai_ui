export function navBar() {
  return { open: false };
}

export function skillsSection() {
  return {
    skillGroups: [
      {
        title: 'Languages',
        icon: '<i data-lucide="code-2" class="w-4 h-4"></i>',
        accent: 'indigo',
        items: ['Python', 'TypeScript', 'JavaScript', 'Go', 'SQL', 'Bash']
      },
      {
        title: 'Backend & APIs',
        icon: '<i data-lucide="server" class="w-4 h-4"></i>',
        accent: 'violet',
        items: ['FastAPI', 'Node.js', 'REST', 'GraphQL', 'gRPC', 'PostgreSQL', 'Redis']
      },
      {
        title: 'Frontend',
        icon: '<i data-lucide="monitor" class="w-4 h-4"></i>',
        accent: 'sky',
        items: ['React', 'Next.js', 'Alpine.js', 'Tailwind CSS', 'HTML5', 'CSS3']
      },
      {
        title: 'Cloud & Infrastructure',
        icon: '<i data-lucide="cloud" class="w-4 h-4"></i>',
        accent: 'teal',
        items: ['Docker', 'Kubernetes', 'AWS', 'GCP', 'Terraform', 'CI/CD']
      },
      {
        title: 'Tools & Practices',
        icon: '<i data-lucide="git-branch" class="w-4 h-4"></i>',
        accent: 'amber',
        items: ['Git', 'GitHub Actions', 'Linux', 'Agile/Scrum', 'TDD', 'Code Review']
      },
      {
        title: 'Data & ML',
        icon: '<i data-lucide="bar-chart-2" class="w-4 h-4"></i>',
        accent: 'rose',
        items: ['Pandas', 'NumPy', 'Scikit-learn', 'Grafana', 'Prometheus', 'Loki']
      }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}

export function projectsSection() {
  return {
    projects: [
      {
        title: 'Distributed Task Orchestrator',
        type: 'Open Source',
        description: 'A lightweight, fault-tolerant task queue built in Go with pluggable backends (Redis, PostgreSQL). Supports priority queues, dead-letter handling, and a real-time web dashboard.',
        tags: ['Go', 'Redis', 'PostgreSQL', 'Docker'],
        github: 'https://github.com',
        demo: null
      },
      {
        title: 'API Gateway — IO Platform',
        type: 'Professional',
        description: 'Designed and built a reverse-proxy API gateway routing traffic from Cloudflare through Caddy to backend microservices, with JWT auth, rate limiting, and structured logging.',
        tags: ['Python', 'FastAPI', 'Caddy', 'Docker Compose'],
        github: null,
        demo: null
      },
      {
        title: 'DevMetrics Dashboard',
        type: 'Side Project',
        description: 'A self-hosted engineering metrics platform that pulls data from GitHub and Jira, computes DORA metrics, and surfaces them in a Grafana-powered dashboard.',
        tags: ['Python', 'Grafana', 'Prometheus', 'PostgreSQL'],
        github: 'https://github.com',
        demo: 'https://example.com'
      },
      {
        title: 'MCP Server Framework',
        type: 'Open Source',
        description: 'A Python framework for building Model Context Protocol servers, with built-in tool discovery, schema validation, and typed handler registration.',
        tags: ['Python', 'Pydantic', 'asyncio', 'MCP'],
        github: 'https://github.com',
        demo: null
      },
      {
        title: 'Real-time Collaboration API',
        type: 'Professional',
        description: 'Event-driven WebSocket backend powering live document co-editing for a SaaS product with 10k+ daily active users. Handles presence, conflict resolution, and message replay.',
        tags: ['Node.js', 'WebSocket', 'Redis Pub/Sub', 'AWS'],
        github: null,
        demo: null
      },
      {
        title: 'Portfolio Site',
        type: 'Personal',
        description: 'This site! A fully static personal portfolio built with semantic HTML5, Tailwind CSS, and Alpine.js. No build step, no bundler — just clean, fast, accessible HTML.',
        tags: ['HTML5', 'Tailwind CSS', 'Alpine.js', 'Vanilla JS'],
        github: 'https://github.com',
        demo: null
      }
    ],
    init() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}

export function contactForm() {
  return {
    name: '',
    email: '',
    message: '',
    sent: false,
    errors: {},
    validate() {
      this.errors = {};
      if (!this.name.trim()) this.errors.name = 'Name is required.';
      if (!this.email.trim()) this.errors.email = 'Email is required.';
      else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.email)) this.errors.email = 'Please enter a valid email.';
      if (!this.message.trim()) this.errors.message = 'Message is required.';
      return Object.keys(this.errors).length === 0;
    },
    submit() {
      if (!this.validate()) return;
      // Static site: simulate submission
      this.sent = true;
      this.name = '';
      this.email = '';
      this.message = '';
    }
  };
}
