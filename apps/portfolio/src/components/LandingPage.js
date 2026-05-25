export function navBar() {
  return { open: false };
}

export function skillsSection() {
  return {
    skillGroups: [
      {
        title: 'Frontend',
        icon: '<i data-lucide="monitor" class="w-4 h-4"></i>',
        accent: 'amber',
        items: ['React', 'Next.js', 'Alpine.js', 'Tailwind CSS', 'TypeScript', 'HTML5', 'CSS3']
      },
      {
        title: 'Backend',
        icon: '<i data-lucide="server" class="w-4 h-4"></i>',
        accent: 'orange',
        items: ['Python', 'FastAPI', 'Node.js', 'Go', 'PostgreSQL', 'Redis', 'Docker', 'REST', 'GraphQL']
      },
      {
        title: 'Design',
        icon: '<i data-lucide="pen-tool" class="w-4 h-4"></i>',
        accent: 'rose',
        items: ['Figma', 'UI/UX', 'Design Systems', 'Accessibility', 'Responsive Design', 'Animation']
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
        imageClass: 'project-image-1',
        imageIcon: 'layers',
        github: 'https://github.com',
        demo: null
      },
      {
        title: 'DevMetrics Dashboard',
        type: 'Side Project',
        description: 'A self-hosted engineering metrics platform that pulls data from GitHub and Jira, computes DORA metrics, and surfaces them in a Grafana-powered dashboard.',
        tags: ['Python', 'Grafana', 'Prometheus', 'PostgreSQL'],
        imageClass: 'project-image-2',
        imageIcon: 'bar-chart-2',
        github: 'https://github.com',
        demo: 'https://example.com'
      },
      {
        title: 'MCP Server Framework',
        type: 'Open Source',
        description: 'A Python framework for building Model Context Protocol servers, with built-in tool discovery, schema validation, and typed handler registration.',
        tags: ['Python', 'Pydantic', 'asyncio', 'MCP'],
        imageClass: 'project-image-3',
        imageIcon: 'cpu',
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
      this.sent = true;
      this.name = '';
      this.email = '';
      this.message = '';
    }
  };
}
