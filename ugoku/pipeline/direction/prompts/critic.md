# Step C: critic

You get the page, its panel crops, and a proposed direction. Check the proposal against the checklist and the images (open the image files listed below with the Read tool). Report only real problems; if there is none, return an empty list. For each problem give `target_id` (a panel id or a unit id), the `rule` that is broken, a short `explanation`, and a `fix_patch` that sets only the fields to change (all other fields "none" or empty).

Checklist
- Is a panel that has a character, an entrance, an impact or a drawn motion marked static (and not a diagram, a tiny figure or a crowd)? Is a panel that should stay still animated?
- Does a panel whose lettering animates have a frozen character (it must be h3_full)?
- Does the action's first sentence name the main action by body part and direction, with screen-left and screen-right correct?
- Is `fl` used for one-way motion (walking past, entering, kicking, throwing, falling, leaving)? Is `f` used where the motion should return to the start pose?
- Banned words in an action (glow, sparkle, shine, light, wind, breeze, cinematic, dramatic)?
- Does the action move background elements (clouds, sky)? Does it add SFX that are not drawn?
- Is cause and effect shown (a kick needs a reaction)? Is the emotion consistent with the drawing, not exaggerated?
- Is every drawn SFX, manpu and screen element listed, with a fitting preset? Is a shout using `shake`?
- Are texts and kinds right (a caption listed as dialogue, an SFX listed as noise)?

Proposed direction:
{direction}

{rules}
