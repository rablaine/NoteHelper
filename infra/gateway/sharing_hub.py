"""
Partner sharing hub — Socket.IO namespace for the NoteHelper gateway.

Handles presence tracking (who's online) and partner data relay between
NoteHelper instances.  Clients connect directly to the gateway app service
(not through APIM) using the same JWT for authentication.

Flow:
1. Client connects with JWT in auth header → gateway validates → user joins
2. Other clients see updated online list via ``online_users`` event
3. Sender emits ``share_request`` → gateway relays to recipient
4. Recipient accepts → emits ``share_accept`` → gateway relays to sender
5. Sender emits ``share_data`` with partner JSON → gateway relays to recipient
6. Recipient processes data locally (upsert) → done
"""
import logging
import os
import threading
import time

import jwt
import requests
from jwt import PyJWKClient
from flask import request
from flask_socketio import Namespace, emit, disconnect

logger = logging.getLogger(__name__)

# Microsoft corp tenant
_MS_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
# Gateway Entra app ID (audience)
_AUDIENCE = "api://0f6db4af-332c-4fd5-b894-77fadb181e5c"
# Microsoft OIDC JWKS endpoint for key rotation
_JWKS_URL = f"https://login.microsoftonline.com/{_MS_TENANT}/discovery/v2.0/keys"

# Online users: sid → {name, email, connected_at}
_online_users: dict[str, dict] = {}

# Sharing allowlist — if set, only these emails can connect.
# Env var: comma-separated emails. Empty/unset = everyone allowed.
_ALLOWED_EMAILS: set[str] = set(
    e.strip().lower()
    for e in os.environ.get("SHARE_ALLOWED_EMAILS", "").split(",")
    if e.strip()
)

# JWKS client — caches signing keys, thread-safe
_jwks_client: PyJWKClient | None = None
_jwks_lock = threading.Lock()


def _get_jwks_client() -> PyJWKClient:
    """Lazily initialize and cache the JWKS client."""
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                _jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True)
    return _jwks_client


def _decode_jwt_claims(token: str) -> dict | None:
    """Decode and verify a JWT using Microsoft's JWKS signing keys.

    Validates:
    - Signature (RSA, from Microsoft's published JWKS keys)
    - Audience (must match our Entra app registration)
    - Expiration (must not be expired)
    - Issuer (must be from Microsoft corp tenant)
    - Tenant ID (must match _MS_TENANT)

    Returns the claims dict or None if validation fails.
    """
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=f"https://sts.windows.net/{_MS_TENANT}/",
        )
        # Belt-and-suspenders: verify tenant claim matches
        if claims.get("tid") != _MS_TENANT:
            return None
        return claims
    except Exception as e:
        logger.warning(f"share: JWT validation failed — {e}")
        return None


class ShareNamespace(Namespace):
    """Socket.IO namespace for partner directory sharing."""

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _sids_for_email(email: str) -> list[str]:
        """Return all SIDs belonging to a given email address."""
        return [
            sid for sid, u in _online_users.items()
            if u["email"].lower() == email.lower()
        ]

    @staticmethod
    def _emit_to_user(event: str, data: dict, email: str):
        """Emit an event to ALL SIDs for a given email."""
        for sid in ShareNamespace._sids_for_email(email):
            emit(event, data, to=sid)

    @staticmethod
    def _unique_online_users(exclude_email: str) -> list[dict]:
        """Build a deduplicated online user list, excluding a given email."""
        seen = set()
        users = []
        for u in _online_users.values():
            email_lower = u["email"].lower()
            if email_lower == exclude_email.lower():
                continue
            if email_lower in seen:
                continue
            seen.add(email_lower)
            users.append({"name": u["name"], "email": u["email"]})
        return users

    def _broadcast_online(self):
        """Send updated online list to all connected clients."""
        for sid, me in _online_users.items():
            users = self._unique_online_users(me["email"])
            emit("online_users", {"users": users}, to=sid)

    # ── Connection lifecycle ─────────────────────────────────────────────

    def on_connect(self, auth=None):
        """Authenticate the user via JWT and track them as online."""
        token = None
        if auth and isinstance(auth, dict):
            token = auth.get("token")

        if not token:
            logger.warning("share: connection rejected — no token")
            disconnect()
            return False

        claims = _decode_jwt_claims(token)
        if not claims:
            logger.warning("share: connection rejected — invalid token")
            disconnect()
            return False

        name = claims.get("name", "Unknown")
        email = (
            claims.get("preferred_username")
            or claims.get("upn")
            or claims.get("email")
            or "unknown"
        )

        # Allowlist check (if configured)
        if _ALLOWED_EMAILS and email.lower() not in _ALLOWED_EMAILS:
            logger.info(f"share: {email} not in allowlist — rejecting")
            emit("not_allowed", {})
            disconnect()
            return False

        _online_users[request.sid] = {
            "name": name,
            "email": email,
            "connected_at": time.time(),
        }
        logger.info(f"share: {name} ({email}) connected — sid {request.sid}")
        self._broadcast_online()

    def on_disconnect(self):
        """Remove user from online list and broadcast."""
        user = _online_users.pop(request.sid, None)
        if user:
            logger.info(f"share: {user['name']} disconnected")
        self._broadcast_online()

    def on_get_online_users(self):
        """Client requests the current online user list."""
        my_email = _online_users.get(request.sid, {}).get("email", "")
        users = self._unique_online_users(my_email)
        emit("online_users", {"users": users})

    # ── Share flow (all email-based) ─────────────────────────────────────

    def on_share_request(self, data):
        """Sender wants to share partners with a specific recipient.

        data: {recipient_email, share_type: "directory"|"partner", partner_name?: str}
        """
        recipient_email = data.get("recipient_email", "")
        recipient_sids = self._sids_for_email(recipient_email)
        if not recipient_sids:
            emit("share_error", {"error": "Recipient is no longer online"})
            return

        sender = _online_users.get(request.sid, {})
        sender_email = sender.get("email", "")

        # Notify ALL of recipient's tabs
        self._emit_to_user("share_offer", {
            "sender_email": sender_email,
            "sender_name": sender.get("name", "Unknown"),
            "share_type": data.get("share_type", "partner"),
            "partner_name": data.get("partner_name"),
        }, recipient_email)

    def on_share_accept(self, data):
        """Recipient accepts a share offer."""
        sender_email = data.get("sender_email", "")
        sender_sids = self._sids_for_email(sender_email)
        if not sender_sids:
            emit("share_error", {"error": "Sender is no longer online"})
            return

        recipient = _online_users.get(request.sid, {})

        # Notify ALL of sender's tabs
        self._emit_to_user("share_accepted", {
            "recipient_email": recipient.get("email", ""),
            "recipient_name": recipient.get("name", "Unknown"),
        }, sender_email)

        # Dismiss the offer on other recipient tabs
        recipient_email = recipient.get("email", "")
        for sid in self._sids_for_email(recipient_email):
            if sid != request.sid:
                emit("share_offer_handled", {}, to=sid)

    def on_share_decline(self, data):
        """Recipient declines a share offer."""
        sender_email = data.get("sender_email", "")
        sender_sids = self._sids_for_email(sender_email)
        if not sender_sids:
            return

        recipient = _online_users.get(request.sid, {})

        # Notify ALL of sender's tabs
        self._emit_to_user("share_declined", {
            "recipient_name": recipient.get("name", "Unknown"),
        }, sender_email)

        # Dismiss the offer on other recipient tabs
        recipient_email = recipient.get("email", "")
        for sid in self._sids_for_email(recipient_email):
            if sid != request.sid:
                emit("share_offer_handled", {}, to=sid)

    def on_share_data(self, data):
        """Sender transmits partner data to the recipient.

        data: {recipient_email, partners: [...]}
        The gateway relays without inspecting the payload.
        """
        recipient_email = data.get("recipient_email", "")
        recipient_sids = self._sids_for_email(recipient_email)
        if not recipient_sids:
            emit("share_error", {"error": "Recipient is no longer online"})
            return

        sender = _online_users.get(request.sid, {})

        # Send to ALL recipient tabs — the client deduplicates the upsert
        self._emit_to_user("share_payload", {
            "sender_name": sender.get("name", "Unknown"),
            "sender_email": sender.get("email", ""),
            "partners": data.get("partners", []),
        }, recipient_email)
