# <%= APP_NAME %> — Personal Portfolio

A polished personal-portfolio template with light/dark theme, project filtering, and a working (simulated) contact form.

## Structure

```
index.html              Single-page portfolio with header, hero, work, about, skills, contact, footer
styles/main.css         Project-specific overrides
src/main.js             Alpine bootstrap + Lucide
src/components/
  Portfolio.js          Theme toggle (localStorage), project filter, contact form, content
public/                 Static assets (empty)
```

## Customizing

- Edit `Portfolio.js` to change `name`, `initials`, `projects`, and `skills`.
- Replace the about-section image and project seed numbers (each `seed` produces a deterministic placeholder from picsum.photos).
- The contact form is currently simulated — wire it to your backend by replacing the body of `submitContact()`.
