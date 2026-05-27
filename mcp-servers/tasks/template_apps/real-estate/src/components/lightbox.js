// Lightbox overlay for image galleries.
// Usage: spread into a parent Alpine state, OR register as Alpine.data("lightbox", lightbox).
// Each gallery <img> carries data-img-slot="gallery"; gallery card click handlers
// invoke show(<index>) directly. The parent template wires body-scroll lock via
// `x-effect="document.body.style.overflow = open ? 'hidden' : ''"` on the overlay.
//
// Assumptions (these hold for static templates; revisit if ported to SPA shells):
//   - Gallery is rendered statically before init() runs (no x-for / dynamic mutation).
//   - Single page lifetime — keydown listener attaches to document and is never
//     removed. If reused in a multi-page SPA, store the handler reference and
//     remove it on a destroy() lifecycle method.
export const lightbox = () => ({
  open: false,
  src: "",
  alt: "",
  idx: 0,
  images: [],
  init() {
    // Collect all gallery images at boot. Each <img> must have data-img-slot="gallery".
    this.images = Array.from(document.querySelectorAll('[data-img-slot="gallery"]'))
      .map((img) => ({ src: img.dataset.full || img.src, alt: img.alt }));
    document.addEventListener("keydown", (e) => {
      if (!this.open) return;
      if (e.key === "Escape") { this.open = false; return; }
      if (e.key === "ArrowRight") this.next();
      if (e.key === "ArrowLeft") this.prev();
    });
  },
  show(i) {
    if (i < 0 || i >= this.images.length) return;
    this.idx = i;
    this.src = this.images[i].src;
    this.alt = this.images[i].alt;
    this.open = true;
  },
  next() { this.show((this.idx + 1) % this.images.length); },
  prev() { this.show((this.idx - 1 + this.images.length) % this.images.length); },
});
