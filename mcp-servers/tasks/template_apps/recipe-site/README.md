# Salt & Pan — Recipe Site Template

Browse recipes, scale ingredients to any serving count, and cook through step-by-step with an optional timer and screen wakelock.

## Features

- **4-view flow:** Catalog (browse + filter) -> Recipe detail (serving scaler + step preview) -> Cook mode (fullscreen) -> Completed
- **Live serving-size slider** — drag from 1 to 8 servings; quantities rescale instantly using fraction glyphs (½ cup, ¾ tsp, etc.)
- **Fraction rendering** — `formatQuantity()` produces Unicode fractions (⅛ ¼ ⅓ ½ ⅔ ¾) within 0.04 tolerance; integers and decimals fall back to numeric
- **Fullscreen cook mode** — single-step view (`fixed inset-0 z-40`) with large Fraunces display text
- **3:00 step timer** — countdown with audio chime on completion; clears on step advance
- **Screen wakelock** — `navigator.wakeLock.request("screen")` wrapped in try/catch (gracefully no-op in unsupported browsers)
- **30 recipes** — vegan, vegetarian, gluten-free, dairy-free diets; easy / medium difficulty
- **Filters** — ingredient/title search, diet pills, time bucket pills, difficulty pills
- **localStorage persistence** — `favorites[]` and `cookingHistory[]` under `io-template:recipe-site` namespace
- **Warm white + olive palette** — `--bg: #faf6f1`, `--accent: #556b2f`
- **Fraunces** (display headings) + **Inter** (body) typography

## Palette

| Token          | Value     |
|----------------|-----------|
| `--bg`         | `#faf6f1` |
| `--bg-card`    | `#f3ede4` |
| `--accent`     | `#556b2f` |
| `--accent-soft`| `#e8e0d0` |
| `--text`       | `#1f2937` |
| `--text-muted` | `#6b7280` |

## Serving Scale Logic

`scaledQty(ing)` computes `ing.qty * (servings / baseServings)` then passes the result to `formatQuantity()`:

- `0.5` → `½`
- `1.5` → `1 ½`
- `2.0` → `2`
- `0.333...` → `⅓`
- `0.25` → `¼`

## Cook Mode Wakelock

```js
try {
  if ("wakeLock" in navigator) {
    this.wakeLock = await navigator.wakeLock.request("screen");
  }
} catch { /* unsupported or denied: silently no-op */ }
```

Released in both `exitCookMode()` and `completeCooking()`.

## Run locally

```bash
cd template_apps/recipe-site
python -m http.server 8204
# open http://localhost:8204
```

## File structure

```
recipe-site/
  index.html          -- All 4 views (Alpine x-show)
  styles/main.css     -- CSS custom properties (warm white/olive palette)
  src/
    data.js           -- 30 recipes with ingredients and steps
    main.js           -- Alpine root: filters, serving scale, cook mode, wakelock
    lib/
      router.js       -- Block A: view history stack
      persistence.js  -- Block B: localStorage with try/catch
      skeleton.js     -- Block C: simulateNetwork delay
      countUp.js      -- Block F: rAF tween (ingredient quantity tweens)
  public/
    .gitkeep
```
