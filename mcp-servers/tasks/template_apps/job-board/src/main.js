import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { jobs, roleFamilies } from "./data.js";

function _buildAppState() { return {
  ...createRouter({ initial: "list", views: ["list", "detail", "apply", "submitted"] }),
  ...createPersistence({ namespace: "job-board", keys: ["savedJobs"] }),

  jobs,
  roleFamilies,
  filteredJobs: jobs,
  isLoading: false,

  filters: {
    search: "",
    remoteMode: "any",
    salaryMin: 60000,
    salaryMax: 300000,
    roleFamilies: [],
    seniority: "any",
  },

  _searchTimer: null,
  selectedJobId: null,
  application: { name: "", email: "", resume: "", cover: "" },
  trackingId: "",
  toastMsg: "",

  init() {
    this._hydrate();
    this.applyFilters();
  },

  onSearchInput() {
    if (this._searchTimer) clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => this.applyFilters(), 250);
  },

  applyFilters() {
    const q = this.filters.search.trim().toLowerCase();
    this.filteredJobs = this.jobs.filter((j) =>
      (q === "" || j.title.toLowerCase().includes(q) || j.company.toLowerCase().includes(q)) &&
      (this.filters.remoteMode === "any" || j.remoteMode === this.filters.remoteMode) &&
      j.salaryMin >= this.filters.salaryMin &&
      j.salaryMax <= this.filters.salaryMax + 50000 &&
      (this.filters.roleFamilies.length === 0 || this.filters.roleFamilies.includes(j.roleFamily)) &&
      (this.filters.seniority === "any" || j.seniority === this.filters.seniority)
    );
  },

  toggleRoleFamily(name) {
    const i = this.filters.roleFamilies.indexOf(name);
    if (i >= 0) this.filters.roleFamilies.splice(i, 1);
    else this.filters.roleFamilies.push(name);
    this.applyFilters();
  },

  openJob(jobId) {
    this.selectedJobId = jobId;
    this.setView("detail");
  },

  toggleSave(jobId) {
    const i = this.savedJobs.indexOf(jobId);
    if (i >= 0) {
      this.savedJobs.splice(i, 1);
      this.toast("Removed from saved jobs");
    } else {
      this.savedJobs.push(jobId);
      this.toast("Job saved");
    }
    this._save("savedJobs");
  },

  isSaved(jobId) { return this.savedJobs.includes(jobId); },

  get selectedJob() {
    return this.jobs.find((j) => j.id === this.selectedJobId);
  },

  async submitApplication() {
    if (!this.application.name || !this.application.email || !this.application.cover) return;
    this.isLoading = true;
    await simulateNetwork();
    this.isLoading = false;
    this.trackingId = `APP-${Math.floor(Math.random() * 90000 + 10000)}`;
    this.setView("submitted");
    this.application = { name: "", email: "", resume: "", cover: "" };
  },

  postedLabel(days) {
    if (days === 0) return "Today";
    if (days === 1) return "Yesterday";
    return `${days} days ago`;
  },

  formatSalary(min, max) {
    return `$${Math.round(min / 1000)}k – $${Math.round(max / 1000)}k`;
  },

  toast(msg) { this.toastMsg = msg; setTimeout(() => { this.toastMsg = ""; }, 2000); },
}; }

// Expose on window immediately AND via alpine:init to handle both
// defer'd script and ES module load-order races.
window.appState = _buildAppState;
document.addEventListener("alpine:init", () => { window.appState = _buildAppState; });
