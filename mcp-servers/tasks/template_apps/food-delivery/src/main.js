import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { restaurants, cuisines } from "./data.js";

function _buildAppState() { return {
  ...createRouter({ initial: "restaurants", views: ["restaurants", "menu", "cart", "checkout", "confirmation"] }),
  ...createPersistence({ namespace: "food-delivery", keys: ["cart"] }),

  restaurants,
  cuisines,

  // Filter state (in-memory; not persisted)
  filters: { cuisine: "all", minRating: 0, maxEta: 60 },
  filteredRestaurants: [],
  isLoading: false,

  // Current selection
  activeRestaurantId: null,

  // Cart shape: { restaurantId, items: [{itemId, qty}] }
  // Initialized to null by persistence factory; hydrated in init()
  cart: { restaurantId: null, items: [] },

  // Checkout form
  address: { line1: "", city: "", zip: "" },
  card: "",

  toastMsg: "",

  init() {
    this._hydrate();
    // Persistence factory defaults cart to [] but our shape is an object.
    // Recover or initialize.
    if (Array.isArray(this.cart) || !this.cart || typeof this.cart !== "object") {
      this.cart = { restaurantId: null, items: [] };
    }
    if (!this.cart.items) this.cart.items = [];
    this.applyFilters();
  },

  applyFilters() {
    this.filteredRestaurants = this.restaurants.filter((r) =>
      (this.filters.cuisine === "all" || r.cuisine === this.filters.cuisine) &&
      r.rating >= this.filters.minRating &&
      r.eta <= this.filters.maxEta
    );
  },

  async openMenu(restaurantId) {
    this.activeRestaurantId = restaurantId;
    this.isLoading = true;
    this.setView("menu");
    await simulateNetwork();
    this.isLoading = false;
  },

  get activeRestaurant() {
    return this.restaurants.find((r) => r.id === this.activeRestaurantId);
  },

  get cartRestaurant() {
    return this.restaurants.find((r) => r.id === this.cart.restaurantId) ?? null;
  },

  cartItem(itemId) {
    if (!this.cartRestaurant) return null;
    return this.cartRestaurant.items.find((it) => it.id === itemId) ?? null;
  },

  get cartTotal() {
    if (!this.cart.items.length) return 0;
    const rest = this.restaurants.find((r) => r.id === this.cart.restaurantId);
    if (!rest) return 0;
    return this.cart.items.reduce((sum, line) => {
      const item = rest.items.find((it) => it.id === line.itemId);
      return sum + (item ? item.price * line.qty : 0);
    }, 0);
  },

  get cartCount() {
    return this.cart.items.reduce((sum, line) => sum + line.qty, 0);
  },

  get cartDeliveryFee() {
    return this.cart.items.length ? 3.99 : 0;
  },

  get cartTax() {
    return Math.round(this.cartTotal * 0.08 * 100) / 100;
  },

  get cartGrandTotal() {
    return Math.round((this.cartTotal + this.cartDeliveryFee + this.cartTax) * 100) / 100;
  },

  addItem(itemId) {
    // If cart belongs to a different restaurant, replace.
    if (this.cart.restaurantId && this.cart.restaurantId !== this.activeRestaurantId) {
      this.cart = { restaurantId: this.activeRestaurantId, items: [] };
    }
    if (!this.cart.restaurantId) this.cart.restaurantId = this.activeRestaurantId;
    const line = this.cart.items.find((l) => l.itemId === itemId);
    if (line) line.qty++;
    else this.cart.items.push({ itemId, qty: 1 });
    this._save("cart");
    this.toast("Added to cart");
  },

  removeItem(itemId) {
    const line = this.cart.items.find((l) => l.itemId === itemId);
    if (!line) return;
    line.qty--;
    if (line.qty <= 0) {
      this.cart.items = this.cart.items.filter((l) => l.itemId !== itemId);
    }
    if (this.cart.items.length === 0) this.cart.restaurantId = null;
    this._save("cart");
  },

  clearCart() {
    this.cart = { restaurantId: null, items: [] };
    this._save("cart");
  },

  itemQty(itemId) {
    const line = this.cart.items.find((l) => l.itemId === itemId);
    return line ? line.qty : 0;
  },

  // Called from the checkout view's "Confirm order" button (NOT from the cart view).
  // The cart view's "Place order" button advances to checkout via setView('checkout').
  placeOrder() {
    this.toast("Order placed!");
    this.clearCart();
    this.setView("confirmation");
  },

  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ""; }, 2000);
  },
}; }

// Expose on window immediately AND via alpine:init to handle both
// defer'd script and ES module load-order races.
window.appState = _buildAppState;
document.addEventListener("alpine:init", () => { window.appState = _buildAppState; });
