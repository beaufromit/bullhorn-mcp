"""In-memory CV upload tickets (CR41, FR-15 Amendment, NFR-9).

A CV must reach Bullhorn without its bytes ever passing through a tool argument
(base64 in a tool call costs roughly 100k output tokens per CV). Instead:

1. ``request_cv_upload`` mints a ticket: an opaque ``upload_id`` plus a single-use
   ``token`` that forms the upload URL ``{MCP_BASE_URL}/upload/{token}``.
2. Whoever holds the file (curl in the Cowork VM, or the in-chat upload box)
   POSTs it to that URL. ``redeem`` stores the bytes against the ticket.
3. The CV tools read the bytes back with ``get(upload_id, owner_sub)`` and call
   ``mark_attached`` once Bullhorn has the file, which drops the bytes.

Security and retention rules (NFR-9):
- The token is 256 bits from ``secrets`` and only its SHA-256 is stored, so a
  memory dump or a debug print of the store cannot be replayed as a URL.
- Tickets are single use and expire 15 minutes after issue.
- Records are bound to the Entra ``sub`` that minted them; any other caller gets
  "not found", never "forbidden", so ids cannot be probed.
- Bytes live in memory only. They are dropped on attach, or 30 minutes after
  upload otherwise. A small tombstone survives so ``get`` can say ``attached``
  or ``expired`` instead of "not found". An ``attached`` tombstone is removed at
  the original 30-minute purge time (30 minutes after upload, however soon the
  attach happened); an ``expired`` one is removed 30 minutes after it expired.
- The stored resume parse (structured fields, no file bytes) stays on an
  ``attached`` tombstone until that purge; an ``expired`` tombstone drops it.
- Each user may hold at most ``MAX_OPEN_UPLOADS_PER_USER`` pending or received
  uploads at once, so one caller cannot fill process memory with parked files.
- A commit call ``claim``s the upload for the length of its Bullhorn writes, so
  two overlapping calls on one ``upload_id`` cannot both write and attach.
- Purging is lazy (on every call). No background thread.

Production is one process, so this module-level store is shared by the MCP tools
and the upload route. A restart drops in-flight uploads; the user re-sends.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Callable

# Bullhorn's own attachment cap is 10 MB (File Attachment FAQ). Anything larger
# would pass this server and then fail at Bullhorn, so it is rejected up front.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({"pdf", "doc", "docx", "rtf", "odt", "txt", "html", "htm"})
TICKET_TTL_SECONDS = 15 * 60
FILE_TTL_SECONDS = 30 * 60
# Pending plus received uploads one user may hold at once (10 x 10 MB at most).
MAX_OPEN_UPLOADS_PER_USER = 10

# Bullhorn's parser takes "text" and "html" rather than the file suffixes.
_PARSER_FORMAT = {"txt": "text", "htm": "html"}


class UploadError(Exception):
    """Base class. ``code`` is the JSON error slug, ``http_status`` the route's reply."""

    code = "upload_error"
    http_status = 400


class UploadNotFound(UploadError):
    code = "upload_not_found"
    http_status = 404


class UploadExpired(UploadError):
    code = "upload_expired"
    http_status = 410


class UploadAlreadyUsed(UploadError):
    code = "upload_already_used"
    http_status = 410


class UploadTooLarge(UploadError):
    code = "file_too_large"
    http_status = 413


class UploadBadType(UploadError):
    code = "unsupported_file_type"
    http_status = 415


class UploadEmpty(UploadError):
    code = "empty_file"
    http_status = 400


class UploadLimitReached(UploadError):
    code = "too_many_uploads"
    http_status = 429


class UploadInUse(UploadError):
    code = "upload_in_use"
    http_status = 409


def file_extension(filename: str | None) -> str | None:
    """Return the lower-case final suffix without the dot, or None.

    Only the final suffix counts: ``"Jane_CV_New..pdf"`` (a real Cowork name seen
    in T40.1) is a PDF. Any directory part is ignored.
    """
    if not filename:
        return None
    suffix = PurePath(filename.replace("\\", "/")).suffix
    return suffix[1:].lower() if len(suffix) > 1 else None


def parser_format(extension: str) -> str:
    """Map a file extension to the format hint Bullhorn's resume parser expects."""
    return _PARSER_FORMAT.get(extension, extension)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _Upload:
    upload_id: str
    owner_sub: str
    filename: str
    extension: str
    candidate_id: int | None
    token_hash: str | None
    ticket_expires_at: float
    status: str = "pending"  # pending | received | attached | expired
    data: bytes | None = None
    size: int | None = None
    sha256: str | None = None
    received_at: float | None = None
    file_id: object = None
    remove_at: float | None = None  # set once the record is a tombstone
    parsed: dict | None = None  # stored resume parse (no file bytes)
    attached_candidate_id: int | None = None
    created_candidate_id: int | None = None  # Candidate create_candidate_from_cv made from it


class UploadStore:
    """Thread-safe in-memory store of upload tickets and received files."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._uploads: dict[str, _Upload] = {}
        self._by_token: dict[str, str] = {}  # token hash -> upload_id
        self._claimed: set[str] = set()  # upload_ids a commit call is using

    # --- internal -------------------------------------------------------

    def _expires_at_utc(self, monotonic_deadline: float) -> datetime:
        """Wall-clock equivalent of a store deadline, for showing to the caller."""
        return datetime.now(timezone.utc) + timedelta(seconds=monotonic_deadline - self._clock())

    def _purge(self, now: float) -> None:
        """Expire and remove records whose time is up. Caller holds the lock."""
        for upload_id in list(self._uploads):
            rec = self._uploads[upload_id]
            if rec.status == "pending" and now >= rec.ticket_expires_at:
                self._tombstone(rec, "expired", now + FILE_TTL_SECONDS)
            elif rec.status == "received" and now >= rec.received_at + FILE_TTL_SECONDS:
                self._tombstone(rec, "expired", now + FILE_TTL_SECONDS)
            if rec.remove_at is not None and now >= rec.remove_at:
                # The token hash stays indexed until here, so a used or expired
                # link answers 410 rather than 404 while the tombstone lives.
                if rec.token_hash is not None:
                    self._by_token.pop(rec.token_hash, None)
                del self._uploads[upload_id]

    def _tombstone(self, rec: _Upload, status: str, remove_at: float) -> None:
        rec.status = status
        rec.data = None
        if status != "attached":
            rec.parsed = None
        rec.remove_at = remove_at

    def _issue_token(self, rec: _Upload, now: float) -> str:
        if rec.token_hash is not None:
            self._by_token.pop(rec.token_hash, None)
        token = secrets.token_urlsafe(32)
        rec.token_hash = _hash_token(token)
        rec.ticket_expires_at = now + TICKET_TTL_SECONDS
        self._by_token[rec.token_hash] = rec.upload_id
        return token

    def _owned(self, upload_id: str, owner_sub: str) -> _Upload:
        rec = self._uploads.get(upload_id)
        if rec is None or not owner_sub or not secrets.compare_digest(rec.owner_sub, owner_sub):
            raise UploadNotFound(f"No upload '{upload_id}' for this user.")
        return rec

    # --- public API -----------------------------------------------------

    def create(
        self, owner_sub: str, filename: str, candidate_id: int | None = None
    ) -> tuple[str, str, datetime]:
        """Mint a ticket. Returns ``(upload_id, token, expires_at_utc)``.

        ``filename`` is the original name the user attached; it is the name the
        file gets in Bullhorn. Raises ``UploadBadType`` before any upload when its
        extension is not an allowed CV type.
        """
        extension = file_extension(filename)
        if extension not in ALLOWED_EXTENSIONS:
            raise UploadBadType(
                f"'{filename}' is not an allowed CV type. Allowed: "
                + ", ".join(sorted(ALLOWED_EXTENSIONS))
            )
        name = PurePath(filename.replace("\\", "/")).name
        with self._lock:
            now = self._clock()
            self._purge(now)
            open_count = sum(
                1 for r in self._uploads.values()
                if r.owner_sub == owner_sub and r.status in ("pending", "received")
            )
            if open_count >= MAX_OPEN_UPLOADS_PER_USER:
                raise UploadLimitReached(
                    f"You already have {open_count} open CV uploads (the limit is "
                    f"{MAX_OPEN_UPLOADS_PER_USER}). Finish or wait out one of them first."
                )
            upload_id = "upl_" + secrets.token_hex(12)
            rec = _Upload(
                upload_id=upload_id,
                owner_sub=owner_sub,
                filename=name,
                extension=extension,
                candidate_id=candidate_id,
                token_hash=None,
                ticket_expires_at=now,
            )
            token = self._issue_token(rec, now)
            self._uploads[upload_id] = rec
            return upload_id, token, self._expires_at_utc(rec.ticket_expires_at)

    def check_token(self, token: str) -> None:
        """Raise the same errors ``redeem`` would for the token alone.

        Lets the route refuse a dead ticket before reading a 10 MB body.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._ticket_for(token, now)

    def _ticket_for(self, token: str, now: float) -> _Upload:
        upload_id = self._by_token.get(_hash_token(token))
        if upload_id is None:
            raise UploadNotFound("Unknown, used or expired upload link.")
        rec = self._uploads[upload_id]
        if rec.status == "expired" or (rec.status == "pending" and now >= rec.ticket_expires_at):
            raise UploadExpired("This upload link has expired. Call request_cv_upload again.")
        if rec.status != "pending":
            raise UploadAlreadyUsed("This upload link has already been used.")
        return rec

    def redeem(self, token: str, upload_filename: str | None, data: bytes) -> dict:
        """Store ``data`` against the ticket. Single use, atomic.

        ``upload_filename`` (the multipart name, which in Cowork carries an
        8-hex prefix) is only used to check its extension matches the ticket's;
        the stored name stays the one given to ``create``. A rejected file does
        not consume the ticket, so the user can resend the right one.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            rec = self._ticket_for(token, now)
            if not data:
                raise UploadEmpty("The uploaded file is empty.")
            if len(data) > MAX_UPLOAD_BYTES:
                raise UploadTooLarge(
                    f"The file is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES} bytes (10 MB)."
                )
            if file_extension(upload_filename) != rec.extension:
                raise UploadBadType(
                    f"The uploaded file must be a .{rec.extension} file to match '{rec.filename}'."
                )
            rec.status = "received"
            rec.data = bytes(data)
            rec.size = len(data)
            rec.sha256 = hashlib.sha256(data).hexdigest()
            rec.received_at = now
            return {"upload_id": rec.upload_id, "filename": rec.filename, "size": rec.size}

    def reissue_token(self, upload_id: str, owner_sub: str) -> tuple[str, datetime]:
        """Give a still-pending ticket a fresh token and a fresh 15-minute window.

        Only the hash of a token is kept, so the original URL cannot be rebuilt;
        the in-chat upload box gets a new one instead. The old token stops working.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            rec = self._owned(upload_id, owner_sub)
            if rec.status == "expired":
                raise UploadExpired("This upload has expired. Call request_cv_upload again.")
            if rec.status != "pending":
                raise UploadAlreadyUsed(f"This upload is already {rec.status}.")
            token = self._issue_token(rec, now)
            return token, self._expires_at_utc(rec.ticket_expires_at)

    def get(self, upload_id: str, owner_sub: str) -> dict:
        """Return the record as a dict for its owner; anyone else gets ``UploadNotFound``.

        Keys: upload_id, status, filename, extension, format, candidate_id, size,
        sha256, file_id, ``parsed`` (stored resume parse or None),
        ``attached_candidate_id``, ``created_candidate_id``, and ``data`` (bytes,
        only while ``received``).
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            rec = self._owned(upload_id, owner_sub)
            return {
                "upload_id": rec.upload_id,
                "status": rec.status,
                "filename": rec.filename,
                "extension": rec.extension,
                "format": parser_format(rec.extension),
                "candidate_id": rec.candidate_id,
                "size": rec.size,
                "sha256": rec.sha256,
                "file_id": rec.file_id,
                "parsed": rec.parsed,
                "attached_candidate_id": rec.attached_candidate_id,
                "created_candidate_id": rec.created_candidate_id,
                "data": rec.data if rec.status == "received" else None,
            }

    def set_parsed(self, upload_id: str, owner_sub: str, parsed: dict) -> None:
        """Store the resume parse against a received or attached upload."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            rec = self._owned(upload_id, owner_sub)
            if rec.status == "expired":
                raise UploadExpired("This upload has expired. Call request_cv_upload again.")
            if rec.status == "pending":
                raise UploadError("No file has been received for this upload yet.")
            rec.parsed = parsed

    def claim(self, upload_id: str, owner_sub: str) -> None:
        """Reserve a received upload for one commit call. Pair with ``release``.

        Raises ``UploadInUse`` while another call holds it, so two overlapping
        commits on one ``upload_id`` cannot both write to Bullhorn and attach.
        """
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._owned(upload_id, owner_sub)
            if upload_id in self._claimed:
                raise UploadInUse(f"Upload '{upload_id}' is being used by another call right now.")
            self._claimed.add(upload_id)

    def release(self, upload_id: str) -> None:
        """End a ``claim``. Safe to call after ``mark_attached`` or a purge."""
        with self._lock:
            self._claimed.discard(upload_id)

    def mark_created(self, upload_id: str, candidate_id: int) -> None:
        """Record the Candidate created from this upload, so a later attach_cv only attaches the file."""
        with self._lock:
            rec = self._uploads.get(upload_id)
            if rec is not None:
                rec.created_candidate_id = candidate_id

    def mark_attached(
        self, upload_id: str, file_id: object = None, candidate_id: int | None = None
    ) -> None:
        """Drop the bytes once Bullhorn holds the file; keep a tombstone until the purge."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            rec = self._uploads.get(upload_id)
            if rec is None:
                return
            rec.file_id = file_id
            rec.attached_candidate_id = candidate_id
            # The bytes go at once (NFR-9) but ``parsed`` stays on the tombstone
            # until the purge: an attach_cv confirm call that follows a first
            # (additions) call which already attached the file still needs the
            # parse Claude reviewed.
            self._tombstone(rec, "attached", (rec.received_at or now) + FILE_TTL_SECONDS)


upload_store = UploadStore()


def _reset_upload_store() -> None:
    """Empty the module-level store. Used in tests for isolation."""
    with upload_store._lock:
        upload_store._uploads.clear()
        upload_store._by_token.clear()
        upload_store._claimed.clear()
