# Skylane — Flight Booking Template

Single-page flight search and booking app built on the IO App Builder's
static-template baseline (Tailwind CDN + Alpine.js + vanilla ES modules,
no build step).

## What's included

- Single-page state machine: search → results → detail → review
- 30 demo flights across 8 routes (JFK, LHR, SFO, NRT, LAX, CDG, ATL, FCO)
- Real client-side filters: price slider, stops, time of day, airlines, duration
- 800-1400ms fake-network delay so skeleton placeholders have airtime
- Saved trips persist across reloads (localStorage namespace: `flight-booking`)
- Honors `prefers-reduced-motion`

## Local preview

```bash
cd template_apps/flight-booking
python -m http.server 8200
# open http://localhost:8200
```

## Customization safe spots

- `src/data.js` — flight catalog, airlines list, city codes
- `styles/main.css` — `--bg`, `--accent`, `--text` CSS custom properties
- Brand name "Skylane" appears in `index.html` (header) and `<title>`
