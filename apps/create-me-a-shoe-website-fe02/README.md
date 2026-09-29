# Create Me A Shoe Website Fe02 — Landing Page

A modern, conversion-focused SaaS landing page template (no backend required).

## Changelog

- **2026-09-11**: Added responsive shoe product landing page in `public/index.html` with hero, features, gallery, email capture form, testimonials, and footer sections. Includes placeholder images and Tailwind/Alpine.js setup.

## Structure

```
index.html              Page markup with sticky header, hero, features, testimonials, pricing, FAQ, CTA, footer
public/index.html       Standalone shoe product landing page (mobile-first, Tailwind CDN, Alpine.js)
assets/                 Placeholder image files (shoe-classic-blue.jpg, shoe-midnight-black.jpg, shoe-sunset-red.jpg)
styles/main.css         Project-specific overrides (Tailwind handles 95%)
src/main.js             Alpine bootstrap + Lucide icon refresh
src/components/         Alpine factories
  LandingPage.js        Mobile menu, FAQ accordion, content data
```

## How to run

Open `public/index.html` directly in a browser - no build step required. The page uses CDN-hosted Tailwind CSS and Alpine.js.

## Customizing

- Copy is data-driven: edit the `features`, `steps`, `testimonials`, `plans`, and `faqs` arrays in `LandingPage.js`.
- Colors: replace the `indigo` Tailwind palette with your brand color throughout `index.html`.
- Sections are self-contained — drop or reorder them as needed.
