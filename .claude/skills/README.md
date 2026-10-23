# Skills folder

Every folder here with a `SKILL.md` is loaded by the editing agent (Claude Agent SDK,
`skills="all"`). This is where Greg's know-how goes, as plain files he can edit.

## What is here now

- `reels-edit-style/` — how to pick and package a Reel clip. Written from the locked
  rules in Greg's desktop pipelines (repo `sshcvirtual/claude-video-edits`:
  Talking Head Videos, Podcast Style Clips). Greg should read it and correct it.

- `edit-course-lesson/`, `cut-silences/`, `cut-mistakes/` — Katrina's course lesson
  skill and the two cut skills it uses, copied from her HyperFrames student kit (see
  `course/README.md`). Used only for **Course lesson** uploads; the Reel editor does not
  see them.

## What to add

Copy each of these in as its own folder (`<name>/SKILL.md` plus any reference files):

| Skill | What it is | Where it is today |
| --- | --- | --- |
| `gt-talking-head` | Greg's direct-to-camera script voice | Claude account skills (GT skills) |
| `gt-podcast-clips` | Greg's podcast-clip voice and viral patterns | Claude account skills |
| `gt-green-screen` | Greg's reaction / green screen scripts | Claude account skills |
| Greg's editing skills | anything he uses in his own Claude sessions to edit | ask Greg |

The gt-* skills are written for Greg's own content. For other clients, the brand kit
(`clients/<id>/brand_kit.json`) sets the voice; the skills still teach what a strong
hook and a clean clip look like.

Do not put passwords or API keys in skill files.
