Create one horizontal animation strip for Codex pet `combo-lead`, state `running-right`.

Use the attached canonical base for identity. Use the attached layout guide only for slot count, spacing, centering, and padding; do not draw the guide.

Output exactly 8 full-body frames in one left-to-right row on flat pure user-selected #00FF00. Treat the row as 8 invisible equal-width slots: one centered complete pose per slot, evenly spaced, with no overlap, clipping, empty slots, labels, or borders.

Identity: same pet in every frame: Only the single large rounded black eighth-note character from the reference. It has two vertical white oval eyes, two short legs, and one separate curved black accent stroke behind its left side. Do not include the small companion.. Preserve silhouette, face, proportions, markings, palette, material, style, and props.
Anatomy lock: only the note body and stem, two white oval eyes, two short legs, and the existing curved accent stroke. No hands, arms, paws, wings, ears, mouth, tools, props, or other new anatomy.
Style: Pet-safe sprite: compact full-body mascot, readable in a 192x208 cell, clear silhouette, simple face, stable palette/materials, and crisp edges for chroma-key extraction. Style `flat-vector`: Flat vector-style mascot with simple geometric forms, crisp color areas, clean outline, and minimal shading. User style notes: Minimal monochrome raster art with crisp antialiased edges; no signal color, shadows, decorative effects, text, or companion character..
Animation continuity: keep apparent pet scale and baseline stable within the row unless the state itself intentionally changes vertical position, such as `jumping`. Move the pose within the slot instead of redrawing the pet larger or smaller frame to frame.

State action: Dragging-right loop: show directional movement to the right through body and limb poses only.

State requirements:
- Show rightward running only through alternating short-leg stride, slight forward body lean, restrained body compression, and subtle stem/accent follow-through.
- The row must unmistakably face and travel right.
- The movement cadence must alternate visibly across the 8 frames instead of repeating one nearly static stride.
- Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.

Clean extraction: crisp opaque edges, safe padding, no scenery, text, guide marks, checkerboard, shadows, glows, motion blur, speed lines, dust, detached effects, stray pixels, or chroma-key colors inside the pet.
