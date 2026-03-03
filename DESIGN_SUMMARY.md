# Complete Design Summary — LoqAI Website

## Fonts

- **Body:** `Inter` (300–900) — Google Fonts
- **Headings (h1–h4):** `Space Grotesk` (400–700) — Google Fonts, `letter-spacing: -0.02em`
- **Icons:** Font Awesome 6.5.0 (Solid)

---

## Color Palette

| Token             | Hex / Value                  | Usage                                  |
| ----------------- | ---------------------------- | -------------------------------------- |
| `--primary`       | `#6366f1`                    | Indigo — primary brand, buttons        |
| `--primary-light` | `#818cf8`                    | Lighter indigo — links, icon highlights |
| `--accent`        | `#22d3ee`                    | Cyan — secondary accent, labels        |
| `--accent2`       | `#a855f7`                    | Purple — gradient endpoints            |
| `--dark`          | `#05050f`                    | Deepest background                     |
| `--dark2`         | `#0d0d20`                    | Alternate section background           |
| `--dark3`         | `#12122a`                    | Cards, navbar, mobile drawer           |
| `--border`        | `rgba(99,102,241,0.2)`       | Subtle borders                         |
| `--text-muted`    | `#94a3b8`                    | Body text, secondary text              |
| `--glass`         | `rgba(255,255,255,0.03)`     | Glassmorphism card fill                |
| `--glass-border`  | `rgba(255,255,255,0.08)`     | Glassmorphism card borders             |
| Body text         | `#e2e8f0`                    | Primary readable text                  |
| Stars             | `#f59e0b`                    | Testimonial star ratings               |
| Scrollbar         | `#6366f1` on `#05050f`       | Custom thin scrollbar                  |

---

## Key Gradients

- **Primary gradient:** `linear-gradient(135deg, #6366f1, #a855f7)` — buttons, CTA
- **Gradient text:** `linear-gradient(135deg, #6366f1, #22d3ee, #a855f7)` — `.gradient-text` with `-webkit-background-clip: text`
- **Accent gradient:** `linear-gradient(90deg, var(--primary), var(--accent))` — underlines, borders
- **Glows:** `radial-gradient(circle, rgba(99,102,241,0.12), transparent)` — hero background effects

---

## Layout System

- **Max widths:** Hero content `1200px`, sections use `padding: 100px 5%`
- **Grids:** CSS Grid with `repeat(auto-fit, minmax(300px, 1fr))` for cards; 2-column grid for testimonials
- **Responsive breakpoints:** `1024px` (tablet), `768px` (mobile)

---

## Navbar

- **Fixed**, `backdrop-filter: blur(20px)`, transparent bg `rgba(5,5,15,0.7)`
- Shrinks on scroll (`.scrolled` class: smaller padding, opaque bg)
- **Links:** `0.9rem`, muted color → white on hover, animated underline via `::after` with `scaleX` transition
- **Dropdown:** Appears on hover, `12px` below link, centered with `translateX(-50%)`, `border-radius: 12px`, `box-shadow: 0 16px 40px rgba(0,0,0,0.4)`
- **CTA button:** Gradient background, `8px` radius, lifts `-2px` on hover with purple glow shadow
- **Mobile:** Hamburger icon at `768px`, slide-in drawer from right (`280px` wide), overlay with `0.6` opacity black

---

## Hero Section

- **Two-column flex layout:** Text left (`flex: 1`), image right (`flex: 1.5`)
- **Canvas background** (particle animation via JS)
- **Glow orbs:** `900px` and `400px` radial gradients, positioned absolute
- **Title:** `clamp(3.5rem, 8vw, 6.5rem)`, weight `800`
- **Subtitle:** `clamp(1.15rem, 2.4vw, 1.4rem)`, muted color, `max-width: 680px`
- **CTA buttons:** Primary (gradient bg, inline-flex with arrow) + Secondary (bordered, transparent)
- Stacks vertically on mobile `≤768px`

---

## Logo Ticker

- Infinite horizontal marquee via `@keyframes marquee` (`translateX(0)` → `translateX(-50%)`)
- Logos duplicated for seamless loop
- `450×150px` per logo, `object-fit: contain`, no margin, full color
- Fade edges using `::before` / `::after` pseudo-elements with gradient from dark → transparent (`200px` wide)
- "Trusted By" label: `0.75rem`, uppercase, `letter-spacing: 3px`

---

## Cards (General Pattern)

```css
background: rgba(255,255,255,0.03);       /* var(--glass) */
border: 1px solid rgba(255,255,255,0.08); /* var(--glass-border) */
border-radius: 20px;
```

- **Hover:** `translateY(-6px to -8px)`, border brightens, gradient overlay fades in via `::before`
- **Transition:** `0.4s cubic-bezier(0.4, 0, 0.2, 1)`

---

## Section Headers

- **Label pill:** Cyan border/bg, uppercase, `0.75rem`, pulsing dot before text
- **Title:** `clamp(2rem, 4vw, 2.8rem)`, weight `700`, with `.gradient-text` span
- **Description:** `1.05rem`, muted, `max-width: 560px`, centered

---

## Why Section (Two-Column)

- **Left:** Visual card with SVG globe, gradient ring, floating badges with colored dots
- **Right:** 4 items, each with colored icon box + title + description
- **Icon boxes:** `48×48px`, `12px` radius, colored backgrounds at ~12% opacity

---

## How It Works

- Step cards with large step numbers
- Connecting line visual between steps

---

## Stats Section

- Grid cards with large animated counter numbers (`data-target` attribute)
- Number animation via JS (counts up on scroll into view)

---

## Testimonials (2-Column Grid)

- **Star ratings:** Font Awesome solid stars, amber `#f59e0b`
- **Service badge pill:** Top-right, `0.7rem`, rounded, indigo bg at 12%
- **Quote:** Large curly `"` via `::before` pseudo-element (`3.5rem`, primary color at `0.25` opacity)
- **Author row:** Company logo avatar (`46×46px`, circular, glassmorphism border) + name + company text

---

## Pricing

- Single centered card
- Gradient icon, tag pills
- CTA button

---

## Team Section

- **Grid:** `repeat(auto-fit, minmax(240px, 1fr))`
- **Cards:** Circular avatar (`80×80px`) with gradient ring (`::after` pseudo), name, role (cyan accent), bio, social links
- **Hover:** Lifts `-8px`, top accent line scales in via `::before`

---

## Contact

- Centered layout
- Icon boxes (`48×48px`, `12px` radius) with labels and values
- Email/phone as links with hover color transition

---

## Footer

- **4-column grid** (brand wider at `1.5fr`)
- Brand logo + description + social icons
- Column titles: uppercase, `0.85rem`
- Link lists: muted → white on hover
- **Bottom bar:** Copyright + legal links, `border-top` separator

---

## Animations

| Name       | Effect                                          |
| ---------- | ----------------------------------------------- |
| `fadeUp`   | Opacity 0→1, translateY 30px→0                  |
| `float`    | translateY 0→-18px→0 (6s loop)                  |
| `pulse`    | Scale/opacity pulse (2s infinite)               |
| `glow`     | Box-shadow pulse (indigo)                       |
| `marquee`  | translateX 0→-50% (for ticker)                  |
| `spin`     | Continuous clockwise rotation                   |
| `spinCCW`  | Continuous counter-clockwise rotation            |
| `.fade-up` | Scroll-triggered via JS (adds `.visible` class) |

---

## Button Styles

- **Primary:** `linear-gradient(135deg, primary, accent2)`, white text, `8px` radius, inline-flex with arrow icon, lifts + glow shadow on hover
- **Secondary:** Transparent bg, `1px` border (glass-border), `8px` radius, text color inherits, hover → slight bg + border change

---

## Scrollbar

- `6px` wide
- Dark track (`#05050f`)
- Indigo thumb (`#6366f1`)
- `3px` border-radius

---

## Glass / Frosted Pattern (Used Everywhere)

```css
background: rgba(255,255,255,0.03);
border: 1px solid rgba(255,255,255,0.08);
border-radius: 20px;
backdrop-filter: blur(20px); /* navbar only */
```
