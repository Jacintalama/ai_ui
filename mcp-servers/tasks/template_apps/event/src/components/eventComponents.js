import { countUp } from "./countUp.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("event", () => ({
    mobileMenu: false,
    activeDay: 1,
    openFaq: null,
    activeSpeaker: null, // for hover-bio reveal: speaker card index whose bio is shown
    showBio(i) { this.activeSpeaker = i; },
    hideBio() { this.activeSpeaker = null; },
  }));

  Alpine.data("countdown", (targetIso) => ({
    target: new Date(targetIso).getTime(),
    now: Date.now(),
    timer: null,
    init() {
      if (this.now >= this.target) return; // already elapsed: don't start ticking
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        // Snapshot once; don't tick.
        return;
      }
      this.timer = setInterval(() => { this.now = Date.now(); }, 1000);
    },
    destroy() { if (this.timer) clearInterval(this.timer); },
    get elapsed() { return this.now >= this.target; },
    get days()    { return Math.floor(Math.max(0, this.target - this.now) / 86_400_000); },
    get hours()   { return Math.floor((Math.max(0, this.target - this.now) % 86_400_000) / 3_600_000); },
    get minutes() { return Math.floor((Math.max(0, this.target - this.now) % 3_600_000) / 60_000); },
    get seconds() { return Math.floor((Math.max(0, this.target - this.now) % 60_000) / 1_000); },
  }));

  Alpine.data("countUp", countUp);
});
