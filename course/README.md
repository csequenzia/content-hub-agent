# Course lesson kit files

Course lessons run Katrina's `edit-course-lesson` skill, which comes from her copy of the
HyperFrames student kit (Nate Herk, MIT license, see `LICENSE-hyperframes-student-kit`).
Only the parts the server needs are copied here:

| Here | From the kit | Used for |
| --- | --- | --- |
| `.claude/skills/edit-course-lesson/` | same path | the skill, lesson-plan builder, Healthy Free Life template |
| `.claude/skills/cut-silences/` | same path | silence cut |
| `.claude/skills/cut-mistakes/` | same path | mistake candidates + applying cuts |
| `course/starter/` | `examples/starter/` (json files) | new lesson project |
| `course/preflight.mjs` | `scripts/preflight.mjs` | checks the built page before rendering |
| `package.json` | trimmed to `hyperframes` + `gsap` | rendering |

When Katrina changes the skill or the brand template in her kit, copy the changed
folder over the matching one here. `hub/course.py` calls the scripts by these paths.
