export function navigation() {
  return {
    mobileMenuOpen: false,

    init() {
      // Close mobile menu when clicking on a link
      this.$el.addEventListener('click', (e) => {
        if (e.target.tagName === 'A' && this.mobileMenuOpen) {
          this.mobileMenuOpen = false;
        }
      });

      // Close mobile menu on escape key
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.mobileMenuOpen) {
          this.mobileMenuOpen = false;
        }
      });
    }
  };
}
