"""POST /targets and PATCH /targets/{id}'s request-customization fields (Phase 6, prompt 6.2):
custom method/headers/basic-auth/keyword-match. Worker-side behavior (what actually happens
with these fields during a check) is covered in worker/tests/test_request_customization.py —
this file is about validation and the API contract only.
"""

import pytest


async def _register(client, email="customizer@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200
    return resp


async def test_create_target_with_no_customization_behaves_as_before(client):
    await _register(client)
    resp = await client.post("/targets", json={"url": "https://example.com/plain"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["request_method"] is None
    assert body["request_headers"] is None
    assert body["basic_auth_username"] is None
    assert body["keyword_match"] is None
    assert body["keyword_match_mode"] == "contains"
    assert "basic_auth_password" not in body
    assert "basic_auth_password_encrypted" not in body


async def test_create_target_with_custom_method_and_headers(client):
    await _register(client)
    resp = await client.post(
        "/targets",
        json={
            "url": "https://example.com/api",
            "request_method": "POST",
            "request_headers": {"X-Api-Key": "abc123"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["request_method"] == "POST"
    assert body["request_headers"] == {"X-Api-Key": "abc123"}


async def test_create_target_with_invalid_method_rejected(client):
    await _register(client)
    resp = await client.post("/targets", json={"url": "https://example.com/x", "request_method": "DELETE"})
    assert resp.status_code == 400


async def test_create_target_with_head_and_keyword_match_rejected(client):
    """HEAD has no response body — keyword_match requires a body to check against."""
    await _register(client)
    resp = await client.post(
        "/targets",
        json={"url": "https://example.com/x", "request_method": "HEAD", "keyword_match": "OK"},
    )
    assert resp.status_code == 400
    assert "keyword_match" in resp.json()["detail"]


async def test_create_target_with_invalid_keyword_match_mode_rejected(client):
    await _register(client)
    resp = await client.post(
        "/targets",
        json={"url": "https://example.com/x", "keyword_match": "OK", "keyword_match_mode": "sometimes"},
    )
    assert resp.status_code == 400


async def test_create_target_with_basic_auth_username_but_no_password_rejected(client):
    await _register(client)
    resp = await client.post(
        "/targets", json={"url": "https://example.com/x", "basic_auth_username": "user"}
    )
    assert resp.status_code == 400


async def test_create_target_with_basic_auth_password_but_no_username_rejected(client):
    await _register(client)
    resp = await client.post(
        "/targets", json={"url": "https://example.com/x", "basic_auth_password": "secret"}
    )
    assert resp.status_code == 400


async def test_create_target_with_basic_auth_stores_username_and_never_returns_password(client):
    await _register(client)
    resp = await client.post(
        "/targets",
        json={
            "url": "https://example.com/protected",
            "basic_auth_username": "admin",
            "basic_auth_password": "hunter2",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["basic_auth_username"] == "admin"
    assert "basic_auth_password" not in body
    assert "basic_auth_password_encrypted" not in body
    assert "hunter2" not in resp.text  # the plaintext password never appears anywhere in the response


async def test_create_target_with_keyword_match_default_mode(client):
    await _register(client)
    resp = await client.post(
        "/targets", json={"url": "https://example.com/status", "keyword_match": "healthy"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["keyword_match"] == "healthy"
    assert body["keyword_match_mode"] == "contains"


async def test_create_target_with_not_contains_mode(client):
    await _register(client)
    resp = await client.post(
        "/targets",
        json={
            "url": "https://example.com/status2",
            "keyword_match": "maintenance",
            "keyword_match_mode": "not_contains",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["keyword_match_mode"] == "not_contains"


@pytest.fixture
async def target_id(client):
    await _register(client)
    resp = await client.post("/targets", json={"url": "https://example.com/editable"})
    return resp.json()["id"]


async def test_patch_updates_only_provided_fields(client, target_id):
    resp = await client.patch(f"/targets/{target_id}", json={"request_method": "GET"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_method"] == "GET"
    assert body["name"] is None  # untouched, still default

    # A second PATCH touching a different field must not have disturbed the first change.
    resp2 = await client.patch(f"/targets/{target_id}", json={"name": "Editable target"})
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["name"] == "Editable target"
    assert body2["request_method"] == "GET"  # still set from the earlier PATCH


async def test_patch_can_explicitly_clear_keyword_match(client, target_id):
    set_resp = await client.patch(f"/targets/{target_id}", json={"keyword_match": "ok"})
    assert set_resp.json()["keyword_match"] == "ok"

    clear_resp = await client.patch(f"/targets/{target_id}", json={"keyword_match": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["keyword_match"] is None


async def test_patch_head_plus_existing_keyword_match_rejected(client, target_id):
    await client.patch(f"/targets/{target_id}", json={"keyword_match": "ok"})
    resp = await client.patch(f"/targets/{target_id}", json={"request_method": "HEAD"})
    assert resp.status_code == 400


async def test_patch_basic_auth_password_blank_means_unchanged(client, target_id):
    """The edit-form UX: the username is shown back, the password never is — omitting or
    blanking basic_auth_password on a later PATCH must leave the previously-stored password
    untouched, not clear it (clearing basic auth entirely requires clearing the username)."""
    set_resp = await client.patch(
        f"/targets/{target_id}",
        json={"basic_auth_username": "admin", "basic_auth_password": "first-password"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["basic_auth_username"] == "admin"

    # Rename the username without resending a password — must not be rejected, and must not
    # clear the stored password (there's no way to observe the encrypted value directly via
    # the API, but a bare username-only PATCH must succeed exactly because the existing
    # password is still considered "set" underneath).
    rename_resp = await client.patch(f"/targets/{target_id}", json={"basic_auth_username": "admin2"})
    assert rename_resp.status_code == 200
    assert rename_resp.json()["basic_auth_username"] == "admin2"


async def test_patch_clearing_basic_auth_username_removes_basic_auth_entirely(client, target_id):
    await client.patch(
        f"/targets/{target_id}",
        json={"basic_auth_username": "admin", "basic_auth_password": "pw"},
    )
    resp = await client.patch(f"/targets/{target_id}", json={"basic_auth_username": None})
    assert resp.status_code == 200
    assert resp.json()["basic_auth_username"] is None


async def test_patch_password_without_any_username_rejected(client, target_id):
    resp = await client.patch(f"/targets/{target_id}", json={"basic_auth_password": "pw"})
    assert resp.status_code == 400


async def test_patch_nonexistent_or_unowned_target_returns_404(client, target_id):
    resp = await client.patch("/targets/999999", json={"name": "nope"})
    assert resp.status_code == 404
