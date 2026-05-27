// Salt & Pan — recipe site main state.
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { recipes }           from "./data.js";

// ── Fraction glyphs ────────────────────────────────────────────────────────
const FRACTIONS = [
  [0.125, "⅛"], // ⅛
  [0.25,  "¼"], // ¼
  [0.333, "⅓"], // ⅓
  [0.5,   "½"], // ½
  [0.667, "⅔"], // ⅔
  [0.75,  "¾"], // ¾
];

function formatQuantity(value) {
  if (value === 0) return "";
  const whole = Math.floor(value);
  const frac  = Math.round((value - whole) * 1000) / 1000;
  let glyph = "";
  for (const [v, sym] of FRACTIONS) {
    if (Math.abs(frac - v) < 0.04) { glyph = sym; break; }
  }
  if (whole === 0 && glyph)  return glyph;
  if (whole >  0 && glyph)   return `${whole} ${glyph}`;
  if (whole >  0 && frac === 0) return `${whole}`;
  // Fallback: trim trailing zeros
  return value.toFixed(2).replace(/\.?0+$/, "");
}

// ── App root ────────────────────────────────────────────────────────────────
// Register via alpine:init to guarantee the function exists before Alpine
// walks the DOM — ES modules are always deferred, which can race with Alpine's
// own defer'd initialisation on slow/CDN loads.
function _buildAppState() {
  return {
  ...createRouter({ initial: "catalog", views: ["catalog", "recipe", "cook-mode", "completed"] }),
  ...createPersistence({ namespace: "recipe-site", keys: ["favorites", "cookingHistory"] }),

  recipes,
  filteredRecipes: recipes,
  filters: { ingredientSearch: "", diet: [], timeBucket: "any", difficulty: "any" },
  isLoading: false,

  selectedRecipeId: null,
  servings: 2,
  stepIndex: 0,
  timer: { remaining: 0, running: false, _interval: null },
  wakeLock: null,

  toastMsg: "",

  init() {
    this._hydrate();
    this.applyFilters();
    // Minimal silent WAV for timer chime — base64 header only produces a click,
    // sufficient as an audible cue without bundling an external asset.
    try {
      this._chime = new Audio(
        "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="
      );
    } catch { this._chime = null; }
  },

  // ── Filtering ─────────────────────────────────────────────────────────────
  applyFilters() {
    const q = this.filters.ingredientSearch.trim().toLowerCase();
    this.filteredRecipes = this.recipes.filter((r) => {
      const matchesSearch =
        q === "" ||
        r.ingredients.some((ing) => ing.name.toLowerCase().includes(q)) ||
        r.title.toLowerCase().includes(q);
      const matchesDiet =
        this.filters.diet.length === 0 ||
        this.filters.diet.every((d) => r.diet.includes(d));
      const matchesTime =
        this.filters.timeBucket === "any" ||
        (this.filters.timeBucket === "<15" ? r.minutes < 15  :
         this.filters.timeBucket === "<30" ? r.minutes < 30  :
         this.filters.timeBucket === "<60" ? r.minutes < 60  : true);
      const matchesDiff =
        this.filters.difficulty === "any" || r.difficulty === this.filters.difficulty;
      return matchesSearch && matchesDiet && matchesTime && matchesDiff;
    });
  },

  toggleDiet(d) {
    const i = this.filters.diet.indexOf(d);
    if (i >= 0) this.filters.diet.splice(i, 1);
    else         this.filters.diet.push(d);
    this.applyFilters();
  },

  isDietActive(d) { return this.filters.diet.includes(d); },

  // ── Recipe navigation ─────────────────────────────────────────────────────
  openRecipe(id) {
    this.selectedRecipeId = id;
    const r = this.selectedRecipe;
    this.servings = r?.baseServings ?? 2;
    this.setView("recipe");
  },

  get selectedRecipe() {
    return this.recipes.find((r) => r.id === this.selectedRecipeId) ?? null;
  },

  // ── Serving scale + fraction formatter ────────────────────────────────────
  scaledQty(ing) {
    const r = this.selectedRecipe;
    if (!r) return "";
    const scale = this.servings / r.baseServings;
    return formatQuantity(ing.qty * scale);
  },

  // ── Favorites ─────────────────────────────────────────────────────────────
  toggleFavorite(id) {
    const i = this.favorites.indexOf(id);
    if (i >= 0) this.favorites.splice(i, 1);
    else         this.favorites.push(id);
    this._save("favorites");
    this.toast(this.favorites.includes(id) ? "Saved to favorites" : "Removed from favorites");
  },

  isFavorite(id) { return this.favorites.includes(id); },

  // ── Cook mode ─────────────────────────────────────────────────────────────
  async startCookMode() {
    this.stepIndex = 0;
    this.timer = { remaining: 0, running: false, _interval: null };
    // Wakelock: keep screen on while cooking. Silently no-op if unsupported/denied.
    try {
      if ("wakeLock" in navigator) {
        this.wakeLock = await navigator.wakeLock.request("screen");
      }
    } catch { /* unsupported or permission denied: silently no-op */ }
    this.setView("cook-mode");
  },

  exitCookMode() {
    if (this.timer._interval) clearInterval(this.timer._interval);
    if (this.wakeLock) { this.wakeLock.release().catch(() => {}); this.wakeLock = null; }
    this.setView("recipe");
  },

  nextStep() {
    if (!this.selectedRecipe) return;
    if (this.stepIndex < this.selectedRecipe.steps.length - 1) {
      this.stepIndex++;
      // Clear timer when advancing to a new step
      if (this.timer._interval) clearInterval(this.timer._interval);
      this.timer = { remaining: 0, running: false, _interval: null };
    } else {
      this.completeCooking();
    }
  },

  prevStep() {
    if (this.stepIndex > 0) this.stepIndex--;
  },

  // ── Timer ─────────────────────────────────────────────────────────────────
  startTimer(seconds = 180) {
    if (this.timer._interval) clearInterval(this.timer._interval);
    this.timer.remaining = seconds;
    this.timer.running   = true;
    this.timer._interval = setInterval(() => {
      this.timer.remaining--;
      if (this.timer.remaining <= 0) {
        clearInterval(this.timer._interval);
        this.timer.running = false;
        try { if (this._chime) this._chime.play().catch(() => {}); } catch {}
        this.toast("Timer done");
      }
    }, 1000);
  },

  timerLabel() {
    if (this.timer.remaining <= 0) return "—"; // —
    const m = Math.floor(this.timer.remaining / 60);
    const s = this.timer.remaining % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  },

  // ── Completion ────────────────────────────────────────────────────────────
  // Commit pattern: async work first, then setView.
  completeCooking() {
    if (this.selectedRecipeId) {
      this.cookingHistory.push({
        recipeId: this.selectedRecipeId,
        completedAt: new Date().toISOString(),
      });
      this._save("cookingHistory");
    }
    if (this.wakeLock) { this.wakeLock.release().catch(() => {}); this.wakeLock = null; }
    if (this.timer._interval) clearInterval(this.timer._interval);
    this.setView("completed");
  },

  // ── Toast ─────────────────────────────────────────────────────────────────
  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ""; }, 2000);
  },
  };
}

// Make available on window immediately (for environments where the module
// loads synchronously before Alpine), AND via alpine:init for the deferred case.
window.appState = _buildAppState;
document.addEventListener("alpine:init", () => {
  // alpine:init fires before Alpine walks the DOM, so re-registering here
  // ensures it's available regardless of module vs defer load order.
  window.appState = _buildAppState;
});
