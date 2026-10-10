# Trading terminal

User direction: dark, compact trading terminal; charcoal surfaces, clear numbers, minimal animation.

The primary task is checking market freshness, choosing isolated exposure, and managing a
paper position. The market chart and order ticket share a workspace; active positions stay
immediately below. History and journal use dedicated views, not a collection of dashboard cards.

Design read: a quiet, technical workspace. Typography and aligned prices carry the identity.
Charcoal is the working surface; amber identifies selection and primary actions. Green and
red indicate trading direction and PnL, always paired with labels or signs.

ENERGY 2 / RHYTHM 2 / MOTION 1. High information density, stable rows, no perpetual animation.
Numeric changes never animate position or width. Transitions are short focus/hover feedback
and disabled when reduced motion is requested. The user's compact terminal direction overrides
decorative layout and animation defaults.

Use a locally bundled sans-serif font and tabular/monospaced financial figures. Small radii
separate controls from flat work surfaces. Avoid gradients, marketing copy, large hero text,
glow, floating panels, invented performance numbers, and unrelated imagery.

Desktop: market workspace beside a 320px order ticket. Tablet: narrower two-column layout
until fields no longer fit. Mobile: deliberate chart/ticket stack, full-width position rows,
and compact labelled navigation. No viewport-wide horizontal overflow. Keyboard focus, status
messages, empty states, chart text alternatives, and visible disabled reasons are required.

## Approved sharing and entry exceptions

The terminal layout stays unchanged. User-requested meme imagery is confined to explicit
PnL sharing and the optional confirmed-fill splash. Built-in artwork is original Canvas
frog illustration, not copied Pepe assets. Local user images may replace it by category.

The 1200×675 export uses an asymmetric result/art split, large signed ROE, and the existing
Geist/charcoal palette. Green, red and neutral grey reflect the numeric PnL; signs and labels
also communicate the result. Pair, direction, leverage and entry/end prices stay visible.
Paper/simulated labelling is mandatory. USDT amount is hidden until explicitly enabled.

The entry splash lasts 1.6 seconds and only follows a confirmed paper fill. One 220ms
transform/opacity entrance is permitted; no continuous motion. Esc, click or its dismiss
button closes it. Native modal focus/inert behavior prevents click-through. Reduced-motion
removes spatial animation, including animation from user GIFs by rasterizing a still frame.
An Entry splash checkbox persists only the on/off preference, never authentication data.

Share dialogs reflow on mobile; the exported image keeps its landscape dimensions. Native
sharing and image clipboard controls depend on browser support; PNG download is the fallback.