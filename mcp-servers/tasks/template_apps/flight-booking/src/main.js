// src/main.js — Alpine root with router, persistence, search, filters, save.
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { flights, cities, airlines } from "./data.js";

function _buildAppState() { return {
  ...createRouter({ initial: "search", views: ["search", "results", "detail", "review", "saved"] }),
  ...createPersistence({ namespace: "flight-booking", keys: ["savedTrips"] }),

  // Reference data
  cities,
  airlines,
  allFlights: flights,

  // Search form
  searchForm: { origin: "JFK", destination: "LHR", depart: "2026-10-12", returnDate: "2026-10-19", pax: 1, cabin: "Economy" },

  // Results state
  filteredFlights: [],
  isLoading: false,
  filters: { maxPrice: 2000, stops: "any", timeOfDay: "any", airlines: [], maxDuration: 900 },

  // Detail/review state
  selectedFlight: null,
  passengerNames: [""],

  // Toast
  toastMsg: "",

  init() {
    this._hydrate();
    this.filteredFlights = this.allFlights;
  },

  async runSearch() {
    this.isLoading = true;
    this.setView("results");
    await simulateNetwork();
    this.applyFilters();
    this.isLoading = false;
  },

  applyFilters() {
    this.filteredFlights = this.allFlights.filter((f) =>
      f.price <= this.filters.maxPrice &&
      f.duration <= this.filters.maxDuration &&
      (this.filters.stops === "any" || (this.filters.stops === "0" ? f.stops === 0 : f.stops >= 1)) &&
      (this.filters.timeOfDay === "any" || f.departureBucket === this.filters.timeOfDay) &&
      (this.filters.airlines.length === 0 || this.filters.airlines.includes(f.airline))
    );
  },

  toggleAirline(name) {
    const i = this.filters.airlines.indexOf(name);
    if (i >= 0) this.filters.airlines.splice(i, 1);
    else this.filters.airlines.push(name);
    this.applyFilters();
  },

  openDetail(flightId) {
    this.selectedFlight = this.allFlights.find((f) => f.id === flightId);
    this.setView("detail");
  },

  saveTrip() {
    if (!this.selectedFlight) return;
    if (!this.savedTrips.find((t) => t.id === this.selectedFlight.id)) {
      this.savedTrips.push(this.selectedFlight);
      this._save("savedTrips");
      this.toast("Trip saved");
    } else {
      this.toast("Already saved");
    }
  },

  removeTrip(flightId) {
    const i = this.savedTrips.findIndex((t) => t.id === flightId);
    if (i < 0) return;
    this.savedTrips.splice(i, 1);
    this._save("savedTrips");
    this.toast("Trip removed");
  },

  goReview() {
    this.passengerNames = Array.from({ length: this.searchForm.pax }, () => "");
    this.setView("review");
  },

  confirmBooking() {
    this.toast(`Confirmation sent (demo)`);
    this.setView("search");
    this.selectedFlight = null;
  },

  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ""; }, 2000);
  },

  formatDuration(min) {
    return `${Math.floor(min / 60)}h ${min % 60}m`;
  },
}; }

// Expose on window immediately AND via alpine:init to handle both
// defer'd script and ES module load-order races.
window.appState = _buildAppState;
document.addEventListener("alpine:init", () => { window.appState = _buildAppState; });
