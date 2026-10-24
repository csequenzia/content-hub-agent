# Edit recipes

One file per reference reel, named after its Content Studio template id (`R09.json` is
Maria Wendt's "The Big Reveal"). When Content Studio sends a filmed card, it passes the
card's template id as `template`, and the agent edits the footage to look like that reel:
its hook style, caption style, camera cuts, pace and length. Videos with no template, or a
template with no recipe yet, get the house style.

The fields are documented at the top of `hub/recipes.py`. `edit_notes` is read by Claude,
so write it in plain words: the beats to keep, where the camera changes, what to emphasise.
Everything else is read by the renderer.

## How the recipes were made

Each one comes from watching Maria's original (downloaded copies live on Chris's Mac in
`~/Maria Scrape 6-13-26/`): frame sheets for timing, close frames for the text look.
Positions (`y`) are fractions of the 1080x1920 frame. `shots` are fractions of the Reel's
length; Claude moves them onto the right sentences. Zoom 1.0 is the full phone frame,
1.4-1.55 is "tight on the face", which stands in for Maria's second camera.

## Done

R02, R04, R09, R13, R22, R25, R29, R38, R47, R48 (the talking-head templates whose
originals were on hand).

## Still to do

R03, R05, R11, R12, R14, R15, R20, R23, R30, R31, R32, R42, R46: their originals need
downloading first. Until then they use the house style.
