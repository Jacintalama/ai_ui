import { parallax } from "./parallax.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("restaurant", () => ({
    mobileMenu: false,
    activeMenu: "brunch",
    init() {
      // Parallax on the hero image. The element has id="hero-img".
      parallax(document.getElementById("hero-img"));
    },
    submitReservation() {
      this.$dispatch("toast", {
        msg: "Reservation request received — we'll confirm by email within 24 hours.",
        kind: "success",
      });
    },
  }));
});
