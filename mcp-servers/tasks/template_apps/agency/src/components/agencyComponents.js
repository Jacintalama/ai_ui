import { countUp } from "./countUp.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("agency", () => ({
    mobileMenu: false,
    navSolid: false,
    init() {
      const onScroll = () => { this.navSolid = window.scrollY > 600; };
      window.addEventListener("scroll", onScroll, { passive: true });

      const dot = document.getElementById("cursor-dot");
      if (dot && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        let raf = null;
        let x = 0, y = 0;
        window.addEventListener("mousemove", (e) => {
          x = e.clientX; y = e.clientY;
          if (raf) return;
          raf = requestAnimationFrame(() => {
            dot.style.transform = `translate(${x}px, ${y}px)`;
            raf = null;
          });
        });
      }
    },
    submitContact() {
      this.$dispatch("toast", { msg: "Thanks — we'll be in touch within 24 hours.", kind: "success" });
    },
  }));

  Alpine.data("countUp", countUp);
});
