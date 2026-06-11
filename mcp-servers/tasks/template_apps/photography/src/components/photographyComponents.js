import { lightbox } from "./lightbox.js";

document.addEventListener("alpine:init", () => {
  // Photography page state spreads lightbox in so we can call show(N) from
  // anywhere within x-data="photography".
  Alpine.data("photography", () => ({
    mobileMenu: false,
    ...lightbox(),  // adds open/src/alt/idx/images/init/show/next/prev
  }));
});
