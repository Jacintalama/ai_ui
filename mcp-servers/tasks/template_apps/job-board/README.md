# Workpath — Job Board Template

A job board single-page app template built with Alpine.js and Tailwind CSS.

## Features

- **60 jobs** across 12 companies, spanning 5 role families
- **Debounced search** (250ms) by job title or company name
- **Multi-filter chips**: work mode (remote/hybrid/on-site), salary range slider, role family, seniority
- **Bookmark toggle** — persisted via localStorage (`io-template:job-board:savedJobs`)
- **4 views**: list, detail, apply, submitted
- Application form with required-field validation
- Skeleton loading state on form submission
- Toast notifications on bookmark actions
- DiceBear `initials` API for company logos

## Views

| View | Route (Alpine state) | Description |
|---|---|---|
| List | `list` (initial) | Job cards with sidebar filters |
| Detail | `detail` | Full job description + apply/save buttons |
| Apply | `apply` | Application form (name, email, resume URL, cover letter) |
| Submitted | `submitted` | Confirmation with tracking ID |

## Palette

| Variable | Value |
|---|---|
| `--bg` | `#ffffff` |
| `--bg-card` | `#f8fafc` |
| `--text` | `#0f172a` |
| `--text-muted` | `#64748b` |
| `--accent` | `#2563eb` |
| `--border` | `#e2e8f0` |

## Development

```bash
cd template_apps/job-board
python -m http.server 8202
# Open http://localhost:8202
```

## File Structure

```
job-board/
  index.html          # App shell — 4 Alpine views
  styles/
    main.css          # CSS custom properties, reduced-motion guard
  src/
    data.js           # 60 job records + metadata
    main.js           # Alpine root — router, persistence, filters, submission
    lib/
      router.js       # View router (Block A)
      persistence.js  # localStorage helper (Block B)
      skeleton.js     # Simulated network delay (Block C)
  public/
    .gitkeep
```
