## Direction rules (shared by all steps)

Panels
- Animate every panel that motion would improve. Use `h3_full` (the whole panel is replaced by a generated video of about 5 s) for: a character action (walking, passing by, playing an instrument, swinging, running, turning), an entrance or an arrival (a monster or a person appearing), an impact, a change of expression, and any motion that is drawn (speed lines, a swing arc, a falling object).
- Use `static` for: explanation, diagrams or text-only panels, figures that are tiny, crowds, and panels where stillness is the effect. Say why in `reason`.
- Never let lettering move while the character is frozen. A panel whose balloons or SFX animate must be `h3_full` (the character moves) unless it has no character at all (a screen, a landscape, lettering only).
- Do not animate background elements (clouds, sky, distant scenery).
- Show cause and effect inside one panel: if one figure attacks, the other figure reacts.

The `action` text (h3_full only)
- English, 1 to 3 sentences. The first sentence is the main action, written by body part and direction, with left and right as seen on the screen. Example shape: "The man on the left raises his right arm and brings it down in a fast arc."
- Describe only what moves inside the panel. Do not describe camera moves, lighting, or style.
- Banned words: glow, sparkle, shine, light, wind, breeze, cinematic, dramatic.
- The video is 5 s long and its last frame is pinned to the first. Two modes:
  - `fl` (first and last frame fixed): the motion must go out and come back to the start pose (shake, nod, swing and return, a hand that plays and settles). Write it as "starts nearly still, moves, returns to the starting pose".
  - `f` (first frame fixed only): one-way motion that must not be reversed: walking past, an entrance, a kick, a throw, a fall, a departure. Never use `fl` for these; a walk that returns looks like walking backwards.
- `magnitude`: `medium` or `large`. Prefer a motion that is clearly visible at a glance (upper body, whole arm, whole body). Facial changes alone are `medium`.
- Read the emotion from the drawing and the lines. Do not overdo expressions. `emotion_source` says which line or drawn detail you took the emotion from.

Lettering and effects
- Every drawn SFX, manpu (sweat drops, tears, anger marks, sparkles, speed lines, blue lines of shock) and on-screen element must be listed once. Do not add SFX that are not drawn.
- Dialogue and narration units appear one by one in reading order (`anim`: `pop` for ordinary speech, `fade` for narration and quiet text, `shake` for shouts, `slide` rarely).
- SFX and manpu get a motion `preset`:
  - impact, jolt: hits and shocks; tremble: fear, anger, a growl; pulse, repeat_pop, rhythm: beats and heartbeats; sway: swaying; creep: slow approach; slide, drop: entering from a side or from above; tick: a clock-like step; drip: sweat or tears; pop: a sudden appearance; stretch, line_stretch: speed lines and blue lines; sparkle_blink: drawn sparkles; flicker: flickering; mail_slide: a notification or a card sliding in from above (kind screen only).
