# Frontend / GUI Design Guidelines

Practical guidance for intentional visual design when building a new UI or reshaping an existing one. Design deliberately: make opinionated choices about palette, typography, and layout that fit the specific project rather than reading as templated defaults.

## Ground the design in the subject matter

Identify the product, its audience, and its primary job before designing. The subject's industry, materials, and vernacular are where distinctive visual choices come from. Build with the real content throughout.

## Design principles

- **Open with the most characteristic thing** in the subject's world (headline, image, animation, or interactive moment). A big number with a small label and a gradient accent is the default treatment — use it only if it is truly the best option.
- **Typography carries personality.** Use one family or two; if two, make them clearly distinct. Choose typefaces deliberately (not defaults), set a clear type scale, and use type treatments as an active part of the design.
- **Keep line lengths under 80 characters.** Serif body text gets slightly more line-height than sans-serif.
- **Avoid default tells:** accenting a single word in a headline, all-caps labels, and unnecessary typographic labels above content.
- **Visual structure is information.** Outlines, borders, numbering, and dividers should encode meaning, not decorate. Only number items when the content really is a sequence (steps, timeline).
- **Use non-user-triggered motion sparingly.** One orchestrated moment lands better than scattered effects. Motion that answers a user action (opening, expanding, confirming) is welcome when it shows what changed.

## Process: plan, review, build, critique

Typical AI-generated design clusters around these defaults — recognize them so you can choose instead of defaulting:
1. warm cream background (#F4F1EA) with high-contrast serif and a terracotta accent (near #D97757);
2. near-black background with one bright acid-green or vermilion accent;
3. broadsheet layout: hairline rules, zero border-radius, dense newspaper columns;
4. the SaaS-card kit: identical rounded cards, one border-radius everywhere, soft grey shadow (rgba(0,0,0,.1)), gradient washes as decoration;
5. template chrome: ALL-CAPS eyebrows, meta strings joined with '·', 'WORD — fragment' labels, tinted near-black (#0B0B0B/#111), monospace for small data labels, a '→' appended to links.

Follow the brief's explicit direction exactly; where it leaves an axis free, don't spend that freedom on a default.

Work in two passes:
1. **Brainstorm** a compact design plan — a token system with color (4–6 named hex values), type roles, a layout concept (sentence prose + ASCII wireframes, including alignment: left / center / justified), and high-level principles.
2. **Review against the brief** before building. If any part reads like the generic default for a similar page, revise it and note what changed and why.

When writing code, watch CSS selector specificity — type-based selectors (e.g. .section) and element selectors (e.g. .cta) can cancel each other out, often on padding/margin between sections.

## Restraint and self-critique

Spend your boldness in one place: make one element memorable and keep everything around it quiet. Cut decoration that doesn't serve the brief. Build to a quality floor without announcing it: responsive to mobile, visible keyboard focus, reduced motion respected, accessible, harmonious palette. Critique your own work as you build (take screenshots if possible). Before finishing, remove one accessory.

## Principles for interface writing

Words are design content, not decoration. Write from the end user's perspective, name things in plain language, use active voice, and keep a CTA's name consistent through the whole flow ("Publish" → "Published"). Treat failure and emptiness as direction, not mood: explain what went wrong and how to fix it. Keep tone conversational — plain verbs, sentence case, no filler.
