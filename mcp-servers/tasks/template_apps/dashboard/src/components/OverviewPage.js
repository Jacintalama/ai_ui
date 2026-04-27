import { fetchEvents, summarize, dailySeries, topEvents } from '../lib/api.js';

export function overviewPage() {
  return {
    range: 30,
    loading: false,
    events: [],
    summary: null,
    sortKey: 'created_at',
    sortDir: -1,
    page: 1,
    pageSize: 25,
    _lineChart: null,
    _barChart: null,

    async init() {
      await this.reload();
      window.addEventListener('theme-change', () => this.renderCharts());
    },

    async reload() {
      this.loading = true;
      try {
        const userId = this.$root.session?.user?.id || 'local';
        this.events = await fetchEvents(userId, Number(this.range));
        this.summary = summarize(this.events, Number(this.range));
        this.page = 1;
        this.$nextTick(() => {
          this.renderCharts();
          window.lucide && window.lucide.createIcons();
        });
      } catch (e) {
        console.error(e);
        alert('Failed to load events: ' + (e?.message || e));
      } finally {
        this.loading = false;
      }
    },

    get kpis() {
      const s = this.summary;
      if (!s) return [];
      return [
        { label: 'Active users', value: s.activeUsers.value, trend: s.activeUsers.trend, spark: s.activeUsers.spark },
        { label: 'Sessions',     value: s.sessions.value,    trend: s.sessions.trend,    spark: s.sessions.spark },
        { label: 'Avg session',  value: s.avgSession.value,  trend: s.avgSession.trend,  spark: s.avgSession.spark },
        { label: 'Bounce rate',  value: s.bounce.value,      trend: s.bounce.trend,      spark: s.bounce.spark }
      ];
    },

    setSort(key) {
      if (this.sortKey === key) this.sortDir *= -1;
      else { this.sortKey = key; this.sortDir = -1; }
    },

    get sortedEvents() {
      const k = this.sortKey, d = this.sortDir;
      return [...this.events].sort((a, b) => {
        const av = a[k] ?? ''; const bv = b[k] ?? '';
        if (av < bv) return -1 * d;
        if (av > bv) return 1 * d;
        return 0;
      });
    },

    get totalPages() { return Math.max(1, Math.ceil(this.events.length / this.pageSize)); },
    get pageRows() {
      const start = (this.page - 1) * this.pageSize;
      return this.sortedEvents.slice(start, start + this.pageSize);
    },

    formatTime(ts) {
      const d = new Date(ts);
      return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },

    renderCharts() {
      const dark = this.$root.theme === 'dark';
      const grid = dark ? 'rgba(148,163,184,0.15)' : 'rgba(15,23,42,0.08)';
      const ticks = dark ? '#94a3b8' : '#64748b';

      // Line chart
      const series = dailySeries(this.events, Number(this.range));
      const lineEl = this.$refs.lineChart;
      if (lineEl) {
        if (this._lineChart) this._lineChart.destroy();
        this._lineChart = new Chart(lineEl, {
          type: 'line',
          data: {
            labels: series.labels,
            datasets: [{
              label: 'Sessions',
              data: series.counts,
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99,102,241,0.15)',
              fill: true,
              tension: 0.35,
              pointRadius: 0,
              borderWidth: 2
            }]
          },
          options: {
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { color: grid }, ticks: { color: ticks, maxTicksLimit: 8 } },
              y: { grid: { color: grid }, ticks: { color: ticks }, beginAtZero: true }
            }
          }
        });
      }

      // Bar chart
      const top = topEvents(this.events);
      const barEl = this.$refs.barChart;
      if (barEl) {
        if (this._barChart) this._barChart.destroy();
        this._barChart = new Chart(barEl, {
          type: 'bar',
          data: {
            labels: top.map(t => t.label),
            datasets: [{ data: top.map(t => t.value), backgroundColor: '#6366f1', borderRadius: 4 }]
          },
          options: {
            indexAxis: 'y',
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { color: grid }, ticks: { color: ticks }, beginAtZero: true },
              y: { grid: { display: false }, ticks: { color: ticks } }
            }
          }
        });
      }
    }
  };
}
