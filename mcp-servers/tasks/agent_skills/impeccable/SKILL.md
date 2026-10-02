---
name: impeccable
description: "Build and change websites, landing pages and app screens to a high design standard with the Impeccable design skill. Use when asked to build, design, redesign, restyle or polish a site or page, or to make an app look or read better."
allowed-tools: code
metadata:
  tags: design, website, site, landing, redesign, restyle, polish, look, frontend
  source: "Condensed from Impeccable by Paul Bakaus, https://impeccable.style, Apache License 2.0"
---

# Impeccable design

With this skill ticked, every app you create or change is built with the
real Impeccable design skill: the builder loads it, follows it, and runs its
design checker before it finishes. Your part is the brief.

## Steps

1. A new site or page: `create_app` with their own words. When they told
   you, add one short line each for who it is for, what a visitor should do,
   and the tone. Never invent facts about their business, prices or people.
2. A change to an app that exists: `list_my_apps`, read the file you would
   change, then `propose_app_change` naming the design problem in plain
   terms (hierarchy, spacing, contrast, type size, a missing state) and what
   must stay as it is. Wait for their yes before `apply_app_change`.
3. Give them the link exactly as the result writes it, and say the build
   takes a few minutes. It is not built yet when create_app answers: say it
   is ready only after `build_status` says so.

## The standard the work is held to

- Contrast: body text at least 4.5:1 against its background, large text
  3:1. No light gray text on a tinted white.
- Type: body lines 65 to 75 characters wide, display headings no larger
  than 6rem, one family in several weights or a clear serif and sans pair.
- Layout: spacing that varies with meaning, more space above a heading than
  below it. Cards only when a card is the best container, never nested.
- Motion: one deliberate moment rather than an effect on every section,
  easing out, with a reduced-motion alternative, and content that is
  visible without the animation.
- States: hover, keyboard focus, disabled, loading, error and empty are all
  designed, not left to browser defaults.
- Copy: the product's own words. Buttons name their action; an error says
  what went wrong and how to recover.
- Refused by default, because they are what makes a page look generated:
  gradient text, a small label above every heading, a page built from
  same-size icon cards, glass and blur as decoration, thick colored side
  borders on cards, emoji standing in for icons, and the big-number hero
  with a row of small stats.
- A change keeps the app's look, copy and behaviour outside what was asked.

## Rules

- Their words beat these rules. Asked for gradient text, they get gradient
  text.
- Do not quiz them about colors or fonts. The builder decides the look
  inside these rules, and they can ask for changes after they see it.
- Say which app you built or changed, once, by its name.
