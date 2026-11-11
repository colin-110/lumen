"""The local-disk storage backend: round trip, cleanup, and path containment."""

from __future__ import annotations

import pytest

from app.services.storage import LocalStorageService


@pytest.fixture
def store(tmp_path):
    return LocalStorageService(str(tmp_path / "docs"))


async def test_round_trip(store, tmp_path):
    assert await store.ensure_bucket()
    key = "org-1/doc-1/handbook.txt"
    assert await store.upload_file(b"Refunds within 30 days.", key, "text/plain")

    out = tmp_path / "out.txt"
    assert await store.download_file(key, str(out))
    assert out.read_bytes() == b"Refunds within 30 days."


async def test_upload_leaves_no_partial_file(store):
    await store.ensure_bucket()
    await store.upload_file(b"x", "org/doc/a.txt")
    assert [p.name for p in (store.root / "org" / "doc").iterdir()] == ["a.txt"]


async def test_delete_removes_file_and_empty_directories(store):
    await store.ensure_bucket()
    await store.upload_file(b"a", "org/doc-a/a.txt")
    await store.upload_file(b"b", "org/doc-b/b.txt")

    assert await store.delete_file("org/doc-a/a.txt")
    assert not (store.root / "org" / "doc-a").exists()
    # A sibling document in the same tenant directory is untouched.
    assert (store.root / "org" / "doc-b" / "b.txt").read_bytes() == b"b"
    assert store.root.exists()


async def test_deleting_a_missing_file_is_not_an_error(store):
    await store.ensure_bucket()
    assert await store.delete_file("org/doc/never-existed.txt")


@pytest.mark.parametrize(
    "key",
    ["../escape.txt", "org/doc/../../../escape.txt", "/etc/passwd", "org/../.."],
)
async def test_names_that_escape_the_root_are_refused(store, tmp_path, key):
    await store.ensure_bucket()
    assert not await store.upload_file(b"pwned", key)
    assert not (tmp_path / "escape.txt").exists()
    assert not await store.download_file(key, str(tmp_path / "out"))
