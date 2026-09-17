# Navivi Features

- **Interactive 3D Map Routing:** Build paths using driving, walking, direct line, spline curves, or ferry pathfinding. Powered by Mapbox and OpenRouteService.
- **Smart GPX & EXIF Photo Import:** Drop GPX files or photos directly onto the map to extract timestamps, reverse-geocode stops, and auto-plot your entire road trip.
- **Floating CAD-Style Workspace:** A highly fluid, responsive workspace featuring a decoupled Waypoint Editor and a Unified Layers Panel for a clean, non-obstructive map viewing experience.
- **Granular Styling & Route Heatmaps:** Per-segment control over line colors, custom map markers, curve offsets, and drawing styles. Includes dynamic **Gradient Heatmaps** to visualize uphill/downhill slope intensity.
- **Historical Weather Sync (Experimental):** Integrates with the Open-Meteo API to extract dates from EXIF photos and automatically render contextual weather overlays (fog, rain, clear skies) on the map during video generation.
- **AI Storytelling & Media Pipeline:**
  - Generate location scripts locally using **Ollama**.
  - Synthesize realistic voiceovers using **Irodori TTS**.
  - Render stunning pop-up videos using **ComfyUI (Wan 2.2)**.
- **Advanced Non-Linear Timeline:**
  - Fine-tune your generated video, adjust subtitles, video tracks, and map markers seamlessly.
  - **Multi-Track Audio with Auto-Ducking:** Import background music (BGM) tracks that automatically attenuate in volume when voiceovers are playing.
- **Social Media Export Presets:** Pre-configured bitrate and resolution profiles for Desktop/YouTube (16:9) and Shorts/TikTok/Reels (9:16 vertical crop).
- **Universal Asset Manifest Pipeline:** A clean JSON bridging system that passes rich mapping and narration metadata from the React frontend directly to the Python video engine.
