import "./components/realEstateComponents.js";

const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (!REDUCED && "IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-visible");
      if (e.target.matches(".count-up")) {
        const stack = e.target._x_dataStack;
        if (stack && stack[0] && typeof stack[0].start === "function") {
          stack[0].start();
        }
      }
      io.unobserve(e.target);
    }
  }, { threshold: 0.2 });
  document.querySelectorAll(".reveal, .count-up").forEach((el) => io.observe(el));
} else {
  document.querySelectorAll(".reveal").forEach((el) => el.classList.add("is-visible"));
  document.querySelectorAll(".count-up").forEach((el) => {
    const stack = el._x_dataStack;
    if (stack && stack[0] && typeof stack[0].start === "function") stack[0].start();
  });
}
