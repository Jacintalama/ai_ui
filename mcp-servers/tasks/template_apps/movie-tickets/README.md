# Lumen Cinemas — Movie Tickets Template

Interactive cinema ticket booking demo with a 10×14 seat picker as the centerpiece.

## Features

- **6-view flow:** Now Showing → Film detail → Showtime picker → Seat picker → Checkout → Tickets
- **10×14 interactive seat grid** — available / taken / selected / aisle states
- **Animated running total** — count-up tween as seats are toggled (Block F)
- **Max 8 seats per booking** — enforced with a toast notification
- **Deterministic seat occupancy** — ~30% taken per showtime via hash (stable across reloads)
- **12 films, 3 theaters, 5 showtimes each** (180 showtimes total)
- **localStorage persistence** — `bookedShowings[]` under `io-template:movie-tickets` namespace
- **Black + amber palette** — `--bg: #0a0a0a`, `--accent: #f59e0b`
- Genre filter pills + theater filter on the Now Showing view

## Palette

| Token       | Value     |
|-------------|-----------|
| `--bg`      | `#0a0a0a` |
| `--bg-card` | `#1a1a1a` |
| `--accent`  | `#f59e0b` |
| `--text`    | `#ffffff` |

## Seat Grid

- **10 rows** (A–J), **14 columns**
- **Aisles** at columns 4 and 9 (zero-indexed) — rendered as spacers, not buttons
- Seat occupancy hash: `(seed * (row+1) * (col+2)) % 10 < 3` → ~30% taken

## Run locally

```bash
cd template_apps/movie-tickets
python -m http.server 8203
# open http://localhost:8203
```

## File structure

```
movie-tickets/
  index.html          — All 6 views (Alpine x-show)
  styles/main.css     — CSS custom properties (black/amber palette)
  src/
    data.js           — Films, theaters, showtimes, seat occupancy
    main.js           — Alpine root: seat picker, count-up, confirmPayment
    lib/
      router.js       — Block A: view history stack
      persistence.js  — Block B: localStorage with try/catch
      skeleton.js     — Block C: simulateNetwork delay
      countUp.js      — Block F: rAF tween for animated total
  public/
    .gitkeep
```
