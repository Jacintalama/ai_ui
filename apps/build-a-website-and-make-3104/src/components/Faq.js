export function faq() {
  return {
    open: 0,
    items: [
      { q: 'When does Lumen launch?', a: 'General availability is Spring 2026. Waitlist signups get invited in weekly waves starting February; founding-team accounts are already active.' },
      { q: 'Can I migrate from Notion or Linear?', a: 'Yes — the one-click importer handles page trees, tickets, comments, and internal links. Migrations typically finish in under an hour for teams of 50.' },
      { q: 'How does the GitHub integration work?', a: 'We install a read-only GitHub app that watches merged PRs. Nothing is written back to your repo. All processing happens inside your Lumen workspace, encrypted at rest.' },
      { q: 'Is there a self-hosted option?', a: 'Yes, for Enterprise customers. We ship a Docker Compose bundle plus a Kubernetes Helm chart; both include the full auto-release-notes pipeline.' },
      { q: 'What happens to my data if I cancel?', a: 'You can export the entire workspace as Markdown + JSON at any time, including on the free plan. We keep a 30-day soft-delete window and then permanently erase everything.' },
    ],
    toggle(i) { this.open = this.open === i ? -1 : i; }
  };
}
