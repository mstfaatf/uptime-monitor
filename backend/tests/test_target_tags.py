"""POST/DELETE /targets/{id}/tags[/{tag_id}] (attach/detach), tags in GET /targets' response,
and the ?tag= filter (Phase 6, prompt 6.4). Tag CRUD itself is covered in test_tags.py.
"""


async def _register(client, email="tagtarget@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200


async def _create_target(client, url="https://example.com/tagtarget"):
    resp = await client.post("/targets", json={"url": url})
    assert resp.status_code == 201
    return resp.json()


async def _create_tag(client, name="production"):
    resp = await client.post("/tags", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


async def test_new_target_has_no_tags(client):
    await _register(client)
    target = await _create_target(client)
    assert target["tags"] == []


async def test_attach_tag_to_target(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)

    resp = await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert [t["id"] for t in body["tags"]] == [tag["id"]]
    assert body["tags"][0]["name"] == "production"


async def test_attach_tag_is_idempotent(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)

    first = await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})
    second = await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(second.json()["tags"]) == 1  # not duplicated


async def test_attach_multiple_tags_to_one_target(client):
    await _register(client)
    target = await _create_target(client)
    tag_a = await _create_tag(client, "frontend")
    tag_b = await _create_tag(client, "critical")

    await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag_a["id"]})
    resp = await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag_b["id"]})
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tags"]}
    assert names == {"frontend", "critical"}


async def test_detach_tag_removes_it(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)
    await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})

    detach = await client.delete(f"/targets/{target['id']}/tags/{tag['id']}")
    assert detach.status_code == 204

    listing = await client.get("/targets")
    assert listing.json()[0]["tags"] == []


async def test_detach_tag_not_currently_attached_is_a_no_op(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)  # never attached

    resp = await client.delete(f"/targets/{target['id']}/tags/{tag['id']}")
    assert resp.status_code == 204


async def test_attach_nonexistent_tag_returns_404(client):
    await _register(client)
    target = await _create_target(client)

    resp = await client.post(f"/targets/{target['id']}/tags", json={"tag_id": 999999})
    assert resp.status_code == 404


async def test_detach_nonexistent_tag_returns_404(client):
    await _register(client)
    target = await _create_target(client)

    resp = await client.delete(f"/targets/{target['id']}/tags/999999")
    assert resp.status_code == 404


async def test_cannot_attach_another_users_tag_to_own_target(client):
    """The scenario the prompt calls out explicitly: user A's target, user B's tag."""
    await _register(client, "tag-user-b@example.com")
    other_tag = await _create_tag(client, "not-yours")
    await client.post("/auth/logout")

    await _register(client, "tag-user-a@example.com")
    own_target = await _create_target(client, "https://example.com/a-owns-this")

    resp = await client.post(f"/targets/{own_target['id']}/tags", json={"tag_id": other_tag["id"]})
    assert resp.status_code == 404

    # Confirm it really wasn't attached.
    listing = await client.get("/targets")
    assert listing.json()[0]["tags"] == []


async def test_cannot_attach_own_tag_to_another_users_target(client):
    """The reverse: user A's tag, user B's target — ownership must be enforced on the target
    side too, not just the tag side."""
    await _register(client, "tag-user-c@example.com")
    other_target = await _create_target(client, "https://example.com/c-owns-this")
    await client.post("/auth/logout")

    await _register(client, "tag-user-d@example.com")
    own_tag = await _create_tag(client, "d-owns-this")

    resp = await client.post(f"/targets/{other_target['id']}/tags", json={"tag_id": own_tag["id"]})
    assert resp.status_code == 404


async def test_cannot_detach_another_users_tag_from_own_target(client):
    await _register(client, "tag-user-e@example.com")
    other_tag = await _create_tag(client, "e-tag")
    await client.post("/auth/logout")

    await _register(client, "tag-user-f@example.com")
    own_target = await _create_target(client, "https://example.com/f-owns-this")

    resp = await client.delete(f"/targets/{own_target['id']}/tags/{other_tag['id']}")
    assert resp.status_code == 404


async def test_user_cannot_see_another_users_tags_via_target_list(client):
    """The list-side ownership scenario the prompt calls out: user A's target list must never
    surface user B's tags, even indirectly."""
    await _register(client, "tag-user-g@example.com")
    target_g = await _create_target(client, "https://example.com/g-owns-this")
    tag_g = await _create_tag(client, "g-private")
    await client.post(f"/targets/{target_g['id']}/tags", json={"tag_id": tag_g["id"]})
    await client.post("/auth/logout")

    await _register(client, "tag-user-h@example.com")
    listing = await client.get("/targets")
    assert listing.status_code == 200
    assert listing.json() == []  # user H owns no targets — g's tagged target never appears

    tags_listing = await client.get("/tags")
    assert tags_listing.json() == []  # and never sees g's tag directly either


async def test_filter_by_tag_returns_correct_subset(client):
    await _register(client)
    prod_tag = await _create_tag(client, "production")
    await _create_tag(client, "staging")  # exists but nothing tagged with it

    target_a = await _create_target(client, "https://example.com/filter-a")
    target_b = await _create_target(client, "https://example.com/filter-b")
    target_c = await _create_target(client, "https://example.com/filter-c")
    await client.post(f"/targets/{target_a['id']}/tags", json={"tag_id": prod_tag["id"]})
    await client.post(f"/targets/{target_b['id']}/tags", json={"tag_id": prod_tag["id"]})
    # target_c deliberately left untagged

    resp = await client.get("/targets", params={"tag": "production"})
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert ids == {target_a["id"], target_b["id"]}

    # Every returned target's full tags list is present, not just the filtered-on tag.
    for t in resp.json():
        assert any(tag["name"] == "production" for tag in t["tags"])


async def test_filter_by_tag_with_no_matches_returns_empty(client):
    await _register(client)
    await _create_target(client)
    resp = await client.get("/targets", params={"tag": "nonexistent-tag"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_filter_by_tag_only_returns_callers_own_targets_even_with_same_tag_name(client):
    """Two users can each have a tag named "production" (uniqueness is per-user) — filtering
    must never cross that boundary."""
    await _register(client, "tag-filter-a@example.com")
    tag_a = await _create_tag(client, "production")
    target_a = await _create_target(client, "https://example.com/filter-user-a")
    await client.post(f"/targets/{target_a['id']}/tags", json={"tag_id": tag_a["id"]})
    await client.post("/auth/logout")

    await _register(client, "tag-filter-b@example.com")
    tag_b = await _create_tag(client, "production")
    target_b = await _create_target(client, "https://example.com/filter-user-b")
    await client.post(f"/targets/{target_b['id']}/tags", json={"tag_id": tag_b["id"]})

    resp = await client.get("/targets", params={"tag": "production"})
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == [target_b["id"]]  # only the currently-logged-in user's own match


async def test_deleting_a_tag_detaches_it_from_every_target(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)
    await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})

    delete_resp = await client.delete(f"/tags/{tag['id']}")
    assert delete_resp.status_code == 204

    listing = await client.get("/targets")
    assert listing.json()[0]["tags"] == []


async def test_deleting_a_target_does_not_delete_its_tags(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)
    await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})

    delete_resp = await client.delete(f"/targets/{target['id']}")
    assert delete_resp.status_code == 204

    tags_listing = await client.get("/tags")
    assert [t["name"] for t in tags_listing.json()] == ["production"]


async def test_attach_and_detach_require_authentication(client):
    await _register(client)
    target = await _create_target(client)
    tag = await _create_tag(client)
    await client.post("/auth/logout")

    assert (
        await client.post(f"/targets/{target['id']}/tags", json={"tag_id": tag["id"]})
    ).status_code == 401
    assert (await client.delete(f"/targets/{target['id']}/tags/{tag['id']}")).status_code == 401
