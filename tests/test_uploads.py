"""Tests for the in-memory CV upload ticket store (CR41, T40.2)."""

import hashlib

import pytest

from bullhorn_mcp import uploads
from bullhorn_mcp.uploads import (
    FILE_TTL_SECONDS,
    MAX_OPEN_UPLOADS_PER_USER,
    MAX_UPLOAD_BYTES,
    TICKET_TTL_SECONDS,
    UploadAlreadyUsed,
    UploadBadType,
    UploadEmpty,
    UploadExpired,
    UploadInUse,
    UploadLimitReached,
    UploadNotFound,
    UploadStore,
    UploadTooLarge,
    file_extension,
    parser_format,
)

OWNER = "sub-owner"
OTHER = "sub-other"


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return UploadStore(clock=clock)


def _received(store, filename="cv.pdf", data=b"%PDF-1.4 hello"):
    upload_id, token, _ = store.create(OWNER, filename)
    store.redeem(token, filename, data)
    return upload_id


class TestCreate:
    def test_create_returns_token_and_id(self, store):
        upload_id, token, expires_at = store.create(OWNER, "cv.pdf")
        assert upload_id.startswith("upl_")
        assert len(upload_id) == len("upl_") + 24
        assert isinstance(token, str)
        assert len(token) >= 43  # token_urlsafe(32)
        assert expires_at.tzinfo is not None

    def test_token_stored_only_as_hash(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

        assert token not in store._by_token
        assert token not in store._by_token.values()
        assert store._by_token == {digest: upload_id}
        for rec in store._uploads.values():
            for value in vars(rec).values():
                assert value != token
                assert not (isinstance(value, str) and token in value)
        assert store._uploads[upload_id].token_hash == digest

    def test_disallowed_extension_rejected_at_create(self, store):
        with pytest.raises(UploadBadType) as exc:
            store.create(OWNER, "cv.exe")
        assert exc.value.http_status == 415
        with pytest.raises(UploadBadType):
            store.create(OWNER, "resume")
        with pytest.raises(UploadBadType):
            store.create(OWNER, "")
        assert store._uploads == {}

    def test_candidate_id_hint_kept(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf", candidate_id=4242)
        assert store.get(upload_id, OWNER)["candidate_id"] == 4242
        upload_id2, _, _ = store.create(OWNER, "cv2.pdf")
        assert store.get(upload_id2, OWNER)["candidate_id"] is None

    def test_double_dot_filename_is_pdf(self, store):
        assert file_extension("Jane_CV_New..pdf") == "pdf"
        upload_id, token, _ = store.create(OWNER, "Jane_CV_New..pdf")
        result = store.redeem(token, "8655a252-Jane_CV_New..pdf", b"data")
        assert result["filename"] == "Jane_CV_New..pdf"
        rec = store.get(upload_id, OWNER)
        assert rec["filename"] == "Jane_CV_New..pdf"
        assert rec["extension"] == "pdf"


class TestRedeem:
    def test_pending_status_before_redeem(self, store):
        upload_id, _, _ = store.create(OWNER, "cv.pdf")
        rec = store.get(upload_id, OWNER)
        assert rec["status"] == "pending"
        assert rec["data"] is None
        assert rec["size"] is None
        assert rec["sha256"] is None
        assert rec["file_id"] is None

    def test_redeem_happy_path(self, store):
        data = b"%PDF-1.4 some bytes"
        upload_id, token, _ = store.create(OWNER, "Jane CV.pdf")
        result = store.redeem(token, "abcd1234-Jane CV.pdf", data)
        assert result == {"upload_id": upload_id, "filename": "Jane CV.pdf", "size": len(data)}

        rec = store.get(upload_id, OWNER)
        assert rec["status"] == "received"
        assert rec["data"] == data
        assert rec["size"] == len(data)
        assert rec["sha256"] == hashlib.sha256(data).hexdigest()
        assert rec["format"] == "pdf"
        assert rec["extension"] == "pdf"
        assert rec["filename"] == "Jane CV.pdf"

    def test_redeem_is_single_use(self, store):
        _, token, _ = store.create(OWNER, "cv.pdf")
        store.redeem(token, "cv.pdf", b"one")
        with pytest.raises(UploadAlreadyUsed) as exc:
            store.redeem(token, "cv.pdf", b"two")
        assert exc.value.http_status == 410

    def test_unknown_token_not_found(self, store):
        with pytest.raises(UploadNotFound) as exc:
            store.redeem("no-such-token", "cv.pdf", b"x")
        assert exc.value.http_status == 404

    def test_ticket_expires_after_15_minutes(self, clock):
        assert TICKET_TTL_SECONDS == 15 * 60

        early = UploadStore(clock=clock)
        _, early_token, _ = early.create(OWNER, "cv.pdf")
        late = UploadStore(clock=clock)
        late_id, late_token, _ = late.create(OWNER, "cv.pdf")

        clock.advance(TICKET_TTL_SECONDS - 0.1)
        assert early.redeem(early_token, "cv.pdf", b"x")["size"] == 1

        clock.advance(0.1)
        with pytest.raises(UploadExpired) as exc:
            late.redeem(late_token, "cv.pdf", b"x")
        assert exc.value.http_status == 410
        assert late.get(late_id, OWNER)["status"] == "expired"

    def test_received_file_purged_after_30_minutes(self, store, clock):
        assert FILE_TTL_SECONDS == 30 * 60
        upload_id = _received(store)

        clock.advance(FILE_TTL_SECONDS - 1)
        assert store.get(upload_id, OWNER)["status"] == "received"

        clock.advance(1)
        rec = store.get(upload_id, OWNER)
        assert rec["status"] == "expired"
        assert rec["data"] is None

    def test_oversize_rejected(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf")
        with pytest.raises(UploadTooLarge) as exc:
            store.redeem(token, "cv.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))
        assert exc.value.http_status == 413
        assert store.get(upload_id, OWNER)["status"] == "pending"

        result = store.redeem(token, "cv.pdf", b"x" * MAX_UPLOAD_BYTES)
        assert result["size"] == MAX_UPLOAD_BYTES

    def test_extension_mismatch_rejected_at_redeem(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf")
        with pytest.raises(UploadBadType) as exc:
            store.redeem(token, "cv.docx", b"data")
        assert exc.value.http_status == 415
        assert store.get(upload_id, OWNER)["status"] == "pending"
        assert store.redeem(token, "cv.pdf", b"data")["size"] == 4

    def test_empty_file_rejected(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf")
        with pytest.raises(UploadEmpty) as exc:
            store.redeem(token, "cv.pdf", b"")
        assert exc.value.http_status == 400
        assert store.get(upload_id, OWNER)["status"] == "pending"


class TestCheckToken:
    def test_check_token_matches_redeem_errors(self, store, clock):
        with pytest.raises(UploadNotFound):
            store.check_token("unknown")

        # A valid ticket passes and is not consumed.
        _, token, _ = store.create(OWNER, "cv.pdf")
        assert store.check_token(token) is None
        assert store.check_token(token) is None
        assert store.redeem(token, "cv.pdf", b"x")["size"] == 1

        # Used.
        with pytest.raises(UploadAlreadyUsed):
            store.check_token(token)

        # Expired.
        _, token2, _ = store.create(OWNER, "cv.pdf")
        clock.advance(TICKET_TTL_SECONDS)
        with pytest.raises(UploadExpired):
            store.check_token(token2)


class TestReissue:
    def test_reissue_token_invalidates_old_and_resets_window(self, store, clock):
        upload_id, old_token, _ = store.create(OWNER, "cv.pdf")
        clock.advance(TICKET_TTL_SECONDS - 60)

        new_token, expires_at = store.reissue_token(upload_id, OWNER)
        assert new_token != old_token
        assert expires_at.tzinfo is not None
        with pytest.raises(UploadNotFound):
            store.redeem(old_token, "cv.pdf", b"x")

        # Window was reset: still valid past the original deadline.
        clock.advance(120)
        assert store.redeem(new_token, "cv.pdf", b"x")["upload_id"] == upload_id

        # Received upload cannot be reissued.
        with pytest.raises(UploadAlreadyUsed):
            store.reissue_token(upload_id, OWNER)

    def test_reissue_for_other_sub_not_found(self, store):
        upload_id, token, _ = store.create(OWNER, "cv.pdf")
        with pytest.raises(UploadNotFound):
            store.reissue_token(upload_id, OTHER)
        with pytest.raises(UploadNotFound):
            store.reissue_token(upload_id, "")
        # Original token untouched.
        assert store.redeem(token, "cv.pdf", b"x")["size"] == 1

    def test_reissue_after_expiry_raises_expired(self, store, clock):
        upload_id, _, _ = store.create(OWNER, "cv.pdf")
        clock.advance(TICKET_TTL_SECONDS)
        with pytest.raises(UploadExpired):
            store.reissue_token(upload_id, OWNER)


class TestGetAndAttach:
    def test_other_user_cannot_get(self, store):
        upload_id = _received(store)
        with pytest.raises(UploadNotFound) as exc:
            store.get(upload_id, OTHER)
        assert exc.value.http_status == 404
        with pytest.raises(UploadNotFound):
            store.get(upload_id, "")

    def test_mark_attached_drops_bytes(self, store, clock):
        upload_id = _received(store)
        store.mark_attached(upload_id, file_id=987)

        rec = store.get(upload_id, OWNER)
        assert rec["status"] == "attached"
        assert rec["data"] is None
        assert rec["file_id"] == 987

        clock.advance(FILE_TTL_SECONDS)
        with pytest.raises(UploadNotFound):
            store.get(upload_id, OWNER)

    def test_mark_attached_unknown_id_is_noop(self, store):
        assert store.mark_attached("upl_missing", file_id=1) is None


class TestOpenUploadCap:
    def test_cap_blocks_extra_ticket_for_same_user_only(self, store):
        for _ in range(MAX_OPEN_UPLOADS_PER_USER):
            store.create(OWNER, "cv.pdf")
        with pytest.raises(UploadLimitReached) as exc:
            store.create(OWNER, "cv.pdf")
        assert exc.value.code == "too_many_uploads"
        assert exc.value.http_status == 429
        store.create(OTHER, "cv.pdf")  # another user is unaffected

    def test_attached_and_expired_uploads_free_a_slot(self, store, clock):
        first = _received(store)
        for _ in range(MAX_OPEN_UPLOADS_PER_USER - 1):
            store.create(OWNER, "cv.pdf")
        store.mark_attached(first, file_id=1)
        store.create(OWNER, "cv.pdf")  # the attached one no longer counts

        clock.advance(TICKET_TTL_SECONDS)
        store.create(OWNER, "cv.pdf")  # expired tickets no longer count


class TestClaim:
    def test_second_claim_refused_until_release(self, store):
        upload_id = _received(store)
        store.claim(upload_id, OWNER)
        with pytest.raises(UploadInUse) as exc:
            store.claim(upload_id, OWNER)
        assert exc.value.code == "upload_in_use"

        store.release(upload_id)
        store.claim(upload_id, OWNER)

    def test_other_user_cannot_claim(self, store):
        upload_id = _received(store)
        with pytest.raises(UploadNotFound):
            store.claim(upload_id, OTHER)

    def test_release_unclaimed_is_noop(self, store):
        assert store.release("upl_missing") is None


class TestHelpers:
    def test_parser_format_mapping(self):
        assert parser_format("txt") == "text"
        assert parser_format("htm") == "html"
        assert parser_format("html") == "html"
        assert parser_format("pdf") == "pdf"
        assert parser_format("docx") == "docx"

    def test_reset_upload_store_clears_singleton(self):
        uploads._reset_upload_store()
        upload_id, token, _ = uploads.upload_store.create(OWNER, "cv.pdf")
        assert uploads.upload_store.get(upload_id, OWNER)["status"] == "pending"

        uploads._reset_upload_store()
        assert uploads.upload_store._uploads == {}
        assert uploads.upload_store._by_token == {}
        with pytest.raises(UploadNotFound):
            uploads.upload_store.get(upload_id, OWNER)
        with pytest.raises(UploadNotFound):
            uploads.upload_store.check_token(token)
