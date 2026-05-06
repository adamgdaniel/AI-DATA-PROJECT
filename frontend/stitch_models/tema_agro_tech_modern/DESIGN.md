---
name: Agro-Tech Modern
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#434843'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#737973'
  outline-variant: '#c3c8c1'
  surface-tint: '#4d6453'
  primary: '#061b0e'
  on-primary: '#ffffff'
  primary-container: '#1b3022'
  on-primary-container: '#819986'
  inverse-primary: '#b4cdb8'
  secondary: '#6f5a4f'
  on-secondary: '#ffffff'
  secondary-container: '#f7dacc'
  on-secondary-container: '#745e53'
  tertiary: '#0e1b00'
  on-tertiary: '#ffffff'
  tertiary-container: '#1e3100'
  on-tertiary-container: '#6ca200'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d0e9d4'
  primary-fixed-dim: '#b4cdb8'
  on-primary-fixed: '#0b2013'
  on-primary-fixed-variant: '#364c3c'
  secondary-fixed: '#faddce'
  secondary-fixed-dim: '#ddc1b3'
  on-secondary-fixed: '#271810'
  on-secondary-fixed-variant: '#564338'
  tertiary-fixed: '#b2f746'
  tertiary-fixed-dim: '#98da27'
  on-tertiary-fixed: '#121f00'
  on-tertiary-fixed-variant: '#334f00'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  h1:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.25'
    letterSpacing: -0.01em
  h3:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: '0'
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  data-tabular:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 24px
  lg: 48px
  xl: 64px
  gutter: 24px
  margin: 32px
---

## Brand & Style

This design system is built for the intersection of agriculture and high-end technology. It prioritizes reliability, precision, and environmental stewardship. The aesthetic is categorized as **Corporate / Modern**, utilizing a structured, data-first approach that ensures complex land management tasks feel manageable and trustworthy.

The visual language balances the organic nature of rural land with the crispness of modern software. It targets agricultural professionals and land managers who require a high-utility interface that remains legible under various field conditions. The emotional response is one of stability and professional growth, moving away from "rustic" tropes toward a sophisticated, tech-forward agricultural future.

## Colors

The palette is rooted in the natural environment but refined for digital clarity. 

- **Primary (Deep Forest Green):** Used for navigation, primary headers, and foundational brand elements to establish authority.
- **Secondary (Fertile Earth Brown):** Utilized for structural accents, subtle borders, and grounding elements.
- **Accent (Bright Lime Green):** Reserved exclusively for high-priority Call to Actions (CTAs), active states, and successful progress indicators. It provides a sharp contrast against the deep greens.
- **Neutrals:** A range of clean whites and cool grays ensure the interface feels breathable. 
- **System States:** High-saturation reds and ambers are used for alerts and maintenance statuses to ensure they are not lost against the earthy primary palette.

## Typography

Inter was selected for its exceptional legibility in data-heavy environments. The typographic scale emphasizes a clear hierarchy between high-level land metrics and granular data points. 

For data tables and input fields, the "Data Tabular" weight is preferred to maintain vertical alignment and readability. Labels use a slightly higher tracking and uppercase styling to differentiate them from user-generated content and land coordinates. High-contrast headlines in Deep Forest Green ensure a sense of place and structure on every page.

## Layout & Spacing

The design system employs a **Fluid Grid** model based on a 12-column system. This allows the application to transition seamlessly from desktop management views to tablet use in the field. 

A strict 8px baseline grid governs the rhythm of the UI. Margins are generous (32px) to prevent the interface from feeling cluttered, while gutters (24px) provide enough breathing room between cards to keep data sets distinct. For complex data tables, a tighter internal padding of 12px (sm) is used to maximize information density without sacrificing touch targets.

## Elevation & Depth

This design system uses **Tonal Layers** combined with **Ambient Shadows** to create a structured hierarchy. The primary canvas is a light neutral, with cards sitting at a low elevation to signify they are the primary interaction containers.

Shadows are soft, using a slight Deep Forest Green tint rather than pure black to keep the interface feeling organic. 
- **Level 0:** Background canvas.
- **Level 1 (Cards):** 0px 4px 12px rgba(27, 48, 34, 0.05).
- **Level 2 (Dropdowns/Modals):** 0px 8px 24px rgba(27, 48, 34, 0.10).
- **Level 3 (Active CTAs):** Subtle Lime Green glow (0px 0px 8px rgba(163, 230, 53, 0.4)).

## Shapes

The shape language is **Rounded**, reflecting a balance between the precision of technology and the organic forms found in agriculture. 

Standard components (Inputs, Buttons, Cards) utilize a 0.5rem (8px) corner radius. Status badges and small utility tags use a "Pill" style (full rounding) to clearly distinguish them from interactive buttons. This approach ensures that the UI feels approachable and modern while maintaining enough structural integrity to appear professional and secure.

## Components

### Buttons & CTAs
Primary buttons use the Bright Lime Green accent with black or Deep Forest Green text for maximum legibility. Secondary buttons are outlined in Fertile Earth Brown.

### Cards
Cards are the primary structural unit. They must feature a 1px border in a light neutral-gray to define boundaries against the white background, supported by Level 1 elevation.

### Status Badges
- **Active:** Bright Lime Green background with dark green text.
- **Pending:** Soft amber background with dark brown text.
- **Maintenance:** Earth Brown background with white text.

### Data Tables
Tables use a "Clean Data" approach: no vertical lines, only subtle horizontal dividers in light gray. Headers are styled using the `label-sm` typographic token with a subtle background tint of Deep Forest Green at 5% opacity.

### Map Integration
Placeholders for maps should utilize a dark-mode styling with Forest Green and Earth Brown highlights to ensure the map UI feels integrated into the application's core aesthetic.

### Input Fields
Inputs are defined by high-contrast borders (1px) that darken on focus. Error states must use a clear, readable red that does not vibrate against the green primary tones.