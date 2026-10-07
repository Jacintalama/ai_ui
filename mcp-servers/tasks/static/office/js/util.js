// Small things the whole office uses: how it authenticates a read, how it
// escapes what it draws, and how it says "2h ago".
//
// Pure except for getJson, which is the one place a request is made, and
// authHeaders, which reads the stored token.

export function authHeaders() {
  var h = { "Content-Type": "application/json" };
  var t = localStorage.getItem("token");
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

export async function getJson(url) {
  var r = await fetch(url, { headers: authHeaders(), credentials: "include" });
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

export function ago(iso) {
  if (!iso) return "never";
  var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return Math.round(s) + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

export function saying(id) { return String(id || "").replace(/-/g, " "); }
