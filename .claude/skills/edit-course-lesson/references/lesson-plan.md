# lesson-plan.json

One file per lesson project, read by `scripts/build-lesson.mjs`. All paths are
relative to the project folder. Times are seconds on the final (cut) video.

```json
{
  "title": "Lesson 5.1: When and How to Pitch an Audit",
  "video": "assets/silenced.mp4",
  "transcript": "assets/transcript.json",
  "imageStyle": "Minimal flat editorial illustration on a plain warm off-white background (#f5f3ee), one blue accent (#2d5bff), charcoal line work, lots of empty space, no text",
  "camera": {
    "focusX": 0.5, "focusY": 0.4, "zoom": 1,
    "events": [
      { "at": 0, "mode": "full" },
      { "atAnchor": "At some point", "mode": "box" }
    ]
  },
  "beats": [
    { "id": "title", "type": "title", "start": 0.1, "endAnchor": "an audit",
      "kicker": "Lesson 5.1", "title": "When and how to pitch an audit" },
    { "id": "notice", "type": "takeaway", "startAnchor": "At some point",
      "label": "Mid-project", "heading": "You'll spot bigger problems",
      "points": [{ "text": "Inefficiencies", "atAnchor": "inefficiencies" }] }
  ]
}
```

## Top level

| Field | Required | Meaning |
| --- | --- | --- |
| `video` | yes | The final cut video. Its audio is the lesson audio. |
| `transcript` | for anchors | Word transcript that matches `video` exactly (post-cut). |
| `title` | no | Page title and timing report heading. |
| `product` | no | Product color variant: `glorious-way` (pomegranate), `temple-restored` (burgundy), `food-revival` (sage). Omit for Healthy Free Life. |
| `imageStyle` | no | Appended to every `imagePrompt` so images match. |
| `duration` | no | Override; defaults to ffprobe duration. |
| `anchorLead` | no | Seconds an anchored item enters before its word (default 0.15). |
| `maxHold` | no | Longest a beat stays up without an explicit end (default 16). |

## Camera

| Field | Default | Meaning |
| --- | --- | --- |
| `focusX`, `focusY` | 0.5, 0.42 | Where the face is in the source frame (0-1). The box crop centers here. |
| `zoom` | 1 | >1 crops tighter in the box. |
| `box` | `{ "w": 620, "h": 820, "right": 72, "radius": 40 }` | Box size and position. Vertically centered unless `top` is set. |
| `transition` | 0.9 | Seconds for a full/box move. |
| `events` | `[{ at: 0, mode: "full" }]` | Mode changes: `"full"` or `"box"`, each with `at` or `atAnchor`. |

## Beats

Every beat has `id`, `type`, and `start` or `startAnchor`. `end` / `endAnchor` is
optional; otherwise a beat runs until the next beat (or `maxHold`). The builder
also ends a beat when the camera leaves its mode (titles at the next `box`,
content at the next `full`) and holds content until a camera move has settled.

| Type | Fields | Look |
| --- | --- | --- |
| `title` | `kicker`, `title`, `subtitle` | Lower-left over the full-screen camera. |
| `section` | `number`, `heading`, `subtitle` | Big accent number and chapter name. |
| `takeaway` | `label`, `heading`, `points[]`, optional `image` + `imagePrompt` | Heading plus bullets. With an image: text left, 3:4 image right. |
| `image` | `heading`, `image`, `imagePrompt`, `caption` | Large 4:3 image with a slow push-in. |

Any takeaway or image beat can use a region of the lesson's own deck instead of an
`image` file: `"slide": 7, "slideCrop": [x, y, w, h]` (fractions of the slide, from
`deck/slide-07.png`, made by `scripts/deck.mjs`). The crop is written to `assets/aids/`,
keeps its real shape, and does not zoom. Wide crops (wider than about 1.45:1) stack
under the takeaway's points instead of sitting beside them.

A point is a string or `{ "text", "at" | "atAnchor" }`. Anchored points appear as
the phrase is spoken; unanchored ones stagger in after the heading.

Anchors match whole words, ignore case and punctuation, and search forward from
the previous beat, so a repeated phrase resolves to its next occurrence. Copy the
phrase from the transcript; Whisper spellings (numbers, names) must match.

## Output

- `index.html`: the composition (regenerated each build; do not hand-edit).
- `lesson-timing.md`: resolved times for every beat and camera change.
- `lesson-theme.css`: created once from the template, then yours to edit.
