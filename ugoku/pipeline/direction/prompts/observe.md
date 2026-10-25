# Step A: observe

You get one manga page as images: the clean page, an overlay, and one labelled crop per panel. The overlay has coloured boxes: thick outlines labelled P1, P2... are candidate panels in the code-computed reading order; thin boxes labelled U1, U2... are candidate text units (blue: balloon, green: free text, red: SFX candidate). A ruler along the border of the overlay shows page fractions (0 to 1) on both axes. Open every image file listed below with the Read tool before answering, and look at the panel crops closely.

Reading direction of this work: {reading}.

Candidate panels (normalized x, y, w, h): {panel_list}
Candidate units: {unit_list}

Tasks
1. `panel_fixes`: check the panel candidates against the page. Reply with one entry per decision.
   - `confirm` (ids = the panels that are right; one entry may list many ids),
   - `not_panel` (ids): the box is not a panel (a balloon, lettering, a decoration),
   - `merge` (ids): several candidates are really one panel,
   - `split` (ids = one candidate, `axis` = "x" for a vertical cut line or "y" for a horizontal one, `approx_pos` = the cut position as a page fraction): one candidate holds two panels,
   - `add` (`approx_rect` = [x, y, w, h] page fractions): a panel that no candidate covers. Borderless and full-bleed panels count; each panel is one scene.
   Code will snap your positions to the nearest drawn edge. Every panel candidate must appear in exactly one entry (confirm, not_panel, merge, split). An inset drawn over a larger panel (a small framed scene) is its own panel: `add` it, with its own frame as the rect.
2. `panels`: describe each FINAL panel: confirmed ids, the first id of a merged group, the two halves of a split as `<id>a` and `<id>b`, and added panels as `N1`, `N2`... For each: `content` (what is drawn, one sentence), `who` (who is in it, no names needed), `face_size` (none, tiny, small, medium, large), `expression`, `drawn_motion` (motion that is drawn: speed lines, arcs, falling objects), `emotion`, `no_character` (true when no character is in the panel).
3. `units`: for each candidate unit U#, give `kind`: dialogue (speech or thought), narration (caption box), sfx (drawn sound effect lettering), manpu (a non-text symbol), screen (text on a device screen), noise (not text, screentone, a false detection). Also `text` (a transcription of the text, empty for non-text), `panel_id` (the final panel it belongs to, by the tail position if the balloon crosses panels), and `shout` (true when it is a shouted line: bold, jagged balloon, exclamations).
4. `add_units`: SFX, manpu or on-screen elements that are drawn but not covered by any unit candidate. `approx_rect` as page fractions. Do not add anything that is not drawn.
5. `page_story`: one or two sentences about the flow of the page. `must`: leave empty unless something on the page needs special handling (give `item` and `how`).

{rules}
