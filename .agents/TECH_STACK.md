# Navivi Tech Stack & Libraries

## Core Frameworks
- React 19
- TypeScript
- Vite
- Tailwind CSS v4
- Tauri v2 (Desktop API bindings)

## Map & Routing
- react-map-gl (v8.1.2)
- mapbox-gl (v3.29.0)
- @turf/* (bezier-spline, buffer, helpers, length, simplify)
- *NOTE: @mapbox/mapbox-gl-draw is listed in package.json but we have EXPLICITLY REMOVED it from the project in favor of native DOM markers for anchors.*

## UI & Components
- react-rnd (v10.5.3) - Used for draggable/resizable windows (like WaypointEditor and Layers)
- lucide-react (v1.28.0) - Re-exported via src/components/ui/icons.ts
- tailwindcss-animate (v1.0.7) - Used for Tailwind CSS animations (WARNING: Do NOT use animate-in classes on react-rnd components, as the transform CSS conflicts with rnd positioning).

## Media & Rendering
- konva / react-konva (v10.3 / v19.2) - Used for Timeline/Video editing
- exifr (v7.1.3) - Exif data reading
