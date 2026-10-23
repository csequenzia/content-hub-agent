#!/usr/bin/env node
// Turn a lesson's slide deck (PDF) into source material for the lesson plan.
//
// Usage: node .claude/skills/edit-course-lesson/scripts/deck.mjs <project-dir> <deck.pdf>
//
// Writes <project>/deck/slide-NN.png (1920 px wide) and <project>/deck/slides.md with
// each slide's text. Slides are not shown in the lesson as-is: their titles and bullets
// become takeaways, section slides become section cards, and diagram regions become
// image aids through a beat's "slide" + "slideCrop" fields (see references/lesson-plan.md).
// Export PowerPoint, Keynote, or Google Slides decks to PDF first. Needs poppler
// (pdftoppm, pdftotext): brew install poppler.
import { mkdirSync, writeFileSync, readdirSync, renameSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const [projectArg, deckArg] = process.argv.slice(2);
if (!deckArg) {
  console.error("Usage: deck.mjs <project-dir> <deck.pdf>");
  process.exit(1);
}
const project = resolve(projectArg);
const deck = resolve(deckArg);
const out = join(project, "deck");
mkdirSync(out, { recursive: true });

const run = (cmd, args) => {
  const r = spawnSync(cmd, args, { encoding: "utf8", maxBuffer: 1 << 26 });
  if (r.status !== 0) {
    console.error(`${cmd} failed: ${r.stderr}`);
    process.exit(1);
  }
  return r.stdout;
};

const info = run("pdfinfo", [deck]);
const pages = Number(info.match(/Pages:\s+(\d+)/)?.[1] ?? 0);
run("pdftoppm", ["-png", "-scale-to-x", "1920", "-scale-to-y", "-1", deck, join(out, "p")]);
// pdftoppm names pages p-1.png or p-01.png depending on count; normalize to slide-NN.png.
for (const f of readdirSync(out).filter((f) => /^p-\d+\.png$/.test(f))) {
  const n = Number(f.match(/\d+/)[0]);
  renameSync(join(out, f), join(out, `slide-${String(n).padStart(2, "0")}.png`));
}

const md = [`# Deck: ${deckArg}`, "", `${pages} slides. Images: deck/slide-NN.png (1920 px wide).`, ""];
for (let n = 1; n <= pages; n++) {
  const text = run("pdftotext", ["-f", String(n), "-l", String(n), "-layout", deck, "-"])
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
  md.push(`## Slide ${n}`, "", text || "(no text: image or diagram only)", "");
}
writeFileSync(join(out, "slides.md"), md.join("\n"));
console.log(`${pages} slides -> ${out}/slide-NN.png and slides.md`);
