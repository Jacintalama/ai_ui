export function navigation() {
    return {
        mobileOpen: false,
        toggleMobile() {
            this.mobileOpen = !this.mobileOpen;
        }
    };
}
