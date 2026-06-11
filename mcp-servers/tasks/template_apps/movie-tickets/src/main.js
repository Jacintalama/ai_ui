import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { createCountUp }     from "./lib/countUp.js";
import { films, theaters, showtimes, SEAT_PRICE, genres } from "./data.js";

const MAX_SEATS = 8;
const ROWS = 10;
const COLS = 14;
const AISLES = new Set([4, 9]);

function _buildAppState() { return {
  ...createRouter({ initial: "now-showing", views: ["now-showing", "film", "showtime", "seats", "checkout", "tickets"] }),
  ...createPersistence({ namespace: "movie-tickets", keys: ["bookedShowings"] }),

  films,
  theaters,
  showtimes,
  SEAT_PRICE,
  genres,

  filters: { genre: "all", theaterId: "all" },
  filteredFilms: films,

  // Selection state
  selectedFilmId: null,
  selectedShowtimeId: null,
  selectedSeats: [],        // array of "row-col" strings

  // Payment form
  cardName: "",
  cardNumber: "",
  cardExpiry: "",
  cardCvv: "",

  // Counter (animated)
  displayedTotal: 0,
  _countUp: null,

  isLoading: false,
  toastMsg: "",

  init() {
    this._hydrate();
    this._countUp = createCountUp(300);
    this.applyFilters();
  },

  applyFilters() {
    this.filteredFilms = this.films.filter((f) =>
      this.filters.genre === "all" || f.genre.toLowerCase().includes(this.filters.genre.toLowerCase())
    );
  },

  openFilm(filmId) {
    this.selectedFilmId = filmId;
    this.setView("film");
  },

  openShowtimes(filmId) {
    this.selectedFilmId = filmId;
    this.setView("showtime");
  },

  pickShowtime(showtimeId) {
    this.selectedShowtimeId = showtimeId;
    this.selectedSeats = [];
    this.displayedTotal = 0;
    this.setView("seats");
  },

  get selectedFilm() {
    return this.films.find((f) => f.id === this.selectedFilmId);
  },

  get selectedShowtime() {
    return this.showtimes.find((s) => s.id === this.selectedShowtimeId);
  },

  isAisle(row, col) { return AISLES.has(col); },

  isTaken(row, col) {
    return this.selectedShowtime?.takenSeats.includes(`${row}-${col}`) ?? false;
  },

  isSelected(row, col) {
    return this.selectedSeats.includes(`${row}-${col}`);
  },

  seatClass(row, col) {
    if (this.isAisle(row, col))   return "bg-transparent cursor-default";
    if (this.isTaken(row, col))   return "bg-gray-700 cursor-not-allowed opacity-60";
    if (this.isSelected(row, col)) return "bg-[var(--accent)] text-black scale-110 shadow-lg shadow-amber-500/30";
    return "bg-gray-600 hover:bg-gray-400 cursor-pointer";
  },

  toggleSeat(row, col) {
    if (this.isAisle(row, col) || this.isTaken(row, col)) return;
    const key = `${row}-${col}`;
    const idx = this.selectedSeats.indexOf(key);
    if (idx >= 0) {
      this.selectedSeats.splice(idx, 1);
    } else if (this.selectedSeats.length < MAX_SEATS) {
      this.selectedSeats.push(key);
    } else {
      this.toast(`Max ${MAX_SEATS} seats per booking`);
      return;
    }
    // Animate running total
    const target = this.selectedSeats.length * SEAT_PRICE;
    this._countUp.to(target, (v) => { this.displayedTotal = v; });
  },

  rows() { return Array.from({ length: ROWS }, (_, r) => r); },
  cols() { return Array.from({ length: COLS }, (_, c) => c); },

  goCheckout() {
    if (this.selectedSeats.length === 0) return;
    this.setView("checkout");
  },

  async confirmPayment() {
    this.isLoading = true;
    await simulateNetwork(800, 1400);
    this.isLoading = false;
    this.bookedShowings.push({
      id: this.selectedShowtimeId,
      filmTitle: this.selectedFilm?.title ?? "",
      seats: [...this.selectedSeats],
      total: this.selectedSeats.length * SEAT_PRICE,
      slot: this.selectedShowtime?.slot ?? "",
      theater: this.theaterById(this.selectedShowtime?.theaterId)?.name ?? "",
      bookedAt: new Date().toISOString(),
      confirmationCode: `LC-${Math.floor(Math.random() * 90000 + 10000)}`,
    });
    this._save("bookedShowings");
    this.setView("tickets");
    // Reset payment form
    this.cardName = "";
    this.cardNumber = "";
    this.cardExpiry = "";
    this.cardCvv = "";
  },

  startOver() {
    this.selectedFilmId = null;
    this.selectedShowtimeId = null;
    this.selectedSeats = [];
    this.displayedTotal = 0;
    this.setView("now-showing");
  },

  showtimesForFilm(filmId) {
    return this.showtimes.filter((s) =>
      s.filmId === filmId &&
      (this.filters.theaterId === "all" || s.theaterId === this.filters.theaterId)
    );
  },

  theaterById(id) {
    return this.theaters.find((t) => t.id === id);
  },

  seatsAvailable(showtimeId) {
    const st = this.showtimes.find((s) => s.id === showtimeId);
    if (!st) return 0;
    // Total non-aisle seats = 10 rows × 12 cols (14 - 2 aisles)
    return 120 - st.takenSeats.length;
  },

  get lastBooking() {
    return this.bookedShowings[this.bookedShowings.length - 1] ?? null;
  },

  runtimeLabel(mins) {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  },

  toast(msg) { this.toastMsg = msg; setTimeout(() => { this.toastMsg = ""; }, 2000); },
}; }

// Expose on window immediately AND via alpine:init to handle both
// defer'd script and ES module load-order races.
window.appState = _buildAppState;
document.addEventListener("alpine:init", () => { window.appState = _buildAppState; });
