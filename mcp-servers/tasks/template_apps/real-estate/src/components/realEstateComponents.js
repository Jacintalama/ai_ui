import { countUp } from "./countUp.js";
import { lightbox } from "./lightbox.js";
import { carousel } from "./carousel.js";

document.addEventListener("alpine:init", () => {
  // Spread lightbox into realEstate so gallery click handlers can call show(N) directly.
  Alpine.data("realEstate", () => ({
    mobileMenu: false,
    ...lightbox(),
    submitViewing() {
      this.$dispatch("toast", {
        msg: "Viewing request received — the agent will confirm by email within 24 hours.",
        kind: "success",
      });
    },
  }));

  Alpine.data("carousel", carousel);
  Alpine.data("countUp", countUp);
});
