"""UEFN Ducky to UEFN Ducky: one signed-in UEFN Ducky asks another of the same
account to run an allowlisted panel call, through that Ducky's site mailbox.

- Sealed end to end with the account data key (ADK, the same on every Ducky of the
  account): the site relays only ciphertext, drops the request once answered and the
  answer once read (uefn-ducky ``desktop-rpc``).
- Every message is bound to its request (account, both Duckies, method, id and
  direction), so the site can't swap, redirect or replay one.
- The asked Ducky answers only while its Remote access is on (the mailbox waiter).

``rtc_connect`` over this link is how a window of this app opens another Ducky's whole
UI peer to peer (web ``remote/directTransport.ts``, bridge ``ducky``).
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
import zlib
from typing import Any

MAGIC = b"UDL1"
_INFO = b"uefn-ducky/ducky-link/v1"
# The site takes at most this much sealed text per request or answer.
SEALED_MAX = 48_000
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
NOT_ANSWERING = "That UEFN Ducky isn't answering. Open it, signed in, with Remote access on."


class LinkError(Exception):
    """A request couldn't go out, or its answer couldn't be read."""


def _derive(adk: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(adk)


def _aad(account: str, sender: str, receiver: str, method: str, rid: str, direction: str) -> bytes:
    return "|".join((account, sender, receiver, method, rid, direction)).encode("utf-8")


def seal(obj: Any, *, adk: bytes, aad: bytes) -> dict[str, str]:
    """``{"sealed": base64(MAGIC + nonce + AES-256-GCM(zlib(json)))}``."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plain = zlib.compress(json.dumps(obj, default=str, separators=(",", ":")).encode("utf-8"), 6)
    nonce = os.urandom(12)
    box = MAGIC + nonce + AESGCM(_derive(adk)).encrypt(nonce, plain, aad)
    return {"sealed": base64.b64encode(box).decode("ascii")}


def open_sealed(env: Any, *, adk: bytes, aad: bytes) -> Any:
    """The object inside ``seal``'s envelope; ``LinkError`` for anything else."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    text = env.get("sealed") if isinstance(env, dict) else None
    try:
        box = base64.b64decode(str(text or ""), validate=True)
    except ValueError as exc:
        raise LinkError("not a sealed message") from exc
    if len(box) < len(MAGIC) + 12 + 16 or not box.startswith(MAGIC):
        raise LinkError("not a sealed message")
    nonce, body = box[len(MAGIC) : len(MAGIC) + 12], box[len(MAGIC) + 12 :]
    try:
        plain = AESGCM(_derive(adk)).decrypt(nonce, body, aad)
    except InvalidTag as exc:
        raise LinkError("This message wasn't sealed for this request by your account.") from exc
    return json.loads(zlib.decompress(plain).decode("utf-8"))


def _context() -> tuple[str, str, bytes]:
    """(account id, this Ducky's key id, the account data key) or ``LinkError``."""
    from backend.uefn_plugins import data_crypto
    from backend.uefn_plugins.scopes import LOCAL, account_id
    from frontend.duckyos_account import _load_blob

    account = account_id()
    own = str(_load_blob().get("device_key_id") or "").strip()
    if account == LOCAL or not own:
        raise LinkError("Sign in to your Ducky account on this UEFN Ducky first.")
    key = data_crypto.adk(account)
    if key is None:
        raise LinkError("Waiting for your account's key. Try again in a minute.")
    return account, own, key


def list_duckies() -> dict[str, Any]:
    """The account's UEFN Duckies (this one marked ``mine``); ``live`` = reachable now."""
    from frontend.duckyos_account import list_account_pcs

    return list_account_pcs()


def call(to: str, method: str, args: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    """Run ``method`` on the UEFN Ducky ``to`` (its key id). ``{"ok", "result" | "error"}``; never raises."""
    from frontend.duckyos_account import RPC_ALLOWLIST, DuckyOSAccountError, _plugin_collect

    to = str(to or "").strip()
    if not _KEY_ID.fullmatch(to):
        return {"ok": False, "error": "Pick one of your UEFN Duckies."}
    if method not in RPC_ALLOWLIST:
        return {"ok": False, "error": "That call can't go to another UEFN Ducky."}
    try:
        account, own, key = _context()
    except LinkError as exc:
        return {"ok": False, "error": str(exc)}
    if to == own:
        return {"ok": False, "error": "That's this UEFN Ducky."}
    rid = uuid.uuid4().hex
    sealed = seal(args or {}, adk=key, aad=_aad(account, own, to, method, rid, "req"))
    if len(sealed["sealed"]) > SEALED_MAX:
        return {"ok": False, "error": "That request is too big to send."}
    errors = {"unavailable_code": "link_unavailable", "unavailable_msg": "", "error_code": "link_failed"}
    try:
        _plugin_collect("uefn-ducky", "desktop-rpc", {"keyId": to, "id": rid, "method": method, "args": sealed}, timeout=15.0, **errors)
        deadline = time.monotonic() + max(1.0, float(timeout))
        pause = 0.3
        while True:
            row = _plugin_collect("uefn-ducky", "desktop-rpc-result", {"id": rid, "keyId": to}, timeout=15.0, **errors)
            status = str(row.get("status") or "")
            if status not in ("", "pending"):
                break
            if time.monotonic() >= deadline:
                return {"ok": False, "error": NOT_ANSWERING}
            time.sleep(pause)
            pause = min(pause * 1.5, 1.0)
    except DuckyOSAccountError as exc:
        return {"ok": False, "error": exc.message}
    if status == "gone":
        return {"ok": False, "error": NOT_ANSWERING}
    if row.get("ok") is False:
        return {"ok": False, "error": str(row.get("error") or "That UEFN Ducky couldn't do it.")}
    result = row.get("result")
    if result is None:
        return {"ok": True, "result": None}
    try:
        return {"ok": True, "result": open_sealed(result, adk=key, aad=_aad(account, own, to, method, rid, "res"))}
    except (LinkError, ValueError, zlib.error) as exc:
        return {"ok": False, "error": str(exc)}


def answer(rid: str, sender: str, method: str, args: Any) -> dict[str, Any]:
    """The mailbox waiter's answer to another UEFN Ducky's sealed request:
    open it, run it like any mailbox call, seal what goes back."""
    from frontend.duckyos_account import dispatch_desktop_rpc

    try:
        account, own, key = _context()
        opened = open_sealed(args, adk=key, aad=_aad(account, sender, own, method, rid, "req"))
    except (LinkError, ValueError, zlib.error) as exc:
        return {"ok": False, "error": str(exc)}
    out = dispatch_desktop_rpc(method, opened if isinstance(opened, dict) else {})
    if "result" in out:
        sealed = seal(out["result"], adk=key, aad=_aad(account, sender, own, method, rid, "res"))
        if len(sealed["sealed"]) > SEALED_MAX:
            return {"ok": False, "error": "The answer is too big to send back. Ask for less."}
        out = {**out, "result": sealed}
    return out
