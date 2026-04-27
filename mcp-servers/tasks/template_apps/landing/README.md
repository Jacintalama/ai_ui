# <%= APP_NAME %> — Landing Page

A modern, conversion-focused SaaS landing page template (no backend required).

## Structure

```
index.html              Page markup with sticky header, hero, features, testimonials, pricing, FAQ, CTA, footer
styles/main.css         Project-specific overrides (Tailwind handles 95%)
src/main.js             Alpine bootstrap + Lucide icon refresh
src/components/         Alpine factories
  LandingPage.js        Mobile menu, FAQ accordion, content data
public/                 Static assets (empty)
```

## Customizing

- Copy is data-driven: edit the `features`, `steps`, `testimonials`, `plans`, and `faqs` arrays in `LandingPage.js`.
- Colors: replace the `indigo` Tailwind palette with your brand color throughout `index.html`.
- Sections are self-contained — drop or reorder them as needed.
