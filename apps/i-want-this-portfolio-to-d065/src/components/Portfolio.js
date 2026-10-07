export function portfolio() {
  return {
    name: 'Lukas Herajt',
    initials: 'LH',
    theme: 'dark',
    filter: 'All',
    contact: { name: '', email: '', message: '', sending: false },
    toast: { visible: false, message: '' },
    activeSection: 'hero',
    sectionIds: ['hero', 'work', 'about', 'writing', 'contact'],
    projects: [
      {
        title: 'Enterprise RAG and Semantic Search Platform',
        summary: 'End-to-end document retrieval system using embedding pipelines, OpenSearch, Pinecone, and FAISS with metadata filtering and hybrid retrieval. Enabled agents to retrieve grounded context before producing summaries and classifications, measurably reducing hallucinations across internal tools.',
        year: '2024–25', category: 'LLM', seed: 11,
        tags: ['Python', 'OpenSearch', 'Pinecone', 'FAISS', 'pgvector']
      },
      {
        title: 'Agentic Document Processing Automation',
        summary: 'LangChain agent logic using Anthropic and OpenAI function calling for extraction, classification, summarization, and structured JSON output. Added fallback policies, validation steps, and confidence checks for safe enterprise deployment.',
        year: '2023–25', category: 'Agents', seed: 12,
        tags: ['LangChain', 'Anthropic', 'OpenAI', 'MCP']
      },
      {
        title: 'LLM Evaluation and Token Optimization Framework',
        summary: 'Accuracy checks, sampling tests, trace logs, and cost dashboards to monitor model stability and operational overhead. Improved output consistency via structured prompts, retry/fallback routing, and context compression.',
        year: '2024', category: 'LLM', seed: 14,
        tags: ['Python', 'Evals', 'Observability']
      },
      {
        title: 'Multi-Model Routing Layer',
        summary: 'Latency- and cost-aware router across Claude Sonnet/Opus/Haiku and GPT-4 family. Deterministic fallbacks, circuit breakers, and per-tenant token budgets keep production traffic predictable under load.',
        year: '2025', category: 'ML Infra', seed: 15,
        tags: ['TypeScript', 'Anthropic', 'OpenAI', 'Redis']
      },
      {
        title: 'MCP Tooling for Internal Workflows',
        summary: 'Model Context Protocol servers exposing internal APIs, vector stores, and knowledge bases to Claude agents. Powers retrieval-grounded automations across the org with audit-logged tool calls.',
        year: '2025', category: 'Agents', seed: 16,
        tags: ['MCP', 'Anthropic', 'Node.js']
      },
      {
        title: 'REST API Modernization (MAD)',
        summary: 'Python backend modules supporting data transformation, analytics, and ML-assisted automation features. REST endpoints enabling model-driven logic in business-facing tools at Mid Atlantic Distribution.',
        year: '2022', category: 'ML Infra', seed: 13,
        tags: ['Python', 'FastAPI', 'Postgres']
      }
    ],
    skills: {
      ml: ['FAISS', 'Chroma', 'Pinecone', 'pgvector', 'OpenSearch', 'Hybrid retrieval', 'Metadata filtering', 'Chunking strategies', 'Embeddings'],
      llm: ['OpenAI API', 'Claude (Sonnet / Opus / Haiku)', 'LangChain', 'LlamaIndex', 'MCP', 'RAG', 'Function calling', 'Agentic workflows', 'Evals & guardrails'],
      infra: ['Python', 'TypeScript', 'JavaScript', 'Node.js', 'REST APIs', 'Async Python', 'Microservices', 'Azure (OpenAI, AI Search, Functions)', 'AWS (Lambda, S3)', 'PostgreSQL', 'MongoDB', 'Docker', 'CI/CD', 'GitHub Actions']
    },
    writing: [
      { title: 'Grounding LLMs with hybrid retrieval: OpenSearch + Pinecone in practice', date: 'Apr 2026', read: '8 min' },
      { title: 'Token cost optimization: caching, routing, and context compression', date: 'Feb 2026', read: '10 min' },
      { title: 'Building safe agentic document pipelines with fallback policies', date: 'Dec 2025', read: '9 min' },
      { title: 'Eval harnesses that catch regressions before prod', date: 'Sep 2025', read: '7 min' }
    ],
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

      window.addEventListener('keydown', (e) => {
        if (e.target && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
        if (e.key !== 'j' && e.key !== 'k') return;
        e.preventDefault();
        const idx = Math.max(0, this.sectionIds.indexOf(this.activeSection));
        const next = e.key === 'j'
          ? Math.min(idx + 1, this.sectionIds.length - 1)
          : Math.max(idx - 1, 0);
        const el = document.getElementById(this.sectionIds[next]);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      });

      if ('IntersectionObserver' in window) {
        const io = new IntersectionObserver((entries) => {
          entries.forEach(en => { if (en.isIntersecting) this.activeSection = en.target.id; });
        }, { rootMargin: '-40% 0px -55% 0px' });
        this.sectionIds.forEach(id => { const el = document.getElementById(id); if (el) io.observe(el); });
      }
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
      this.toast = { visible: true, message: 'Got it. I usually reply within a day.' };
      setTimeout(() => { this.toast.visible = false; }, 3500);
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    }
  };
}
