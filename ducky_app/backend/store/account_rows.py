"""Chats and duckies belong to the Ducky account signed in on this PC (migration 0024).

Every row of ``conversations``, ``messages``, ``folders``, ``duckies`` and
``duckies_history`` carries its owner's ``account_id`` (``scopes.account_id()``,
``_local`` signed out), and the repos read and write only the current account's rows:
signing in to another account shows that account's chats and duckies, and signing out
shows the ``_local`` ones. Shipped duckies are not rows; they are there for everyone.

What the person wrote is sealed for its account with :mod:`backend.uefn_plugins.data_crypto`
(DPAPI plus the account data key; plain DPAPI signed out): chat titles and state, message
bodies and payloads, folder names, ducky data, other Duckies' chat copies. Another account
on this PC can't read them, not even from ``ducky.db``. No key yet raises
``data_crypto.Locked``; nothing is written as plaintext.

Search works without the words: a message's search text is stored as one keyed token per
word (:func:`blind_text`), and a query becomes the same tokens (:func:`blind_query`).

Rows from before (account ``''``) go whole to the first account that opens them
(:func:`claim`, from ``scopes.account_id``) and are sealed in place (:func:`seal_pending`,
at boot and at sign-in). Nothing is deleted. The space those rewrites free is zeroed;
slack in pages written before 0024 keeps old fragments until the page is rewritten (only
a VACUUM rebuilds every page), and backups made before the upgrade age out on their own.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterator

from backend.store import db

UNCLAIMED = ""
# Owner of an old row the claiming account already had a copy of (the same folder or ducky):
# the account keeps its own, the old copy stays in the table under an owner nobody reads.
PARKED = "_parked:"
_KEY_META = "chat_key:"
_SEALED = "enc1:"  # data_crypto.PREFIX
_SEALED_BLOB = b"UDE1"  # data_crypto.FILE_MAGIC

# Columns holding what the person wrote, sealed in place by seal_pending (messages and
# their payloads are the chats repo's own: seal_stored_messages).
SEALED_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("conversations", ("title", "state")),
    ("folders", ("name",)),
    ("duckies", ("data",)),
    ("duckies_history", ("data",)),
    ("ducky_mirror_chats", ("title", "rows")),
)

_lock = threading.Lock()
_chat_keys: dict[tuple[str, str], bytes] = {}
_sealing: set[tuple[str, str]] = set()

# Opened titles, chat state and folder names: a sidebar lists every chat of a project on
# each change, two DPAPI calls a chat without this.
_OPENED_MAX = 4096
_OPENED_MAX_CHARS = 16 * 1024 * 1024
_OPENED_ITEM_MAX = 256 * 1024
_opened: OrderedDict[tuple[str, str], str] = OrderedDict()
_opened_chars = 0


def current() -> str:
    """The signed-in account's id (``_local`` signed out); claims rows from before 0024."""
    from backend.uefn_plugins.scopes import account_id

    return account_id()


# --------------------------------------------------------------------------- sealing


def ready(account: str) -> bytes:
    """Before a write transaction: the account's data key is on this PC (else ``Locked``)
    and its chat key is loaded, so sealing inside the transaction needs no network call
    and no other write. Returns the chat key."""
    from backend.uefn_plugins import data_crypto

    if not data_crypto.available(account):
        raise data_crypto.Locked("Waiting for this account's data key. Your chats open once you're online.")
    return chat_key(account)


def chat_key(account: str) -> bytes:
    """The account's key for search tokens and payload names: random, stored sealed."""
    from backend.uefn_plugins import data_crypto

    memo = (str(db.db_path()), account)
    with _lock:
        key = _chat_keys.get(memo)
    if key is not None:
        return key
    conn = db.connect()
    name = _KEY_META + account
    row = conn.execute("SELECT value FROM meta WHERE key=?", (name,)).fetchone()
    if row is None:
        fresh = data_crypto.seal_text(base64.b64encode(os.urandom(32)).decode("ascii"), account)
        with db.write_txn(conn):
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value, updated) VALUES (?, ?, ?)", (name, fresh, time.time())
            )
        row = conn.execute("SELECT value FROM meta WHERE key=?", (name,)).fetchone()
    key = base64.b64decode(data_crypto.open_text(str(row[0]), account))
    with _lock:
        _chat_keys[memo] = key
    return key


def is_sealed(stored: object) -> bool:
    return isinstance(stored, str) and stored.startswith(_SEALED)


def seal(text: str, account: str) -> str:
    """``text`` sealed for ``account``; an empty value stays empty (nothing to hide)."""
    from backend.uefn_plugins import data_crypto

    return data_crypto.seal_text(text, account) if text else ""


def open_text(stored: str, account: str) -> str:
    """Plaintext of a stored value: sealed ones are opened, rows from before pass as they are."""
    from backend.uefn_plugins import data_crypto

    return data_crypto.open_text(stored, account) if is_sealed(stored) else stored


def open_cached(stored: str, account: str) -> str:
    """:func:`open_text` for small values read over and over (titles, chat state, names)."""
    global _opened_chars
    if not is_sealed(stored) or len(stored) > _OPENED_ITEM_MAX:
        return open_text(stored, account)
    memo = (account, stored)
    with _lock:
        hit = _opened.get(memo)
        if hit is not None:
            _opened.move_to_end(memo)
            return hit
    text = open_text(stored, account)
    with _lock:
        if memo not in _opened:
            _opened[memo] = text
            _opened_chars += len(text)
        while _opened and (len(_opened) > _OPENED_MAX or _opened_chars > _OPENED_MAX_CHARS):
            _, dropped = _opened.popitem(last=False)
            _opened_chars -= len(dropped)
    return text


def seal_blob(data: bytes, account: str) -> bytes:
    from backend.uefn_plugins import data_crypto

    return data_crypto.seal_bytes(data, account)


def open_blob(raw: bytes, account: str) -> bytes:
    """A stored payload: sealed ones are opened, payloads from before pass as they are."""
    from backend.uefn_plugins import data_crypto

    return data_crypto.open_bytes(raw, account) if raw.startswith(_SEALED_BLOB) else raw


def forget() -> None:
    """Login funnel (``data_crypto.on_login_change``): opened values and keys go."""
    global _opened_chars
    with _lock:
        _chat_keys.clear()
        _opened.clear()
        _opened_chars = 0


# --------------------------------------------------------------------------- search without the words

_WORD = re.compile(r"[^\W_]+")


def words(text: str) -> list[str]:
    """The words search matches on: case and accents folded, ``_`` and punctuation split."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    return _WORD.findall("".join(ch for ch in folded if not unicodedata.combining(ch)))


def _token(word: str, key: bytes) -> str:
    digest = hashlib.blake2b(word.encode("utf-8"), key=key, digest_size=5, person=b"chat-word").digest()
    return base64.b32encode(digest).decode("ascii").lower()


def blind_text(text: str, key: bytes) -> str:
    """What the search index keeps of ``text``: one keyed token per word, in order."""
    seen: dict[str, str] = {}
    out: list[str] = []
    for word in words(text):
        token = seen.get(word)
        if token is None:
            token = seen[word] = _token(word, key)
        out.append(token)
    return " ".join(out)


def blind_query(query: str, key: bytes) -> str:
    """FTS5 query over :func:`blind_text` rows: every term as a phrase, or all as one."""
    terms = [ws for ws in (words(t) for t in query.split()) if ws]
    if not terms:
        return ""
    phrases = " ".join('"' + " ".join(_token(w, key) for w in ws) + '"' for ws in terms)
    if len(terms) > 1:
        joined = " ".join(_token(w, key) for ws in terms for w in ws)
        return f'({phrases}) OR "{joined}"'
    return phrases


def part_digest(text: str, key: bytes) -> str:
    """Name of a stored payload: keyed, so two accounts never share one."""
    return hashlib.blake2b(text.encode("utf-8"), key=key, digest_size=32, person=b"chat-part").hexdigest()


# --------------------------------------------------------------------------- rows from before

_UNCLAIMED_ROWS = (
    "SELECT EXISTS(SELECT 1 FROM conversations WHERE account_id='') "
    "OR EXISTS(SELECT 1 FROM folders WHERE account_id='') "
    "OR EXISTS(SELECT 1 FROM duckies WHERE account_id='') "
    "OR EXISTS(SELECT 1 FROM duckies_history WHERE account_id='')"
)


@contextlib.contextmanager
def _zeroing(conn) -> Iterator[None]:
    """Space a rewrite frees is zeroed, so a value's old plaintext doesn't stay in the file."""
    before = int(conn.execute("PRAGMA secure_delete").fetchone()[0])
    conn.execute("PRAGMA secure_delete=ON")
    try:
        yield
    finally:
        conn.execute(f"PRAGMA secure_delete={before}")


def claim(account: str) -> int:
    """Rows from before 0024 become ``account``'s, all of them at once. Returns how many.

    A message belongs to its chat; its own ``account_id`` is filled when it is sealed
    (a batch at a time), not here: rewriting every message in one transaction would hold
    the database for as long as copying it."""
    conn = db.connect()
    if not conn.execute(_UNCLAIMED_ROWS).fetchone()[0]:
        return 0
    with _zeroing(conn), db.write_txn(conn):
        moved = conn.execute("UPDATE conversations SET account_id=? WHERE account_id=''", (account,)).rowcount
        for table in ("folders", "duckies"):
            moved += conn.execute(f"UPDATE OR IGNORE {table} SET account_id=? WHERE account_id=''", (account,)).rowcount
            conn.execute(f"UPDATE {table} SET account_id=? || rowid WHERE account_id=''", (PARKED,))
        moved += conn.execute("UPDATE duckies_history SET account_id=? WHERE account_id=''", (account,)).rowcount
    return moved


def owned_ids(account: str) -> tuple[list[str], list[str]]:
    """(chat ids, folder ids) of one account, for a sidebar dropping them on a switch."""
    conn = db.connect()
    convs = [str(r[0]) for r in conn.execute("SELECT id FROM conversations WHERE account_id=?", (account,))]
    folders = [str(r[0]) for r in conn.execute("SELECT DISTINCT id FROM folders WHERE account_id=?", (account,))]
    return convs, folders


def _seal_table(conn, table: str, cols: tuple[str, ...], account: str, batch: int) -> int:
    """Seal one table's plaintext values of ``account`` in place, a batch per transaction;
    a value changed meanwhile is left to the save that changed it (it wrote it sealed)."""
    pending = " OR ".join(f"({c} <> '' AND substr({c}, 1, 5) <> ?)" for c in cols)
    sets = ", ".join(f"{c}=?" for c in cols)
    same = " AND ".join(f"{c}=?" for c in cols)
    sealed = cursor = 0
    while True:
        rows = conn.execute(
            f"SELECT rowid, {', '.join(cols)} FROM {table} WHERE account_id=? AND rowid>? AND ({pending}) "
            "ORDER BY rowid LIMIT ?",
            (account, cursor, *[_SEALED] * len(cols), batch),
        ).fetchall()
        if not rows:
            return sealed
        todo = [
            (rowid, list(values), [v if not v or is_sealed(v) else seal(str(v), account) for v in values])
            for rowid, *values in rows
        ]
        with db.write_txn(conn):
            for rowid, old, new in todo:
                sealed += conn.execute(f"UPDATE {table} SET {sets} WHERE rowid=? AND {same}", (*new, rowid, *old)).rowcount
        cursor = int(rows[-1][0])


def seal_pending(account: str | None = None, *, batch: int = 40, pause_s: float = 0.05) -> dict[str, int]:
    """Seal every value of ``account`` still in plaintext (rows from before 0024, copies an
    older build wrote). Resumable; does nothing while the account is locked. Never raises
    ``Locked`` (the next boot or sign-in tries again)."""
    from backend.uefn_plugins import data_crypto

    account = account or current()
    memo = (str(db.db_path()), account)
    with _lock:
        if memo in _sealing:
            return {}
        _sealing.add(memo)
    conn = db.connect()
    try:
        ready(account)
        out: dict[str, int] = {}
        from backend.store.repos import chats

        with _zeroing(conn):
            for table, cols in SEALED_COLUMNS:
                n = _seal_table(conn, table, cols, account, batch)
                if n:
                    out[table] = n
            sealed = chats.seal_stored_messages(account, batch=batch, pause_s=pause_s)
        out.update({k: v for k, v in sealed.items() if v})
        return out
    except data_crypto.Locked:
        return {}
    finally:
        with _lock:
            _sealing.discard(memo)
