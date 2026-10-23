"""STUB: GoHighLevel (GHL), for client messages and scheduling the approved post.

Likely uses: text/email the client "your draft is ready" through their GHL contact,
and later schedule the approved Reel through GHL Social Planner.

Needs: a GHL private integration token for Greg's sub-account (GHL_API_TOKEN,
GHL_LOCATION_ID). See project notes on GHL integration for what the API allows.
"""


def send_draft_ready(client_id: str, message: str) -> None:
    raise NotImplementedError("GHL not set up yet")


def schedule_post(client_id: str, video_url: str, caption: str, when_iso: str) -> None:
    raise NotImplementedError("GHL not set up yet")
