export function featureGrid() {
  return {
    features: [
      { icon: '📝', title: 'Living docs', color: 'bg-fuchsia-500/20 text-fuchsia-300',
        body: 'Every doc is versioned, linked to the code it describes, and re-checked whenever a related PR lands. No more silent staleness.' },
      { icon: '🗂️', title: 'Unified planning', color: 'bg-indigo-500/20 text-indigo-300',
        body: 'Roadmap, sprint board, and backlog live in one graph. Drag a card to the roadmap and the sprint updates itself.' },
      { icon: '🚀', title: 'Auto release notes', color: 'bg-emerald-500/20 text-emerald-300',
        body: 'When you merge, Lumen groups commits by feature, drafts a human-readable summary, and posts it to Slack for review.' },
      { icon: '💬', title: 'Threaded reviews', color: 'bg-amber-500/20 text-amber-300',
        body: 'Inline comments on any doc, with resolution states that survive edits. Reviewers see exactly what changed since last look.' },
      { icon: '📊', title: 'Ship metrics', color: 'bg-rose-500/20 text-rose-300',
        body: 'Cycle time, WIP, and PR aging surfaced automatically. No dashboards to configure — the numbers show up where you already work.' },
      { icon: '🔐', title: 'Private by default', color: 'bg-sky-500/20 text-sky-300',
        body: 'End-to-end encrypted workspace. SSO, SCIM, and audit logs on every plan — not gated behind a sales call.' },
    ],
  };
}
