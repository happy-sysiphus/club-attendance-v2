# Design assets

- `glee-logo-2024.jpg`: user-provided Glee logo, copied without altering the image. Kept as the original source; no longer referenced by the app (the SVG below replaced it on screen and as the icon).
- `glee-logo.svg`: user-provided transparent vector of the same logo (2026-09-09). Tab icon for browsers that accept SVG favicons.
- `glee-icon.png`: `glee-logo.svg` rasterized onto a white 1024x1024 canvas (logo width 86%, shifted 3% above center). iOS ignores SVG and paints transparency black, so the home-screen icon needs this opaque PNG. Regenerate instead of editing by hand.
- `attendance.svg`: Figma `contact_emergency`, outlined variant (`51:51972`).
- `calendar.svg`: Figma `calendar_today`, outlined variant (`51:55562`).
- `chevron-left.svg`: Figma top navigation back icon (`2:484`), exported from example screen `61:857`.

Icons are the exact exported asset bytes, stored locally so the app does not depend on expiring Figma asset URLs.

Reference: [Mobile App Wireframing UI Kit](https://www.figma.com/design/PKRK48SNAbpDVTQOrCzWEj/Mobile-App-Wireframing-UI-Kit--Community-?node-id=0-1).

UI references: segmented tabs `36:3849`, title/subtitle list `36:3825`, text field `35:3758`, primary button `35:3798`, example screen `61:857`. Adapted to the existing HTML/CSS/JavaScript app, with Korean text and attendance-specific states.
