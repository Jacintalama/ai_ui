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

// A wrong or MOVED path under /api/ is answered with Open WebUI's own
// index.html and HTTP 200. Measured on production 2026-11-09:
//
//   /api/v1/nonexistent    200 text/html   <!doctype html><html lang="en">
//   /tasks/api/nonexistent 404 application/json
//
// So r.ok is TRUE, r.json() then throws V8's "Unexpected token '<',
// "<!DOCTYPE "... is not valid JSON", and that string is what reaches the
// screen. It names neither the call nor the cause, which is why the red
// toast Ralph saw sat untraced: by HTTP's reckoning the request succeeded,
// so no amount of checking r.ok can catch it. Only the content type tells
// the truth. Our own routes answer JSON correctly; the exposure is this
// code calling Open WebUI's API, which an upgrade can rename under us.
export function expectJson(r, url) {
  var ct = (r && r.headers && r.headers.get && r.headers.get("content-type")) || "";
  if (ct.indexOf("json") === -1) {
    throw new Error(url + " -> " + r.status + " " + (ct || "no content type")
                    + ", not JSON. That route has probably moved.");
  }
}

export async function getJson(url) {
  var r = await fetch(url, { headers: authHeaders(), credentials: "include" });
  if (!r.ok) throw new Error(url + " -> " + r.status);
  expectJson(r, url);
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
