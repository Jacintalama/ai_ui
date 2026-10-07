# Design System – Crumb and Co

Visual identity for the Crumb and Co bakery landing page, reflecting Swiss design sensibility and artisan craft values.

## Palette

- **Flour** `#FAF8F5` – Primary background, clean and warm
- **Wheat** `#D4A574` – Accent color, highlights and emphasis
- **Crust** `#634832` – Primary text, buttons, structured elements
- **Dark Crust** `#3D2A1F` – High-emphasis actions, footer background

Secondary usage:
- White `#FFFFFF` for secondary background sections
- Wheat/20 `rgba(212, 165, 116, 0.2)` for subtle tinted backgrounds
- Crust/70 and Crust/80 for secondary and tertiary text

## Typography

**Primary typeface:** Work Sans  
Loaded via @font-face, weights 400–700

**Hierarchy:**
- Hero heading (h2): 4rem (64px), bold, leading tight (1.1)
- Section heading (h3): 2.5rem (40px), bold
- Card heading (h4): 1.75rem (28px), bold
- Subheading: 1.125rem (18px), bold
- Body text: 1rem (16px), regular and medium
- Small text: 0.875rem (14px), used for labels and navigation
- Large body: 1.25rem (20px) for emphasis paragraphs

**Treatment:**
- `text-wrap: balance` on all headings
- `text-wrap: pretty` on paragraphs
- Uppercase tracking-wide labels for section markers

## Spacing

**Base unit:** Tailwind's spacing scale (0.25rem = 4px)

**Vertical rhythm:**
- Section padding: py-24 (6rem / 96px) for major sections, py-16 (4rem) for minor
- Section margins: mb-16 (4rem) between major groups, mb-8 (2rem) for subsections
- Element margins: mb-6 (1.5rem) for headings, mb-4 (1rem) for images, mb-2 (0.5rem) for tight groups
- More space above headings than below (standard hierarchy)

**Horizontal layout:**
- Max width container: max-w-7xl (80rem / 1280px) with px-6 (1.5rem) padding
- Grid gaps: gap-16 (4rem) for major layout, gap-8 (2rem) for card grids, gap-4 (1rem) for inline elements

**Component spacing:**
- Button padding: px-7 py-4 for primary, px-5 py-2.5 for navigation
- Card spacing: group > image mb-4, heading mb-2, tight leading-relaxed on text

## Components

**Navigation:**
- Fixed header with bg-flour/95 backdrop blur
- Border-bottom border-crust/10 for subtle separation
- Text links with hover:text-wheat transition

**Buttons:**
- Primary: bg-dark-crust text-flour, hover to bg-crust
- Secondary: border-2 border-crust, hover fills with crust
- Inline actions with icons (Lucide arrow-right)

**Cards:**
- Product cards: aspect-square images, rounded-sm, overflow-hidden
- Hover: opacity-90 on image (subtle, no transforms)
- Consistent image aspect ratios: square for products, 4:3 for heroes

**Images:**
- All SVG illustrations with consistent color palette
- object-cover for proper framing
- rounded-sm (0.125rem border radius) as standard treatment

**Browser chrome:**
- Custom ::selection background wheat, text flour
- Custom scrollbar: track flour, thumb crust
- Focus rings: 2px solid wheat with 2px offset
- Caret color: crust

## Motion

Minimal, purposeful motion:
- Transitions: 200-300ms for colors, opacity
- Ease: standard ease for most, ease-out for reveals
- No scale transforms on images
- Backdrop blur on fixed navigation for depth
