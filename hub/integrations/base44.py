"""STUB: Greg's Base44 app (client list, brand kits, approvals).

While Base44 stays the client-facing hub, the worker could read the client list and
brand kits from it and write draft status back so drafts show on the approval screen.
Base44 entity API calls need an API key from the app's settings (BASE44_APP_ID,
BASE44_API_KEY). Until then, clients/<client-id>/brand_kit.json is the source of truth.
"""


def list_clients() -> list[dict]:
    raise NotImplementedError("Base44 not connected yet")


def mark_draft_ready(client_id: str, draft: dict) -> None:
    raise NotImplementedError("Base44 not connected yet")
