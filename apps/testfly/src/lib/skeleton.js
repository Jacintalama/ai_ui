// Fake network delay. Used to gate data swaps so skeleton placeholders
// have time to render (otherwise the data flashes through instantly).
// Honors prefers-reduced-motion: short delay (50ms) so the loading state
// still toggles for assertion purposes, just imperceptibly.
export async function simulateNetwork(minMs = 800, maxMs = 1400) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ms = reduced ? 50 : minMs + Math.random() * (maxMs - minMs);
  await new Promise((r) => setTimeout(r, ms));
}
