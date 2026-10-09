"""
calibra_ee.sync — outcome sync to Calibra Cloud (moved from calibra.outcome_db, ADR-012).

Runs as the `outcome_recorded` plugin hook, after the core has written the
outcome to the local store (~/.calibra/outcomes.jsonl).

Authenticated users (after `calibra login`): syncs the full record to the
authenticated endpoint, tied to the account.

Unauthenticated users: syncs anonymized metric values only to the public
aggregation endpoint. Opt out by setting CALIBRA_NO_CLOUD_SYNC=1.

Failures are always silent (3-second timeout, never blocks the CLI).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
import uuid
from pathlib import Path

from calibra.outcome_db import OutcomeRecord

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".calibra" / "config.json"


def sync_disabled() -> bool:
    return os.environ.get("CALIBRA_NO_CLOUD_SYNC", "").lower() in ("1", "true")


def on_outcome_recorded(record: OutcomeRecord) -> None:
    if sync_disabled():
        return

    from calibra import __version__ as version
    from calibra_ee.cloud.auth import get_token

    token = get_token()
    if token:
        _sync_authenticated(record, token, version)
    else:
        _sync_anonymous(record, version)

    if record.domain == "robotics":
        from calibra_ee.community import print_community_context

        print_community_context(record.fingerprint, record.policy_family)


def _get_installation_id() -> str:
    """Return a stable anonymous installation UUID, generating one on first call.

    Persisted in ~/.calibra/config.json so the same ID is reused across
    invocations. Allows server-side deduplication without identifying the user.
    """
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            if "installation_id" in data:
                return data["installation_id"]
        else:
            data = {}
        installation_id = str(uuid.uuid4())
        data["installation_id"] = installation_id
        with open(_CONFIG_PATH, "w") as f:
            json.dump(data, f)
        return installation_id
    except Exception:
        # If we can't persist, return a session-only ID rather than crashing.
        return str(uuid.uuid4())


def _print_telemetry_notice_once() -> None:
    """Print a one-time notice to stderr about anonymized telemetry sync."""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
        if data.get("telemetry_notice_shown"):
            return
        print(
            "\n[calibra] Anonymized training outcomes are synced to calibra.ai to "
            "improve global\n"
            "          prediction accuracy. No paths, filenames, or identifiable data "
            "are sent.\n"
            "          Set CALIBRA_NO_CLOUD_SYNC=1 to opt out.\n",
            file=sys.stderr,
        )
        data["telemetry_notice_shown"] = True
        with open(_CONFIG_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _post(endpoint: str, payload: dict, headers: dict[str, str]) -> None:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3):
        pass


def _sync_authenticated(record: OutcomeRecord, token: str, version: str) -> None:
    endpoint = (
        os.environ.get("CALIBRA_CLOUD_URL", "https://app.calibra.io")
        + "/api/outcomes/authenticated"
    )
    try:
        _post(
            endpoint,
            {
                "fingerprint": record.fingerprint,
                "predicted_score": record.predicted_score,
                "actual_success_rate": record.actual_success_rate,
                "policy_family": record.policy_family,
                "n_episodes": record.n_episodes,
                "dataset_name": record.dataset_name,
                "calibra_version": version,
                "domain": record.domain,
            },
            {"Authorization": f"Bearer {token}"},
        )
        logger.debug("Authenticated cloud sync succeeded")
    except Exception as exc:
        logger.debug("Authenticated cloud sync failed (non-fatal): %s", exc)


def _sync_anonymous(record: OutcomeRecord, version: str) -> None:
    _print_telemetry_notice_once()
    endpoint = os.environ.get("CALIBRA_CLOUD_ENDPOINT", "https://outcomes.calibra.ai/v1/record")
    try:
        _post(
            endpoint,
            {
                "installation_id": _get_installation_id(),
                "fingerprint": record.fingerprint,
                "predicted_score": record.predicted_score,
                "actual_success_rate": record.actual_success_rate,
                "policy_family": record.policy_family,
                "calibra_version": version,
                "domain": record.domain,
            },
            {},
        )
        logger.debug("Anonymous cloud sync succeeded to %s", endpoint)
    except Exception as exc:
        logger.debug("Anonymous cloud sync failed (non-fatal): %s", exc)
