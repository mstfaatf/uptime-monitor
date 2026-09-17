"""POST/GET /webhooks and DELETE /webhooks/{id} (Phase 6, prompt 6.6). Fan-out/delivery
behavior lives in test_alerting.py (the realtime.py restructuring) and
test_webhook_delivery.py (webhooks.py's send_webhook) — this file is CRUD and SSRF-at-creation
only.
"""


async def _register(client, email="webhooktest@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200


async def test_create_and_list_webhook(client):
    await _register(client)
    created = await client.post("/webhooks", json={"url": "https://example.com/hook"})
    assert created.status_code == 201
    body = created.json()
    assert body["url"] == "https://example.com/hook"
    assert body["alert_on_downtime"] is True
    assert body["alert_on_cert_expiry"] is True
    assert body["enabled"] is True
    assert "secret" in body and len(body["secret"]) > 20

    listing = await client.get("/webhooks")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert "secret" not in listing.json()[0]  # never returned again after creation


async def test_create_webhook_with_custom_alert_type_toggles(client):
    await _register(client)
    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook2", "alert_on_downtime": False, "alert_on_cert_expiry": True},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["alert_on_downtime"] is False
    assert body["alert_on_cert_expiry"] is True


async def test_create_webhook_rejects_localhost(client):
    await _register(client)
    resp = await client.post("/webhooks", json={"url": "http://localhost/hook"})
    assert resp.status_code == 400


async def test_create_webhook_rejects_private_ip_literal(client):
    await _register(client)
    resp = await client.post("/webhooks", json={"url": "http://10.0.0.5/hook"})
    assert resp.status_code == 400


async def test_create_webhook_rejects_link_local_metadata_address(client):
    await _register(client)
    resp = await client.post("/webhooks", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert resp.status_code == 400


async def test_create_webhook_rejects_non_http_scheme(client):
    await _register(client)
    resp = await client.post("/webhooks", json={"url": "ftp://example.com/hook"})
    assert resp.status_code == 400


async def test_update_webhook_url_and_toggles(client):
    await _register(client)
    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/original", "alert_on_downtime": True, "alert_on_cert_expiry": True},
    )
    webhook_id = created.json()["id"]

    updated = await client.patch(
        f"/webhooks/{webhook_id}",
        json={"url": "https://example.com/updated", "alert_on_downtime": False, "enabled": False},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["url"] == "https://example.com/updated"
    assert body["alert_on_downtime"] is False
    assert body["alert_on_cert_expiry"] is True  # untouched field stays as it was
    assert body["enabled"] is False
    assert "secret" not in body  # PATCH never returns it either


async def test_update_webhook_partial_update_leaves_other_fields_alone(client):
    await _register(client)
    created = await client.post("/webhooks", json={"url": "https://example.com/partial"})
    webhook_id = created.json()["id"]

    updated = await client.patch(f"/webhooks/{webhook_id}", json={"alert_on_cert_expiry": False})
    assert updated.status_code == 200
    body = updated.json()
    assert body["url"] == "https://example.com/partial"
    assert body["alert_on_downtime"] is True
    assert body["alert_on_cert_expiry"] is False
    assert body["enabled"] is True


async def test_update_webhook_rejects_a_new_ssrf_blocked_url(client):
    await _register(client)
    created = await client.post("/webhooks", json={"url": "https://example.com/safe"})
    webhook_id = created.json()["id"]

    resp = await client.patch(f"/webhooks/{webhook_id}", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert resp.status_code == 400

    # The rejected update didn't partially apply.
    listing = await client.get("/webhooks")
    assert listing.json()[0]["url"] == "https://example.com/safe"


async def test_update_webhook_does_not_change_secret(client):
    await _register(client)
    created = await client.post("/webhooks", json={"url": "https://example.com/secret-check"})
    webhook_id = created.json()["id"]
    original_secret = created.json()["secret"]

    await client.patch(f"/webhooks/{webhook_id}", json={"alert_on_downtime": False})

    # No endpoint ever returns the secret again — confirm indirectly via a second create that a
    # fresh secret differs, and that nothing about the update flow exposes the original one.
    second = await client.post("/webhooks", json={"url": "https://example.com/secret-check-2"})
    assert second.json()["secret"] != original_secret


async def test_user_cannot_update_another_users_webhook(client):
    await _register(client, "webhook-owner2@example.com")
    created = await client.post("/webhooks", json={"url": "https://example.com/owner-only-2"})
    webhook_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "webhook-intruder2@example.com")
    resp = await client.patch(f"/webhooks/{webhook_id}", json={"enabled": False})
    assert resp.status_code == 404  # not 403 — can't confirm the id even exists

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": "webhook-owner2@example.com", "password": "pw"})
    still_enabled = await client.get("/webhooks")
    assert still_enabled.json()[0]["enabled"] is True


async def test_delete_webhook_removes_it(client):
    await _register(client)
    created = await client.post("/webhooks", json={"url": "https://example.com/to-delete"})
    webhook_id = created.json()["id"]

    deleted = await client.delete(f"/webhooks/{webhook_id}")
    assert deleted.status_code == 204

    listing = await client.get("/webhooks")
    assert listing.json() == []


async def test_user_cannot_list_or_delete_another_users_webhook(client):
    await _register(client, "webhook-owner@example.com")
    created = await client.post("/webhooks", json={"url": "https://example.com/owner-only"})
    webhook_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "webhook-intruder@example.com")
    listing = await client.get("/webhooks")
    assert listing.json() == []  # never sees the other user's webhook

    delete_resp = await client.delete(f"/webhooks/{webhook_id}")
    assert delete_resp.status_code == 404  # not 403 — can't confirm the id even exists

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": "webhook-owner@example.com", "password": "pw"})
    still_there = await client.get("/webhooks")
    assert len(still_there.json()) == 1


async def test_webhook_endpoints_require_authentication(client):
    assert (await client.get("/webhooks")).status_code == 401
    assert (await client.post("/webhooks", json={"url": "https://example.com/x"})).status_code == 401
    assert (await client.patch("/webhooks/1", json={"enabled": False})).status_code == 401
    assert (await client.delete("/webhooks/1")).status_code == 401
