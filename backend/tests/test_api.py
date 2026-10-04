"""Tests for every Study Pulse API endpoint, with extra focus on anonymity."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import radar

FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()


def struggle(client, h, cid, **kw):
    body = {"type": "struggle", "content": "Stuck on moment of inertia", "topic": "Moment of inertia", **kw}
    return client.post(f"/api/classes/{cid}/posts", json=body, headers=h)


# ---------------- auth ----------------
class TestAuth:
    def reg(self, client, **kw):
        return client.post("/api/auth/register", json={"name": "Nia", "password": "secret1", **kw})

    def test_register_with_username_returns_token_and_recovery_code(self, client):
        r = self.reg(client, username="Nia_K")
        assert r.status_code == 201 and r.json()["token"] and r.json()["user"]["username"] == "nia_k"
        assert len(r.json()["recovery_code"]) == 9 and "password" not in json.dumps(r.json())

    def test_register_with_phone_only(self, client):
        r = self.reg(client, phone="+234 916 341 7764")
        assert r.status_code == 201 and r.json()["user"]["username"] is None
        assert client.post("/api/auth/login", json={"identifier": "2349163417764", "password": "secret1"}).status_code == 200
        assert client.post("/api/auth/login", json={"identifier": "+234-916-341-7764", "password": "secret1"}).status_code == 200

    def test_register_needs_username_or_phone(self, client):
        assert self.reg(client).status_code == 422

    @pytest.mark.parametrize("bad", [{"username": "ab"}, {"username": "12345"}, {"username": "has space"}, {"phone": "123"}, {"phone": "abc-def-ghij"}])
    def test_register_validation(self, client, bad):
        assert self.reg(client, **bad).status_code == 422

    def test_short_password_and_empty_name_rejected(self, client):
        assert client.post("/api/auth/register", json={"name": "A", "username": "abc", "password": "123"}).status_code == 422
        assert client.post("/api/auth/register", json={"name": "", "username": "abc", "password": "secret1"}).status_code == 422

    def test_duplicates_conflict(self, client):
        self.reg(client, username="dup_user", phone="+2348011111111")
        assert self.reg(client, username="DUP_user").status_code == 409
        assert self.reg(client, username="other_one", phone="234 801 111 1111").status_code == 409

    def test_login_by_username_or_phone_and_failures(self, client):
        self.reg(client, username="login_me", phone="+2348022222222")
        for ident in ("login_me", "LOGIN_ME", "+234 802 222 2222"):
            assert client.post("/api/auth/login", json={"identifier": ident, "password": "secret1"}).status_code == 200
        assert client.post("/api/auth/login", json={"identifier": "login_me", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"identifier": "nobody", "password": "secret1"}).status_code == 401

    def test_login_is_throttled_after_repeated_failures(self, client):
        self.reg(client, username="brute_me")
        for _ in range(5):
            assert client.post("/api/auth/login", json={"identifier": "brute_me", "password": "bad"}).status_code == 401
        assert client.post("/api/auth/login", json={"identifier": "brute_me", "password": "secret1"}).status_code == 429

    def test_me_requires_valid_token_and_shows_own_contact_only(self, client, make_user):
        h = make_user("Zed")
        me = client.get("/api/me", headers=h).json()
        assert me["name"] == "Zed" and me["username"] == "u_zed"
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code == 401

    def test_contact_details_never_leak_to_classmates(self, client):
        a = self.reg(client, username="secret_poster", phone="+2348033333333", name="Pat Private").json()
        ha = {"Authorization": "Bearer " + a["token"]}
        k = client.post("/api/classes", json={"name": "C"}, headers=ha).json()
        hb = {"Authorization": "Bearer " + self.reg(client, username="viewer_one", name="Vi").json()["token"]}
        client.post("/api/classes/join", json={"code": k["code"]}, headers=hb)
        p = client.post(f"/api/classes/{k['id']}/posts", json={"type": "struggle", "content": "hi", "is_anonymous": True}, headers=ha).json()
        client.post(f"/api/posts/{p['id']}/comments", json={"content": "c", "is_anonymous": True}, headers=ha)
        cid = client.post("/api/conversations", json={"post_id": p["id"]}, headers=hb).json()["id"]
        blob = "".join(client.get(u, headers=hb).text for u in (f"/api/classes/{k['id']}", f"/api/classes/{k['id']}/posts", f"/api/posts/{p['id']}/comments", "/api/conversations", f"/api/conversations/{cid}/messages"))
        assert "secret_poster" not in blob and "2348033333333" not in blob and "Pat" not in blob

    def test_recovery_code_resets_password_once(self, client):
        r = self.reg(client, username="forgetful").json()
        body = {"identifier": "forgetful", "recovery_code": r["recovery_code"].lower(), "password": "newpass1"}
        out = client.post("/api/auth/reset", json=body)
        assert out.status_code == 200 and out.json()["recovery_code"] != r["recovery_code"]
        assert client.post("/api/auth/login", json={"identifier": "forgetful", "password": "newpass1"}).status_code == 200
        assert client.post("/api/auth/login", json={"identifier": "forgetful", "password": "secret1"}).status_code == 401
        assert client.post("/api/auth/reset", json=body).status_code == 400   # old code is dead
        again = {**body, "recovery_code": out.json()["recovery_code"], "password": "third123"}
        assert client.post("/api/auth/reset", json=again).status_code == 200   # new code works

    def test_reset_rejects_wrong_code_unknown_user_short_password(self, client):
        self.reg(client, username="someone")
        assert client.post("/api/auth/reset", json={"identifier": "someone", "recovery_code": "0000-0000", "password": "newpass1"}).status_code == 400
        assert client.post("/api/auth/reset", json={"identifier": "ghost", "recovery_code": "0000-0000", "password": "newpass1"}).status_code == 400
        assert client.post("/api/auth/reset", json={"identifier": "someone", "recovery_code": "x", "password": "1"}).status_code == 422

    def test_reset_is_throttled(self, client):
        self.reg(client, username="guessme")
        for _ in range(5):
            client.post("/api/auth/reset", json={"identifier": "guessme", "recovery_code": "AAAA-AAAA", "password": "newpass1"})
        assert client.post("/api/auth/reset", json={"identifier": "guessme", "recovery_code": "AAAA-AAAA", "password": "newpass1"}).status_code == 429


# ---------------- classes ----------------
class TestClasses:
    def test_create_class_makes_creator_a_member(self, client, make_user):
        h = make_user("Cara")
        r = client.post("/api/classes", json={"name": "Chem", "subject": "Chemistry"}, headers=h)
        assert r.status_code == 201 and len(r.json()["code"]) == 6 and r.json()["member_count"] == 1
        assert r.json()["my_anon_name"].startswith("Anon_")

    def test_join_by_code_is_case_insensitive_and_idempotent(self, client, world, make_user):
        h = make_user("Dan")
        a = client.post("/api/classes/join", json={"code": world["cls"]["code"].lower()}, headers=h)
        b = client.post("/api/classes/join", json={"code": world["cls"]["code"]}, headers=h)
        assert a.status_code == 200 and a.json()["my_anon_name"] == b.json()["my_anon_name"]
        assert b.json()["member_count"] == 3

    def test_join_unknown_code_404(self, client, make_user):
        assert client.post("/api/classes/join", json={"code": "ZZZZZZ"}, headers=make_user("X")).status_code == 404

    def test_anon_names_unique_within_class(self, client, world, make_user):
        names = {world["cls"]["my_anon_name"]}
        for i in range(6):
            h = make_user(f"S{i}", f"s{i}@x.com")
            names.add(client.post("/api/classes/join", json={"code": world["cls"]["code"]}, headers=h).json()["my_anon_name"])
        assert len(names) == 7

    def test_list_classes_only_mine(self, client, world):
        assert [c["id"] for c in client.get("/api/classes", headers=world["bob"]).json()] == [world["cid"]]
        assert client.get("/api/classes", headers=world["eve"]).json() == []

    def test_class_detail_members_only(self, client, world):
        assert client.get(f"/api/classes/{world['cid']}", headers=world["bob"]).status_code == 200
        assert client.get(f"/api/classes/{world['cid']}", headers=world["eve"]).status_code == 403

    def test_endpoints_require_auth(self, client):
        assert client.get("/api/classes").status_code == 401
        assert client.post("/api/classes", json={"name": "x"}).status_code == 401


# ---------------- posts ----------------
class TestPosts:
    def test_create_public_struggle_shows_real_name(self, client, world):
        r = struggle(client, world["alice"], world["cid"])
        assert r.status_code == 201
        j = r.json()
        assert j["display_name"] == "Alice A." and not j["is_anonymous"] and j["is_mine"]

    def test_anonymous_post_hides_name_everywhere(self, client, world):
        r = struggle(client, world["alice"], world["cid"], is_anonymous=True).json()
        assert r["display_name"] == world["cls"]["my_anon_name"] and r["is_anonymous"]
        for h in (world["alice"], world["bob"]):
            feed = client.get(f"/api/classes/{world['cid']}/posts", headers=h).text
            detail = client.get(f"/api/posts/{r['id']}", headers=h).text
            for blob in (feed, detail):
                assert "Alice" not in blob
                assert "author" not in blob and "user_id" not in blob

    def test_is_mine_only_true_for_author(self, client, world):
        p = struggle(client, world["alice"], world["cid"], is_anonymous=True).json()
        assert client.get(f"/api/posts/{p['id']}", headers=world["alice"]).json()["is_mine"] is True
        assert client.get(f"/api/posts/{p['id']}", headers=world["bob"]).json()["is_mine"] is False

    def test_struggle_needs_content(self, client, world):
        assert client.post(f"/api/classes/{world['cid']}/posts", json={"type": "struggle", "content": "  "}, headers=world["alice"]).status_code == 422

    def test_radar_post_needs_title_and_due(self, client, world):
        url = f"/api/classes/{world['cid']}/posts"
        assert client.post(url, json={"type": "radar", "radar_title": "Lab"}, headers=world["alice"]).status_code == 422
        assert client.post(url, json={"type": "radar", "due_at": FUTURE}, headers=world["alice"]).status_code == 422

    def test_radar_post_is_always_public(self, client, world):
        r = client.post(f"/api/classes/{world['cid']}/posts", headers=world["alice"],
                        json={"type": "radar", "radar_title": "Lab report", "due_at": FUTURE, "is_anonymous": True})
        assert r.status_code == 201 and r.json()["is_anonymous"] is False and r.json()["display_name"] == "Alice A."
        assert r.json()["due_at"].endswith("Z")

    def test_feed_is_scoped_to_class_and_members_only(self, client, world):
        other = client.post("/api/classes", json={"name": "Other"}, headers=world["eve"]).json()
        struggle(client, world["eve"], other["id"], content="secret eve post")
        struggle(client, world["alice"], world["cid"])
        feed = client.get(f"/api/classes/{world['cid']}/posts", headers=world["bob"]).json()
        assert len(feed) == 1 and "eve" not in json.dumps(feed).lower()
        assert client.get(f"/api/classes/{world['cid']}/posts", headers=world["eve"]).status_code == 403
        assert client.post(f"/api/classes/{world['cid']}/posts", json={"type": "struggle", "content": "hi"}, headers=world["eve"]).status_code == 403

    def test_feed_filters_by_type_and_topic_and_sorts_deadlines(self, client, world):
        cid, h = world["cid"], world["alice"]
        struggle(client, h, cid, topic="Optics")
        struggle(client, h, cid, topic="Circuits")
        for title, days in (("Late", 5), ("Soon", 1)):
            client.post(f"/api/classes/{cid}/posts", headers=h, json={"type": "radar", "radar_title": title, "due_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()})
        assert len(client.get(f"/api/classes/{cid}/posts?type=struggle", headers=h).json()) == 2
        assert len(client.get(f"/api/classes/{cid}/posts?topic=Optics", headers=h).json()) == 1
        radar_feed = client.get(f"/api/classes/{cid}/posts?type=radar", headers=h).json()
        assert [p["radar_title"] for p in radar_feed] == ["Soon", "Late"]

    def test_get_post_404_and_outsider_403(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        assert client.get("/api/posts/9999", headers=world["alice"]).status_code == 404
        assert client.get(f"/api/posts/{p['id']}", headers=world["eve"]).status_code == 403

    def test_delete_post_author_only_and_cleans_up(self, client, world):
        p = struggle(client, world["alice"], world["cid"], is_anonymous=True).json()
        client.post(f"/api/posts/{p['id']}/comments", json={"content": "hi"}, headers=world["bob"])
        client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"])
        assert client.delete(f"/api/posts/{p['id']}", headers=world["bob"]).status_code == 403
        assert client.delete(f"/api/posts/{p['id']}", headers=world["alice"]).status_code == 204
        assert client.get(f"/api/posts/{p['id']}", headers=world["alice"]).status_code == 404
        assert client.get("/api/conversations", headers=world["bob"]).json() == []

    def test_me_too_toggle_updates_counts(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        r = client.post(f"/api/posts/{p['id']}/me-too", headers=world["bob"])
        assert r.json() == {"active": True, "count": 1}
        assert client.get(f"/api/posts/{p['id']}", headers=world["bob"]).json()["i_said_me_too"] is True
        assert client.get(f"/api/posts/{p['id']}", headers=world["alice"]).json()["i_said_me_too"] is False
        assert client.post(f"/api/posts/{p['id']}/me-too", headers=world["bob"]).json() == {"active": False, "count": 0}

    def test_me_too_outsider_forbidden(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        assert client.post(f"/api/posts/{p['id']}/me-too", headers=world["eve"]).status_code == 403

    def test_hot_topics_ranked_by_me_too(self, client, world):
        cid = world["cid"]
        a = struggle(client, world["alice"], cid, topic="Optics").json()
        b = struggle(client, world["alice"], cid, topic="Circuits").json()
        for h in (world["alice"], world["bob"]):
            client.post(f"/api/posts/{b['id']}/me-too", headers=h)
        client.post(f"/api/posts/{a['id']}/me-too", headers=world["bob"])
        t = client.get(f"/api/classes/{cid}/topics", headers=world["bob"]).json()
        assert t == [{"topic": "Circuits", "stuck_count": 3}, {"topic": "Optics", "stuck_count": 2}]   # posts + Me too taps
        assert client.get(f"/api/classes/{cid}/topics", headers=world["eve"]).status_code == 403

    def test_report_post(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        assert client.post(f"/api/posts/{p['id']}/report", json={"reason": "spam"}, headers=world["bob"]).status_code == 201
        assert client.post(f"/api/posts/{p['id']}/report", json={}, headers=world["eve"]).status_code == 403


# ---------------- comments ----------------
class TestComments:
    def test_comment_and_list(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        r = client.post(f"/api/posts/{p['id']}/comments", json={"content": "Same here"}, headers=world["bob"])
        assert r.status_code == 201 and r.json()["display_name"] == "Bob B."
        lst = client.get(f"/api/posts/{p['id']}/comments", headers=world["alice"]).json()
        assert len(lst) == 1 and lst[0]["is_mine"] is False
        assert client.get(f"/api/posts/{p['id']}", headers=world["alice"]).json()["comment_count"] == 1

    def test_anonymous_comment_hides_identity(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        c = client.post(f"/api/posts/{p['id']}/comments", json={"content": "psst", "is_anonymous": True}, headers=world["bob"]).json()
        blob = client.get(f"/api/posts/{p['id']}/comments", headers=world["alice"]).text
        assert "Bob" not in blob and c["display_name"].startswith("Anon_")

    def test_comment_validation_and_access(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        assert client.post(f"/api/posts/{p['id']}/comments", json={"content": ""}, headers=world["bob"]).status_code == 422
        assert client.post(f"/api/posts/{p['id']}/comments", json={"content": "hi"}, headers=world["eve"]).status_code == 403
        assert client.get(f"/api/posts/{p['id']}/comments", headers=world["eve"]).status_code == 403


# ---------------- radar ----------------
class TestRadar:
    def test_parse_weekday_and_time(self, client, world):
        r = client.post("/api/radar/parse", json={"text": "Chemistry worksheet due Friday 5pm", "timezone": "Africa/Lagos"}, headers=world["alice"]).json()
        assert r["title"] == "Chemistry worksheet" and r["needs_clarification"] is False
        d = datetime.fromisoformat(r["due_date"])
        assert d.weekday() == 4 and (d.hour, d.minute) == (17, 0) and d.utcoffset() == timedelta(hours=1)

    def test_parse_tomorrow_defaults_to_end_of_day(self):
        now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
        r = radar.fallback("Read chapter 4 tomorrow", "UTC", now)
        assert r["due_date"].startswith("2026-10-03T23:59")

    def test_parse_explicit_dates_both_orders(self):
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        assert radar.fallback("Essay due 12 Oct 9am", "UTC", now)["due_date"].startswith("2026-10-12T09:00")
        assert radar.fallback("Essay due October 12", "UTC", now)["due_date"].startswith("2026-10-12T23:59")
        assert radar.fallback("Quiz on Jan 5", "UTC", now)["due_date"].startswith("2027-01-05")

    def test_missing_date_needs_clarification(self, client, world):
        r = client.post("/api/radar/parse", json={"text": "maths homework"}, headers=world["alice"]).json()
        assert r["due_date"] is None and r["needs_clarification"] is True

    def test_empty_input_rejected_and_auth_required(self, client, world):
        assert client.post("/api/radar/parse", json={"text": " "}, headers=world["alice"]).status_code == 422
        assert client.post("/api/radar/parse", json={"text": "x due friday"}).status_code == 401

    def test_bad_timezone_falls_back_to_utc(self):
        assert radar.fallback("Lab due friday", "Not/AZone")["due_date"]

    def test_image_input_accepted(self, client, world):
        r = client.post("/api/radar/parse", json={"image_base64": "aGVsbG8=", "media_type": "image/png"}, headers=world["alice"])
        assert r.status_code == 200 and "needs_clarification" in r.json()


# ---------------- private deadlines ----------------
class TestDeadlines:
    def test_crud_and_privacy(self, client, world):
        cid = world["cid"]
        r = client.post(f"/api/classes/{cid}/deadlines", json={"title": "Read ch4", "due_at": FUTURE}, headers=world["alice"])
        assert r.status_code == 201
        assert len(client.get(f"/api/classes/{cid}/deadlines", headers=world["alice"]).json()) == 1
        assert client.get(f"/api/classes/{cid}/deadlines", headers=world["bob"]).json() == []
        assert client.delete(f"/api/deadlines/{r.json()['id']}", headers=world["bob"]).status_code == 404
        assert client.delete(f"/api/deadlines/{r.json()['id']}", headers=world["alice"]).status_code == 204
        assert client.get(f"/api/classes/{cid}/deadlines", headers=world["alice"]).json() == []

    def test_requires_membership_and_valid_body(self, client, world):
        cid = world["cid"]
        assert client.post(f"/api/classes/{cid}/deadlines", json={"title": "x", "due_at": FUTURE}, headers=world["eve"]).status_code == 403
        assert client.post(f"/api/classes/{cid}/deadlines", json={"title": "", "due_at": FUTURE}, headers=world["alice"]).status_code == 422
        assert client.get(f"/api/classes/{cid}/deadlines", headers=world["eve"]).status_code == 403

    def test_sorted_by_due_date(self, client, world):
        cid, h = world["cid"], world["alice"]
        for t, d in (("B", 4), ("A", 1)):
            client.post(f"/api/classes/{cid}/deadlines", json={"title": t, "due_at": (datetime.now(timezone.utc) + timedelta(days=d)).isoformat()}, headers=h)
        assert [x["title"] for x in client.get(f"/api/classes/{cid}/deadlines", headers=h).json()] == ["A", "B"]


# ---------------- direct messages ----------------
class TestConversations:
    def anon_post(self, client, world):
        return struggle(client, world["alice"], world["cid"], is_anonymous=True).json()

    def test_dm_to_anonymous_poster_shows_anonymous_student(self, client, world):
        p = self.anon_post(client, world)
        r = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"])
        assert r.status_code == 201
        c = r.json()
        assert c["other_label"] == "Anonymous student" and c["other_hidden"] is True and c["me_anon"] is False
        assert "Alice" not in r.text

    def test_start_is_idempotent(self, client, world):
        p = self.anon_post(client, world)
        a = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()
        b = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()
        assert a["id"] == b["id"] and len(client.get("/api/conversations", headers=world["bob"]).json()) == 1

    def test_cannot_message_yourself_or_outsiders(self, client, world):
        p = self.anon_post(client, world)
        assert client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["alice"]).status_code == 400
        assert client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["eve"]).status_code == 403
        assert client.post("/api/conversations", json={"post_id": 999}, headers=world["bob"]).status_code == 404

    def test_two_way_chat_and_message_ownership(self, client, world):
        p = self.anon_post(client, world)
        cid = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()["id"]
        client.post(f"/api/conversations/{cid}/messages", json={"content": "Want to study?"}, headers=world["bob"])
        client.post(f"/api/conversations/{cid}/messages", json={"content": "Yes please"}, headers=world["alice"])
        bob = client.get(f"/api/conversations/{cid}/messages", headers=world["bob"]).json()
        alice = client.get(f"/api/conversations/{cid}/messages", headers=world["alice"]).json()
        assert [m["is_mine"] for m in bob["messages"]] == [True, False]
        assert [m["is_mine"] for m in alice["messages"]] == [False, True]
        assert "sender" not in json.dumps(bob)
        assert alice["conversation"]["other_label"] == "Bob B." and alice["conversation"]["me_anon"] is True

    def test_non_participant_cannot_read_or_write(self, client, world):
        p = self.anon_post(client, world)
        cid = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()["id"]
        assert client.get(f"/api/conversations/{cid}/messages", headers=world["eve"]).status_code == 404
        assert client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}, headers=world["eve"]).status_code == 404
        assert client.post(f"/api/conversations/{cid}/reveal", headers=world["eve"]).status_code == 404
        assert client.get("/api/conversations", headers=world["eve"]).json() == []

    def test_empty_message_rejected(self, client, world):
        p = self.anon_post(client, world)
        cid = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()["id"]
        assert client.post(f"/api/conversations/{cid}/messages", json={"content": ""}, headers=world["bob"]).status_code == 422

    def test_reveal_only_affects_that_chat_and_that_person(self, client, world):
        p = self.anon_post(client, world)
        cid = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()["id"]
        r = client.post(f"/api/conversations/{cid}/reveal", headers=world["alice"]).json()
        assert r["me_revealed"] is True
        assert client.get("/api/conversations", headers=world["bob"]).json()[0]["other_label"] == "Alice A."
        assert client.get(f"/api/posts/{p['id']}", headers=world["bob"]).json()["display_name"].startswith("Anon_")

    def test_dm_from_anonymous_comment(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        c = client.post(f"/api/posts/{p['id']}/comments", json={"content": "psst", "is_anonymous": True}, headers=world["bob"]).json()
        conv = client.post("/api/conversations", json={"post_id": p["id"], "comment_id": c["id"]}, headers=world["alice"]).json()
        assert conv["other_label"] == "Anonymous student"
        bad = client.post("/api/conversations", json={"post_id": p["id"], "comment_id": 999}, headers=world["alice"])
        assert bad.status_code == 404

    def test_initiator_can_stay_anonymous(self, client, world):
        p = struggle(client, world["alice"], world["cid"]).json()
        client.post("/api/conversations", json={"post_id": p["id"], "anonymous": True}, headers=world["bob"])
        conv = client.get("/api/conversations", headers=world["alice"]).json()[0]
        assert conv["other_label"] == "Anonymous student"


# ---------------- validation, races and limits ----------------
class TestRobustness:
    def test_whitespace_only_text_is_rejected(self, client, world):
        cid, h = world["cid"], world["alice"]
        p = struggle(client, h, cid).json()
        assert client.post(f"/api/posts/{p['id']}/comments", json={"content": "   "}, headers=h).status_code == 422
        assert client.post("/api/classes", json={"name": "   "}, headers=h).status_code == 422
        conv = client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()
        assert client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "  "}, headers=world["bob"]).status_code == 422

    def test_overlong_fields_rejected(self, client, world):
        url = f"/api/classes/{world['cid']}/posts"
        assert client.post(url, json={"type": "struggle", "content": "x" * 5001}, headers=world["alice"]).status_code == 422
        assert client.post(url, json={"type": "radar", "radar_title": "t" * 121, "due_at": FUTURE}, headers=world["alice"]).status_code == 422
        assert client.post(url, json={"type": "struggle", "content": "ok", "topic": "t" * 121}, headers=world["alice"]).status_code == 422

    def test_text_is_trimmed(self, client, world):
        p = client.post(f"/api/classes/{world['cid']}/posts", json={"type": "struggle", "content": "  hello  ", "topic": " Optics "}, headers=world["alice"]).json()
        assert p["content"] == "hello" and p["topic"] == "Optics"

    def test_feed_limit_param(self, client, world):
        for _ in range(3):
            struggle(client, world["alice"], world["cid"])
        assert len(client.get(f"/api/classes/{world['cid']}/posts?limit=2", headers=world["alice"]).json()) == 2
        assert client.get(f"/api/classes/{world['cid']}/posts?limit=0", headers=world["alice"]).status_code == 422

    def test_integrity_conflicts_return_409_not_500(self, client, world, monkeypatch):
        from sqlalchemy.exc import IntegrityError
        p = struggle(client, world["alice"], world["cid"]).json()
        from app import main
        def boom(*a, **k): raise IntegrityError("x", {}, Exception("dup"))
        monkeypatch.setattr(main.Session, "commit", boom, raising=False)
        r = client.post(f"/api/posts/{p['id']}/me-too", headers=world["bob"])
        assert r.status_code == 409

    def test_throttle_is_per_client_and_identifier(self, client):
        client.post("/api/auth/register", json={"name": "A", "username": "target_a", "password": "secret1"})
        client.post("/api/auth/register", json={"name": "B", "username": "target_b", "password": "secret1"})
        for _ in range(5):
            client.post("/api/auth/login", json={"identifier": "target_a", "password": "bad"})
        assert client.post("/api/auth/login", json={"identifier": "target_a", "password": "secret1"}).status_code == 429
        assert client.post("/api/auth/login", json={"identifier": "target_b", "password": "secret1"}).status_code == 200
