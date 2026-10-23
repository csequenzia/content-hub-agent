---
name: edit-course-lesson
description: Edit a raw course or lesson recording into a clean teaching video. The camera opens full screen with a title, then shrinks to a rounded crop beside big bullet-point takeaways, section cards, and simple AI-generated image aids (Higgsfield) on a minimal background. Use when asked to edit a course video, lesson, module, tutorial, training video, or "course-style" edit, or for Nate Herk's course-style prompt. Runs local Whisper, silence and mistake cuts, a reviewed lesson plan, then a verified HyperFrames render.
---

# Edit a course lesson

One lesson = one project in `video-projects/<slug>/`. The look is fixed by the
template so every lesson in a course matches; the plan changes per lesson.

- **Camera**: full screen with a title card, then a rounded crop on the right.
  It can return to full screen for a personal moment, then go back.
- **Brand**: Healthy Free Life (brand guide v1.0): mist ground, Newsreader
  headlines in olive deep, DM Sans text, sage labels, pomegranate section numbers,
  white logotype on the title card and a small HFL monogram while the camera is boxed.
  Source of truth: `~/Downloads/brand-kit/BRAND.md`.
- **Takeaways**: big, short bullet points, each revealed as it is spoken.
- **Visual aids**: simple AI images from Higgsfield with light motion.

All layout and animation comes from `scripts/build-lesson.mjs`, which turns
`lesson-plan.json` into `index.html`. Edit the plan, not the HTML.

## Steps

1. **Set up.** `npm run new-video -- <slug>` from the kit root. Copy the recording
   to `video-projects/<slug>/assets/raw.mp4` (keep the original untouched). Probe it
   with ffprobe and grab a frame to find where the face sits.
   If the user has a course theme from an earlier lesson, copy that project's
   `lesson-theme.css` into the new project so lessons match.

   **Slide deck?** If the lesson was taught from slides, run
   `node .claude/skills/edit-course-lesson/scripts/deck.mjs video-projects/<slug> <deck.pdf>`
   (export PowerPoint/Keynote/Google Slides to PDF first). It writes `deck/slide-NN.png`
   and `deck/slides.md`. The slides are source material, not the visuals: titles and
   bullets become takeaways (use the deck's wording for terms Whisper may mishear),
   "Part One"-style slides become section cards, and diagram regions become image aids
   with a beat's `"slide": N, "slideCrop": [x, y, w, h]`. Look at every crop before
   rendering; widen any that clip a label.
   **Long live sessions (Ecamm, Zoom):** the program recording (the file that shows the
   screen share) tells you exactly when each slide was up. Detect screen changes with
   `ffmpeg -ss <from> -i <program.mov> -an -vf "fps=2,scale=320:-1,select='gt(scene,0.12)',showinfo" -f null -`
   and grab a frame after each change to map times to slides. Use it to find the
   teaching window (skip arrival chat, tech fixes, Q&A unless asked), then cut the camera
   file to that window. Ecamm's camera file already carries the main mic in sync.

2. **Transcribe** locally: `node scripts/transcribe-whisper.mjs video-projects/<slug>/assets/raw.mp4`.
   Use `--model medium.en` if the audio is hard to hear or has jargon.

3. **Cut silences** (read `../cut-silences/SKILL.md`), writing `silenced.mp4` and
   `raw.silence-transcript.json`. Teaching needs breathing room: keep the default
   gap settings unless the user asks for a tighter pace.

4. **Cut mistakes** (read `../cut-mistakes/SKILL.md`) on the silenced files. Show
   the user the proposed cuts with context before applying. With no approved cuts,
   keep `silenced.mp4`. Copy the transcript that matches the final video to
   `assets/transcript.json`. Never pair a transcript with a different cut.

5. **Plan the lesson.** Read the whole transcript, then write `lesson-plan.json`
   (format: `references/lesson-plan.md`). Rules:
   - Open with a `title` beat while the camera is full screen; shrink the camera
     to `box` as the teaching starts.
   - One idea per beat. Headings under 48 characters, at most 4 points, each point
     under 42 characters. Paraphrase into takeaways; never transcribe sentences.
   - Anchor every beat and point to the exact spoken phrase (`startAnchor`,
     `atAnchor`) so it lands as it is said. Copy phrases from the transcript.
   - Use a `section` beat at each new chapter of the lesson, and end with a recap
     `takeaway` if the lesson summarizes itself.
   - Give roughly one image aid per 45-60 seconds, only where a picture explains
     the idea better than words. Add `imagePrompt` describing the concept, and set
     `imageStyle` once at the top of the plan so every image matches. Brand default:
     "Clean minimal flat illustration on a plain white background, olive deep
     (#2A4020) line work, sage (#84A05F) and pale sage (#DCE5C8) fills, one small
     pomegranate (#D13C5B) accent, calm and fresh like a bright morning, lots of
     white space, no text, no letters, no logos". Never fitness-model or
     before/after imagery, and no emojis anywhere (brand rules).
   - Put the camera back to `full` for personal stories or direct appeals; the
     builder trims beats around camera changes automatically.
   - Give every long beat an `endAnchor`; without one it ends after `maxHold` (16s).
   - Cut on-camera tech trouble ("can you see my slides?") and asides to the live
     audience ("if you have questions let me know") as editorial cuts in step 4.
     Re-read the stutter candidates: repeating a word across a sentence break
     ("not all carbohydrates. Carbohydrates also...") is not a stutter.
   - Whisper's timings drift inside long stretches of speech, so an editorial cut can
     leave a stray word ("...let me know") or clip one ("basically it" -> "been").
     Before applying, transcribe a 10-second window around each editorial cut's edges
     from `silenced.mp4` and set start/end from those times. After rendering, transcribe
     a window across every editorial join in `clean.mp4` and read it as a sentence.
   Run `node .claude/skills/edit-course-lesson/scripts/build-lesson.mjs video-projects/<slug> --check`
   and fix every error. Show the user the timing table it prints before spending
   credits, unless they already approved the plan.

6. **Generate images with Higgsfield.** `build-lesson.mjs <project> --images`
   lists missing images. Use the Higgsfield MCP tools:
   - Model `gpt_image_2_5`, `quality: "medium"`, `use_unlim: false`. Use aspect
     `3:4` for a takeaway with an image (split layout) and `4:3` for an `image` beat.
   - Prompt = `imagePrompt` + ". Style: " + `imageStyle`.
   - Check `balance` and preflight one image with `get_cost: true`. Tell the user
     the total (count x cost) and get approval unless they already approved image
     spend for this lesson. Then submit all at once with `generate_image_batch`,
     wait with `jobs_wait`, and show them with one `show_generation_by_ids` call.
   - Download each result URL with curl to the plan's `image` path, and look at
     every image before using it. Regenerate any with text, extra limbs, or clutter.

7. **Build and check.** Run the builder without flags, then from the project run
   `npx hyperframes lint` and `node ../../scripts/preflight.mjs .`. Fix all errors.

8. **Render and verify.** For long lessons, check layout first with
   `npx hyperframes snapshot . --no-end --describe false --at <one time per beat>` and
   read the contact sheets; fix before the full render. Then `npx hyperframes render --quality draft --output renders/draft.mp4`.
   Extract frames at the title, each camera change, and one frame per beat (use the
   times in `lesson-timing.md`). Check: face not cut off in the rounded crop (adjust
   `camera.focusX/focusY/zoom`), no text overlapping the camera box, text fits, images
   look right, no black frames. Listen at a few cut points for A/V sync. Fix, rebuild,
   re-render. Write what was checked to `VERIFY.md`.

9. **Final.** When the user approves the draft:
   `npx hyperframes render --output renders/final.mp4`. Deliver its path, the
   applied cuts, and `lesson-timing.md`. Do not upload or publish unless asked.

## Changing the look

Colors, fonts, and spacing live in the project's `lesson-theme.css`; logos and
bundled fonts live in its `brand/` folder. Both are copied from `template/` on the
first build and never overwritten. Headlines stay sentence case (the brand never
uses all-caps or bold Newsreader). For a product course, set `"product"` in the
plan: `glorious-way` (pomegranate lead, ivory ground), `temple-restored` (burgundy),
or `food-revival` (sage). Variants live in `template/brand/products/` and only swap
the lead color; headlines, fonts, and logos stay Healthy Free Life. The Glorious Way
logo is still in progress (Sept 2026), so its lessons use the HFL logos for now.
For a course-wide default,
edit the template itself. Camera box
size and position are in the plan's `camera.box`; if you change its width, update
`--content-width` in the theme so text stays clear of the camera.
