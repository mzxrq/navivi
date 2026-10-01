# Navivi Features

## Planning

- **3D map routing.** Each leg between two stops is driven, walked, taken by ferry, drawn by hand, a straight line, or a flying curve. Mapbox draws the map; OpenRouteService and OSRM find the roads.
- **Per-leg line colour.** Every leg can have its own colour; the rendered video uses it too. Legs without one use the project's route colour.
- **GPS import.** GPX, FIT, TCX and KML tracks. Stops are the file's named waypoints (plus the start and end of the track), and each leg follows the recorded points instead of being routed again. Photos with location data can be dropped onto the map to plot their places.
- **Stops, stop-bys and your own markers.** Reorder stops, mark places the route only passes by, and give the route or any stop a custom marker.
- **Rich context menus** on stops, legs, via points and the map, plus undo and redo.

## Telling the story

- **Scripts per stop**, with separate text for the trip to the stop and for what you see there. A local Ollama model can draft them, using only the facts it is given, your request, the photo and the neighbouring stops.
- **Voices.** Pick a narration voice, clone one from a short recording, set the speed and preview it.
- **Pronunciation dictionary**, per project and shared by every project, with a scan that finds whole words (verbs with their endings, place names) and fills in readings. Typing `漢字(よみがな)` in a script adds an entry.
- **Photos and your own videos** at each stop. Photos can be animated (ComfyUI with Wan 2.2, or a built-in pan and zoom); videos replace the animated clip, fitted to the narration, with their own sound off unless you turn it on.
- **Render estimate** that learns from your earlier renders on this computer.

## Editing and sharing

- **Timeline editor.** Clips in a sequence with their narration. Drag to reorder, drag the edges to trim, shift the narration, fade between clips, mute or adjust volume.
- **Subtitles** from the narration, from an SRT file (with or without timestamps), or typed by hand; burn them into the video at export.
- **Background music** from a folder of your own tracks (with optional titles, tags and credits).
- **Auto edit** puts the clips in order and fills in fades and subtitles in one click.
- **Export.** One video with narration, music and subtitles; **Export for sharing** makes a lean `.nvv` project file for another person.
- **Version history** for each project, kept in the app's database.
