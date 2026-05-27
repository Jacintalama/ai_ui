// Auto-advancing image carousel with manual prev/next + dot indicators.
// Used by the real-estate template hero. Pauses interval on hover, resumes on leave.
export const carousel = (count, intervalMs = 5000) => ({
  i: 0,
  count,
  timer: null,
  init() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    this.start();
  },
  start() {
    if (this.timer) return;
    this.timer = setInterval(() => { this.i = (this.i + 1) % this.count; }, intervalMs);
  },
  stop() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  },
  go(idx) {
    this.i = idx;
    this.stop(); this.start(); // restart interval after manual nav
  },
  prev() { this.go((this.i - 1 + this.count) % this.count); },
  next() { this.go((this.i + 1) % this.count); },
});
