// rAF-throttled parallax. Apply once per page; no manual cleanup needed
// since templates are static and the listener lives for page lifetime.
export const parallax = (el, factor = 0.4) => {
  if (!el) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let raf = null;
  const update = () => {
    el.style.transform = `translateY(${window.scrollY * factor}px)`;
    raf = null;
  };
  window.addEventListener("scroll", () => {
    if (raf) return;
    raf = requestAnimationFrame(update);
  }, { passive: true });
};
