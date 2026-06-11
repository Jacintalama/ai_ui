# Roost — Food Delivery Template

A restaurant browsing and ordering template with a real persistent cart. Browse 14 restaurants across 8 cuisine types, add items with the +/- stepper, and watch the cart count badge update in real time. The cart survives page reloads via localStorage, and the multi-step flow (restaurants → menu → cart → checkout → confirmation) uses hash-free client-side routing.

## Customize

| What to change | Where |
|---|---|
| Brand name | `index.html` — `<title>` and the `<span>Roost</span>` in the header |
| Palette (background, accent) | `styles/main.css` — `:root` CSS custom properties |
| Restaurant list + menus | `src/data.js` — `restaurantSeeds` array and `itemTemplatesByCuisine` map |
| Delivery fee | `src/data.js` — `deliveryFee: 3.99` per restaurant; `src/main.js` — `cartDeliveryFee` getter |
| Tax rate | `src/main.js` — `cartTax` getter (`0.08` = 8%) |

## Image Sources

- Restaurant hero/thumb images: [Unsplash](https://unsplash.com) — stable photo IDs in `heroPhotos[]`
- Menu item images: [picsum.photos](https://picsum.photos) — seeded deterministic URLs

Both domains are on the CDN whitelist for this template series.

## Tech Stack

- [Alpine.js](https://alpinejs.dev) v3 — reactivity, no build step
- [Tailwind CSS](https://tailwindcss.com) CDN — utility styling
- [Inter](https://fonts.google.com/specimen/Inter) + [DM Sans](https://fonts.google.com/specimen/DM+Sans) — Google Fonts
- localStorage persistence scoped to `io-template:food-delivery:`

## Development

```bash
cd mcp-servers/tasks/template_apps/food-delivery
python -m http.server 8201
# open http://localhost:8201
```
