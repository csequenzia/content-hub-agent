# Connecting an app to the editing agent

Any app can send videos to the agent and get drafts back. That includes Greg's Base44 app
today and an internal app later. Google Drive is not involved. Raw videos go straight from
the uploader's browser into Cloudflare R2 storage, so Base44's 100 MB upload limit
doesn't apply. The agent edits each video, saves the draft back to R2, and the app shows
it for approval.

```
 uploader's browser ──PUT video──▶ R2 bucket ◀──download / save draft── agent (Railway)
        ▲                                                   ▲   │
        │ upload link                         "new video"   │   │ draft ready (callback)
        └──────── app's server side (Base44 backend function) ──┘◀─┘
```

## Setup (one time)

1. **R2 bucket.** In the Cloudflare dashboard, go to **R2 → Create bucket** and name it
   something like `content-hub-videos`. Then go to **R2 → Manage API tokens → Create API
   token** and choose *Object Read & Write*, limited to that bucket. Keep the Access Key
   ID, the Secret Access Key, and your Account ID.
2. **Let browsers upload.** In the bucket, open **Settings → CORS policy** and add the
   policy below, using your app's address:
   Add every app that uploads (for example Content Studio's address too).
   ```json
   [{"AllowedOrigins": ["https://your-app.base44.app"], "AllowedMethods": ["PUT", "GET"],
     "AllowedHeaders": ["Content-Type"], "MaxAgeSeconds": 3600}]
   ```
3. **Railway variables** on the agent service:

   | Name | Value |
   | --- | --- |
   | `HUB_API_TOKEN` | A long random password that only the app knows. Make one with `openssl rand -hex 32`. |
   | `R2_ACCOUNT_ID` | Cloudflare account ID |
   | `R2_ACCESS_KEY_ID` | from the R2 API token |
   | `R2_SECRET_ACCESS_KEY` | from the R2 API token |
   | `R2_BUCKET` | the bucket name |

4. **In the app**, save the agent's address (`https://<service>.up.railway.app`) and
   `HUB_API_TOKEN` as secrets. In Base44, these go under the app's backend function secrets.
   **Call the API only from server-side code.** Browser code must never see the token.

Without R2, the API still works for small files: send a `video_url` the agent can
download. In that case the draft is served by the agent itself (see below).

## The calls

Every call sends the header `Authorization: Bearer <HUB_API_TOKEN>` and uses JSON.

### 1. Get an upload link

`POST /api/v1/uploads`

```json
{ "client_id": "sample-clinic", "filename": "Why your knee still hurts.mov", "content_type": "video/quicktime" }
```

Returns:

```json
{ "video_key": "raw/sample-clinic/3f9a1c2b7d10/Why your knee still hurts.mov",
  "upload_url": "https://…r2.cloudflarestorage.com/…", "method": "PUT",
  "headers": {"Content-Type": "video/quicktime"}, "expires_in": 7200 }
```

The browser then uploads the file directly:
`fetch(upload_url, {method: "PUT", headers, body: file})`.
The link works for 2 hours.

Keep the hook in the filename (for example "Why your knee still hurts.mov"), as with Greg's other pipelines.

### 2. Send the video to be edited

`POST /api/v1/videos`

```json
{ "client_id": "sample-clinic",
  "mode": "reel",
  "hook": "Why your knee still hurts",
  "video_key": "raw/sample-clinic/3f9a1c2b7d10/Why your knee still hurts.mov",
  "external_id": "the app's own id for this video",
  "callback_url": "https://your-app.example/functions/draftReady" }
```

- `mode` is either `"reel"` (a 30-60 second vertical clip) or `"course"` (a full course lesson).
- Send `video_url` (an https link) and `filename` in place of `video_key` if you are not using R2.
- Filmed in several takes? Upload each clip (step 1 once per clip) and send `video_keys`
  (a list, in order) in place of `video_key`. The agent joins them end to end before editing.
- `hook` (optional) is an on-screen hook the creator already wrote; the agent uses it word for word.
  `script` (optional) is the script they read from, so the agent keeps the whole thing where it can.
  Content Studio's teleprompter sends all three.
- `callback_url` is optional.

Returns `201` with the video's status (shape below). If the upload hasn't finished yet,
you get `409`; finish the upload and try again.

### 3. Follow the status

`GET /api/v1/videos/{id}` returns one video. `GET /api/v1/videos?client_id=sample-clinic` lists videos, newest first.

```json
{ "id": "a1b2c3d4e5f6", "status": "draft_ready", "client_id": "sample-clinic", "mode": "reel",
  "filename": "Why your knee still hurts.mov", "external_id": "…",
  "created_at": "2026-10-23T04:00:00Z", "finished_at": "2026-10-23T04:06:12Z",
  "draft": { "filename": "Why your knee still hurts - first draft.mp4",
             "video_url": "https://…r2…/drafts/…mp4?…",
             "video_key": "drafts/sample-clinic/a1b2c3d4e5f6/…mp4",
             "post": { "hook": "…", "post_caption": "…", "hashtags": ["…"], "why_this_clip": "…" },
             "cost_usd": 0.31 },
  "review": null, "error": null }
```

| `status` | Meaning |
| --- | --- |
| `ready_to_edit` | Waiting its turn. Videos are edited one at a time. |
| `editing` | The agent is working on it. A Reel takes about 3-10 minutes. A course lesson takes roughly 3-5 minutes per minute of video. |
| `draft_ready` | The draft is ready. `draft.video_url` is a download link that works for 24 hours, and each status call gives a fresh one. |
| `approved` / `changes_requested` | Someone reviewed it (see step 4). |
| `failed` | `error` says why. |

Course lessons have `draft.course` (Claude's note for the reviewer, the cuts, and the images) in place of `draft.post`.
Without R2, `draft.video_url` is `/api/v1/videos/{id}/draft` on the agent. Fetch it with the same token.

**Callback.** If you sent a `callback_url`, the agent POSTs this same JSON to it when the
draft is ready or the edit fails. The header `X-Hub-Signature: sha256=<hex>` holds the
HMAC-SHA256 of the raw body, keyed with `HUB_API_TOKEN`. Check it before trusting the call.
Failed deliveries are retried 3 times. Polling `GET /videos/{id}` always works as a backup.

### 4. Record the review

`POST /api/v1/videos/{id}/review`

```json
{ "decision": "approved", "note": "", "by": "Greg" }
```

`decision` is `"approved"` or `"changes_requested"`. This only records the decision.
Nothing is posted anywhere.

## Base44 example (backend function, Deno)

```js
// functions/sendToEditor.js: called from the upload screen with the chosen file's name.
const HUB = Deno.env.get("HUB_URL");          // https://<service>.up.railway.app
const TOKEN = Deno.env.get("HUB_API_TOKEN");
const call = (path, body) => fetch(`${HUB}/api/v1${path}`, {
  method: body ? "POST" : "GET",
  headers: { "Authorization": `Bearer ${TOKEN}`, "Content-Type": "application/json" },
  body: body && JSON.stringify(body),
}).then(async (r) => { if (!r.ok) throw new Error(await r.text()); return r.json(); });

// Step 1: the browser asks for an upload link, then PUTs the file to upload_url itself.
export async function uploadLink({ clientId, filename, contentType }) {
  return call("/uploads", { client_id: clientId, filename, content_type: contentType });
}

// Step 2: after the browser's PUT finishes, start the edit.
export async function startEdit({ clientId, videoKey, mode, videoId }) {
  return call("/videos", { client_id: clientId, video_key: videoKey, mode, external_id: videoId,
                           callback_url: `${Deno.env.get("APP_URL")}/functions/draftReady` });
}

// Step 3: the approval screen reads the status and draft link.
export async function editStatus({ hubId }) { return call(`/videos/${hubId}`); }
```

`client_id` must match a brand kit folder on the agent (`clients/<client_id>/brand_kit.json`).
Moving brand kits into the app is a later step (`hub/integrations/base44.py`).
