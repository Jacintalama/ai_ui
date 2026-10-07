const fmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export function money(n) {
  if (n == null || isNaN(n)) return fmt.format(0);
  return fmt.format(Number(n));
}

export function formatDate(d) {
  if (!d) return '';
  try {
    return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch { return d; }
}

export function statusClass(status) {
  switch (status) {
    case 'paid': return 'bg-emerald-100 text-emerald-700';
    case 'sent': return 'bg-sky-100 text-sky-700';
    case 'overdue': return 'bg-rose-100 text-rose-700';
    case 'draft':
    default: return 'bg-slate-100 text-slate-700';
  }
}
