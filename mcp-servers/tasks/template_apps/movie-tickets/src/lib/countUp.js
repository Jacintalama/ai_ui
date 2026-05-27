// src/lib/countUp.js — small rAF tween, honors reduced motion.
// Usage: createCountUp().to(targetValue, callback)
export function createCountUp(durationMs = 400) {
  return {
    _raf: null,
    to(target, set) {
      if (this._raf) cancelAnimationFrame(this._raf);
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reduced) { set(target); return; }
      const start = parseFloat(set.last ?? 0);
      const t0 = performance.now();
      const tick = (now) => {
        const k = Math.min(1, (now - t0) / durationMs);
        const eased = 1 - Math.pow(1 - k, 3);
        const v = Math.round((start + (target - start) * eased) * 100) / 100;
        set(v); set.last = v;
        if (k < 1) this._raf = requestAnimationFrame(tick);
      };
      this._raf = requestAnimationFrame(tick);
    },
  };
}
