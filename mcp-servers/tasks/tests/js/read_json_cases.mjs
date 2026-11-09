// Runs util.js's getJson for real against stubbed responses and prints what
// happened as JSON, so a pytest can assert on BEHAVIOUR rather than grep the
// source. Called by tests/test_an_html_page_is_not_json.py.
//
// The fake json() does JSON.parse on the body, exactly as a real Response
// does, so an HTML body produces V8's genuine "Unexpected token '<'" error.
// That is the bug being fixed, so the test must see the real thing.

const UTIL = process.argv[2];

globalThis.localStorage = { getItem: () => null };

function response(status, contentType, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k) => (String(k).toLowerCase() === "content-type" ? contentType : null) },
    async json() { return JSON.parse(body); },
    async text() { return body; },
  };
}

const SPA = '<!doctype html><html lang="en">\t<head>\t\t<meta charset="utf-8" />';

const CASES = {
  json_200: response(200, "application/json", '{"a":1}'),
  // The real find, measured on production 2026-11-09: a wrong or moved path
  // under /api/ is answered with Open WebUI's index.html and HTTP 200.
  html_200: response(200, "text/html; charset=utf-8", SPA),
  // No content-type at all must not crash the guard.
  html_200_no_type: response(200, null, SPA),
  json_404: response(404, "application/json", '{"detail":"nope"}'),
};

const out = {};
const { getJson } = await import(UTIL);

for (const [name, res] of Object.entries(CASES)) {
  globalThis.fetch = async () => res;
  try {
    out[name] = { threw: false, value: await getJson("/api/v1/auths/") };
  } catch (e) {
    out[name] = { threw: true, message: String((e && e.message) || e) };
  }
}

process.stdout.write(JSON.stringify(out));
