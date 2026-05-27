export const countUp = (target) => ({
  n: 0,
  target,
  done: false,
  start() {
    if (this.done) return;
    this.done = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      this.n = this.target;
      return;
    }
    const t0 = performance.now();
    const dur = 1500;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      this.n = Math.round(this.target * eased);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  },
});
