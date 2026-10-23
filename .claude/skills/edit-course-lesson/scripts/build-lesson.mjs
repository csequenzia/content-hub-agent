#!/usr/bin/env node
// Build a course-lesson HyperFrames composition from video-projects/<slug>/lesson-plan.json.
//
// Usage:
//   node .claude/skills/edit-course-lesson/scripts/build-lesson.mjs <project-dir> [--check] [--images]
//
//   (default)  resolve anchors, validate, write index.html + lesson-timing.md
//   --check    resolve and validate only; write nothing
//   --images   list beats whose imagePrompt has no image file yet (JSON), then exit
//
// The plan format is documented in ../references/lesson-plan.md.

import { readFileSync, writeFileSync, existsSync, copyFileSync, mkdirSync, cpSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const SKILL_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const W = 1920;
const H = 1080;

const args = process.argv.slice(2);
const projectArg = args.find((a) => !a.startsWith("--"));
if (!projectArg) {
  console.error("Usage: build-lesson.mjs <project-dir> [--check] [--images]");
  process.exit(1);
}
const checkOnly = args.includes("--check");
const listImages = args.includes("--images");
const project = resolve(projectArg);
const planPath = join(project, "lesson-plan.json");
if (!existsSync(planPath)) die(`missing ${planPath}`);
const plan = JSON.parse(readFileSync(planPath, "utf8"));

const errors = [];
const warnings = [];
function die(msg) {
  console.error(msg);
  process.exit(1);
}

// ---------- images mode ----------
if (listImages) {
  const needed = (plan.beats ?? [])
    .filter((b) => b.imagePrompt && b.image && !existsSync(join(project, b.image)))
    .map((b) => ({ id: b.id, image: b.image, prompt: b.imagePrompt }));
  console.log(JSON.stringify(needed, null, 2));
  process.exit(0);
}

// ---------- source media ----------
if (!plan.video) die("plan.video is required (path relative to the project)");
const videoPath = join(project, plan.video);
if (!existsSync(videoPath)) die(`video not found: ${plan.video}`);
const probe = spawnSync(
  "ffprobe",
  ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", videoPath],
  { encoding: "utf8" },
);
const probed = JSON.parse(probe.stdout || "{}");
const duration = round(Number(plan.duration ?? probed.format?.duration));
if (!Number.isFinite(duration) || duration <= 0) die("could not determine video duration");
const srcW = probed.streams?.[0]?.width ?? W;
const srcH = probed.streams?.[0]?.height ?? H;
if (Math.abs(srcW / srcH - W / H) > 0.01) {
  warnings.push(`source is ${srcW}x${srcH}, not 16:9; it will be cover-cropped into 1920x1080`);
}

// ---------- transcript + anchors ----------
const norm = (s) => s.toLowerCase().replace(/[^a-z0-9']+/g, " ").trim();
let words = [];
if (plan.transcript) {
  const tPath = join(project, plan.transcript);
  if (!existsSync(tPath)) die(`transcript not found: ${plan.transcript}`);
  const t = JSON.parse(readFileSync(tPath, "utf8"));
  words = (t.words ?? [])
    .filter((w) => (w.type ? w.type === "word" : true))
    .flatMap((w) => norm(w.text).split(" ").filter(Boolean).map((tok) => ({ tok, start: w.start, end: w.end })));
}

// Find `phrase` in the transcript at or after `from` seconds. Returns the first word's start.
function findAnchor(phrase, from, label) {
  if (!words.length) {
    errors.push(`${label}: anchor "${phrase}" needs plan.transcript`);
    return null;
  }
  const toks = norm(phrase).split(" ").filter(Boolean);
  for (let i = 0; i + toks.length <= words.length; i++) {
    if (words[i].start < from) continue;
    if (toks.every((tk, j) => words[i + j].tok === tk)) return { start: words[i].start, end: words[i + toks.length - 1].end };
  }
  errors.push(`${label}: anchor "${phrase}" not found in transcript after ${from.toFixed(2)}s`);
  return null;
}

const LEAD = plan.anchorLead ?? 0.15; // enter slightly before the word lands

// Resolve a time field: number, or { anchor } object, or anchor string on key `<key>Anchor`.
function resolveTime(obj, key, from, label) {
  if (typeof obj[key] === "number") return obj[key];
  const a = obj[`${key}Anchor`];
  if (a) {
    const hit = findAnchor(a, from, label);
    if (hit) return Math.max(0, round((key === "end" ? hit.end + 0.4 : hit.start - LEAD)));
  }
  return null;
}

// ---------- camera ----------
const cam = {
  box: { w: 620, h: 820, right: 72, radius: 40, ...(plan.camera?.box ?? {}) },
  focusX: plan.camera?.focusX ?? 0.5,
  focusY: plan.camera?.focusY ?? 0.42,
  zoom: plan.camera?.zoom ?? 1,
  transition: plan.camera?.transition ?? 0.9,
};
cam.box.top = cam.box.top ?? Math.round((H - cam.box.h) / 2);
cam.box.left = W - cam.box.right - cam.box.w;

function boxWrap() {
  const s = Math.max(cam.box.h / H, cam.box.w / W) * cam.zoom;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const x = clamp(cam.box.w / 2 - cam.focusX * W * s, cam.box.w - W * s, 0);
  const y = clamp(cam.box.h / 2 - cam.focusY * H * s, cam.box.h - H * s, 0);
  return { x: round(x), y: round(y), scale: round(s, 4) };
}
const MODES = {
  full: { clip: { left: 0, top: 0, width: W, height: H, borderRadius: 0 }, wrap: { x: 0, y: 0, scale: 1 } },
  box: {
    clip: { left: cam.box.left, top: cam.box.top, width: cam.box.w, height: cam.box.h, borderRadius: cam.box.radius },
    wrap: boxWrap(),
  },
};

let cursor = 0;
const cameraEvents = (plan.camera?.events ?? [{ at: 0, mode: "full" }]).map((e, i) => {
  const at = resolveTime(e, "at", cursor, `camera.events[${i}]`) ?? 0;
  if (!MODES[e.mode]) errors.push(`camera.events[${i}]: mode must be "full" or "box"`);
  cursor = at;
  return { at, mode: e.mode };
});
cameraEvents.sort((a, b) => a.at - b.at);
if (cameraEvents[0]?.at > 0) cameraEvents.unshift({ at: 0, mode: "full" });
function camModeAt(t) {
  let m = "full";
  for (const e of cameraEvents) if (e.at <= t) m = e.mode;
  return m;
}

// ---------- beats ----------
// Image aids cut from the lesson's own slides: "slide": N with optional "slideCrop":
// [x, y, w, h] as fractions of the slide. Written once to assets/aids/ (re-cut if the
// crop changes). Also records each image's aspect so wide diagrams keep their shape.
function slideImage(b) {
  const src = join(project, "deck", `slide-${String(b.slide).padStart(2, "0")}.png`);
  if (!existsSync(src)) {
    errors.push(`${b.id ?? "beat"}: deck/slide-${String(b.slide).padStart(2, "0")}.png not found (run deck.mjs)`);
    return null;
  }
  const c = b.slideCrop ?? [0, 0, 1, 1];
  const name = `slide-${String(b.slide).padStart(2, "0")}-${c.map((v) => Math.round(v * 1000)).join("-")}.png`;
  const rel = `assets/aids/${name}`;
  const out = join(project, rel);
  if (!existsSync(out)) {
    mkdirSync(join(project, "assets/aids"), { recursive: true });
    const r = spawnSync("ffmpeg", ["-nostdin", "-y", "-loglevel", "error", "-i", src, "-vf", `crop=iw*${c[2]}:ih*${c[3]}:iw*${c[0]}:ih*${c[1]}`, out]);
    if (r.status !== 0) errors.push(`${b.id}: could not crop slide ${b.slide}`);
  }
  return rel;
}
function aspectOf(rel) {
  const r = spawnSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", join(project, rel)], { encoding: "utf8" });
  const [w, h] = r.stdout.trim().split(",").map(Number);
  return w && h ? w / h : null;
}

const TRACK = { title: 2, section: 3, takeaway: 3, image: 3 };
const beats = [];
cursor = 0;
for (const [i, b] of (plan.beats ?? []).entries()) {
  const label = `beats[${i}] ${b.id ?? ""}`.trim();
  if (!TRACK[b.type]) {
    errors.push(`${label}: unknown type "${b.type}" (title, section, takeaway, image)`);
    continue;
  }
  let start = resolveTime(b, "start", cursor, label);
  if (start == null) {
    errors.push(`${label}: needs start or startAnchor`);
    continue;
  }
  // Content that lands while the camera is still moving into the box gets covered;
  // hold it until the move is mostly done.
  if (b.type !== "title") {
    const moving = cameraEvents.find((e) => e.mode === "box" && e.at > 0 && start >= e.at - 0.05 && start < e.at + cam.transition * 0.75);
    if (moving) start = round(moving.at + cam.transition * 0.75);
  }
  cursor = start;
  const points = (b.points ?? []).map((p, j) => {
    const pt = typeof p === "string" ? { text: p } : { ...p };
    pt.at = resolveTime(pt, "at", start, `${label} point ${j + 1}`);
    return pt;
  });
  const image = b.slide ? slideImage({ ...b, id: b.id ?? `beat-${i + 1}` }) : b.image;
  const aspect = image && existsSync(join(project, image)) ? aspectOf(image) : null;
  beats.push({ ...b, image, aspect, id: b.id ?? `beat-${i + 1}`, start, points, end: resolveTime(b, "end", start, label), track: TRACK[b.type] });
}
// Default end: next beat on the same track, else +maxHold, else video end.
const MAX_HOLD = plan.maxHold ?? 16;
for (const b of beats) {
  if (b.end == null) {
    const next = beats.filter((o) => o.track === b.track && o.start > b.start).sort((x, y) => x.start - y.start)[0];
    b.end = Math.min(next ? next.start - 0.1 : duration, b.start + MAX_HOLD, duration);
  }
  // An end phrase can run a moment into the next beat on the same track: end just before it.
  const nextOnTrack = beats.filter((o) => o.track === b.track && o.start > b.start).sort((x, y) => x.start - y.start)[0];
  if (nextOnTrack && b.end > nextOnTrack.start - 0.1) b.end = nextOnTrack.start - 0.1;
  // Titles belong to the full-screen camera and content to the box: end each beat
  // before the camera leaves the mode it was built for.
  const leaves = cameraEvents.find((e) => e.at > b.start + 0.5 && (b.type === "title" ? e.mode === "box" : e.mode === "full"));
  if (leaves && b.end > leaves.at) b.end = leaves.at;
  b.end = round(Math.min(b.end, duration));
  b.dur = round(b.end - b.start);
  if (b.dur < 1.2) errors.push(`${b.id}: only ${b.dur}s on screen; give it at least 1.2s`);
}

// ---------- validation ----------
for (const t of new Set(beats.map((b) => b.track))) {
  const on = beats.filter((b) => b.track === t).sort((a, b) => a.start - b.start);
  for (let i = 1; i < on.length; i++) {
    if (on[i].start < on[i - 1].end) errors.push(`${on[i - 1].id} and ${on[i].id} overlap (${on[i - 1].end}s > ${on[i].start}s)`);
  }
}
for (const b of beats) {
  const needBox = b.type !== "title";
  if (needBox && camModeAt(b.start + 0.01) === "full") {
    warnings.push(`${b.id} starts while the camera is full screen; add a camera "box" event at or before ${b.start}s`);
  }
  if (b.heading && b.heading.length > 48) warnings.push(`${b.id}: heading is ${b.heading.length} chars; keep it under 48`);
  if (b.points.length > 4) warnings.push(`${b.id}: ${b.points.length} points; keep takeaways to 4 or fewer`);
  for (const p of b.points) {
    if (p.text.length > 42) warnings.push(`${b.id}: point "${p.text}" is ${p.text.length} chars; keep it under 42`);
    if (p.at != null && (p.at < b.start || p.at > b.end - 0.8)) errors.push(`${b.id}: point "${p.text}" at ${p.at}s is outside its beat`);
  }
  if (b.image) {
    if (!existsSync(join(project, b.image))) {
      (checkOnly ? warnings : errors).push(`${b.id}: image not found: ${b.image}${b.imagePrompt ? " (generate it from imagePrompt)" : ""}`);
    }
  }
  if (b.type === "image" && !b.image) errors.push(`${b.id}: image beats need an image path`);
}

// ---------- report ----------
const table = [
  `# Lesson timing: ${plan.title ?? ""}`,
  "",
  `Duration ${duration}s. Generated by build-lesson.mjs; edit lesson-plan.json, not this file.`,
  "",
  "| Time | Camera |",
  "| --- | --- |",
  ...cameraEvents.map((e) => `| ${fmt(e.at)} | ${e.mode} |`),
  "",
  "| Beat | Type | Start | End | Content |",
  "| --- | --- | --- | --- | --- |",
  ...beats
    .sort((a, b) => a.start - b.start)
    .map((b) => {
      const content = [b.heading ?? b.title ?? b.caption ?? "", ...b.points.map((p) => `${p.at != null ? fmt(p.at) + " " : ""}${p.text}`)]
        .filter(Boolean)
        .join(" / ");
      return `| ${b.id} | ${b.type} | ${fmt(b.start)} | ${fmt(b.end)} | ${content.replace(/\|/g, "\\|")} |`;
    }),
];

for (const w of warnings) console.warn(`warning: ${w}`);
if (errors.length) {
  for (const e of errors) console.error(`error: ${e}`);
  console.error(`\n${errors.length} error(s); nothing written.`);
  process.exit(1);
}
if (checkOnly) {
  console.log(table.join("\n"));
  console.log(`\nok: ${beats.length} beats, ${cameraEvents.length} camera events, ${warnings.length} warning(s)`);
  process.exit(0);
}

// ---------- write ----------
const themeDst = join(project, "lesson-theme.css");
if (!existsSync(themeDst)) copyFileSync(join(SKILL_DIR, "template/lesson-theme.css"), themeDst);
// Logos and fonts the theme references; copied once so a project can swap its own.
const brandDst = join(project, "brand");
if (!existsSync(brandDst)) cpSync(join(SKILL_DIR, "template/brand"), brandDst, { recursive: true });
if (plan.product && !existsSync(join(brandDst, "products", `${plan.product}.css`))) {
  const src = join(SKILL_DIR, "template/brand/products", `${plan.product}.css`);
  if (!existsSync(src)) die(`unknown product "${plan.product}" (see template/brand/products/)`);
  mkdirSync(join(brandDst, "products"), { recursive: true });
  copyFileSync(src, join(brandDst, "products", `${plan.product}.css`));
}
const gsapDst = join(project, "assets/gsap.min.js");
if (!existsSync(gsapDst)) {
  const kitGsap = resolve(SKILL_DIR, "../../../node_modules/gsap/dist/gsap.min.js");
  mkdirSync(join(project, "assets"), { recursive: true });
  copyFileSync(kitGsap, gsapDst);
}
writeFileSync(join(project, "index.html"), renderHtml());
writeFileSync(join(project, "lesson-timing.md"), table.join("\n") + "\n");
console.log(`wrote index.html and lesson-timing.md: ${beats.length} beats, ${duration}s, ${warnings.length} warning(s)`);

// ---------- html ----------
function renderHtml() {
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const beatHtml = beats
    .map((b) => {
      const attrs = `id="${b.id}" class="clip beat beat-${b.type}" data-start="${b.start}" data-duration="${b.dur}" data-track-index="${b.track}"`;
      const pts = b.points
        .map((p, j) => `<li class="pt" id="${b.id}-p${j}"><span class="dot"></span><span class="pt-text">${esc(p.text)}</span></li>`)
        .join("");
      const wide = b.aspect && b.aspect > 1.45;
      const frameStyle = b.aspect && (b.slide || wide) ? ` style="aspect-ratio:${b.aspect.toFixed(4)}"` : "";
      const img = b.image ? `<figure class="aid${b.slide ? " from-slide" : ""}"><div class="aid-frame"${frameStyle}><img src="${esc(b.image)}" alt="" /></div>${b.caption ? `<figcaption>${esc(b.caption)}</figcaption>` : ""}</figure>` : "";
      if (b.type === "title") {
        return `<div ${attrs}><div class="title-scrim"></div><div class="title-card"><div class="title-logo"></div>${b.kicker ? `<div class="kicker">${esc(b.kicker)}</div>` : ""}<h1>${esc(b.title ?? b.heading)}</h1>${b.subtitle ? `<p class="sub">${esc(b.subtitle)}</p>` : ""}</div></div>`;
      }
      if (b.type === "section") {
        return `<div ${attrs}><div class="stage"><div class="section-card">${b.number ? `<div class="sec-num">${esc(b.number)}</div>` : ""}<h2>${esc(b.heading)}</h2>${b.subtitle ? `<p class="sub">${esc(b.subtitle)}</p>` : ""}</div></div></div>`;
      }
      if (b.type === "image") {
        return `<div ${attrs}><div class="stage stage-image">${b.heading ? `<h3 class="heading">${esc(b.heading)}</h3>` : ""}${img}</div></div>`;
      }
      return `<div ${attrs}><div class="stage ${b.image ? (wide ? "stage-stack" : "stage-split") : ""}"><div class="takeaway">${b.label ? `<div class="label">${esc(b.label)}</div>` : ""}<h3 class="heading">${esc(b.heading)}</h3><ul class="pts">${pts}</ul></div>${img}</div></div>`;
    })
    .join("\n      ");

  const tl = [];
  const m = (o) => JSON.stringify(o);
  tl.push(`tl.set("#cam-clip", ${m(MODES[cameraEvents[0].mode].clip)}, 0);`);
  tl.push(`tl.set("#cam-wrap", ${m(MODES[cameraEvents[0].mode].wrap)}, 0);`);
  // Corner logo shows only while the camera is boxed (the title card carries its own).
  tl.push(`tl.set("#brand-mark", { opacity: ${cameraEvents[0].mode === "box" ? 1 : 0} }, 0);`);
  for (const e of cameraEvents.slice(1)) {
    const d = cam.transition;
    tl.push(`tl.to("#brand-mark", { opacity: ${e.mode === "box" ? 1 : 0}, duration: ${e.mode === "box" ? 0.6 : 0.3}, ease: "sine.inOut" }, ${e.mode === "box" ? round(e.at + d * 0.6) : e.at});`);
    tl.push(`tl.to("#cam-clip", { ...${m(MODES[e.mode].clip)}, duration: ${d}, ease: "power3.inOut" }, ${e.at});`);
    tl.push(`tl.to("#cam-wrap", { ...${m(MODES[e.mode].wrap)}, duration: ${d}, ease: "power3.inOut" }, ${e.at});`);
  }
  for (const b of beats) {
    const s = b.start;
    const out = round(b.end - 0.35);
    const sel = `#${b.id}`;
    if (b.type === "title") {
      tl.push(`tl.from("${sel} .title-scrim", { opacity: 0, duration: 0.6, ease: "sine.out" }, ${s});`);
      tl.push(`tl.from("${sel} .title-logo, ${sel} .kicker, ${sel} h1, ${sel} .sub", { y: 36, opacity: 0, duration: 0.7, ease: "power3.out", stagger: 0.12 }, ${s + 0.1});`);
    } else if (b.type === "section") {
      tl.push(`tl.from("${sel} .sec-num", { scale: 0.6, opacity: 0, duration: 0.6, ease: "back.out(1.6)" }, ${s});`);
      tl.push(`tl.from("${sel} h2, ${sel} .sub", { y: 40, opacity: 0, duration: 0.7, ease: "power3.out", stagger: 0.1 }, ${s + 0.12});`);
    } else {
      tl.push(`tl.from("${sel} .label, ${sel} .heading", { y: 30, opacity: 0, duration: 0.6, ease: "power3.out", stagger: 0.08 }, ${s});`);
      b.points.forEach((p, j) => {
        const at = p.at ?? round(s + 0.5 + j * 0.45);
        tl.push(`tl.from("#${b.id}-p${j}", { x: -28, opacity: 0, duration: 0.55, ease: "power3.out" }, ${at});`);
      });
      if (b.image) {
        tl.push(`tl.from("${sel} .aid", { y: 40, opacity: 0, duration: 0.8, ease: "power3.out" }, ${s + 0.15});`);
        // Slide diagrams stay still and whole; the gentle push-in is only for photos/illustrations.
        if (!b.slide) tl.push(`tl.fromTo("${sel} .aid img", { scale: 1.0 }, { scale: 1.07, duration: ${b.dur}, ease: "none" }, ${s});`);
      }
    }
    tl.push(`tl.to("${sel}", { opacity: 0, duration: 0.3, ease: "sine.in" }, ${out});`);
    tl.push(`tl.set("${sel}", { opacity: 0 }, ${b.end});`);
  }

  const src = esc(plan.video);
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=${W}, height=${H}" />
    <title>${esc(plan.title ?? "Course lesson")}</title>
    <script src="assets/gsap.min.js"></script>
    <link rel="stylesheet" href="lesson-theme.css" />${plan.product ? `\n    <link rel="stylesheet" href="brand/products/${esc(plan.product)}.css" />` : ""}
    <style>
      #cam-clip { left: ${MODES.full.clip.left}px; top: 0; width: ${W}px; height: ${H}px; }
    </style>
  </head>
  <body>
    <!-- Generated by .claude/skills/edit-course-lesson/scripts/build-lesson.mjs.
         Edit lesson-plan.json or lesson-theme.css and rebuild; hand edits here are overwritten. -->
    <div id="root" data-composition-id="lesson" data-start="0" data-duration="${duration}" data-width="${W}" data-height="${H}">
      <div class="bg"></div>

      <div id="cam-clip">
        <div id="cam-wrap">
          <video id="cam" src="${src}" data-start="0" data-duration="${duration}" data-track-index="0" muted playsinline></video>
        </div>
      </div>
      <audio id="cam-audio" src="${src}" data-start="0" data-duration="${duration}" data-track-index="9" data-volume="1"></audio>

      <div id="brand-mark"></div>

      ${beatHtml}
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      ${tl.join("\n      ")}
      tl.set({}, {}, ${duration});
      window.__timelines["lesson"] = tl;
    </script>
  </body>
</html>
`;
}

function round(n, p = 3) {
  return Math.round(n * 10 ** p) / 10 ** p;
}
function fmt(t) {
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`;
}
