"""Tests for uploads, moderation, password reset and live chat."""
import base64, io, json
from datetime import datetime, timezone

import pytest
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from app import main, radar


def png_b64(size=(40, 30)):
    buf = io.BytesIO(); Image.new("RGB", size, "red").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def struggle(client, h, cid, **kw):
    return client.post(f"/api/classes/{cid}/posts", json={"type": "struggle", "content": "Help", "topic": "Optics", **kw}, headers=h)


class TestUploads:
    def test_upload_returns_url_and_saves_jpeg(self, client, world):
        r = client.post("/api/uploads", json={"image_base64": png_b64()}, headers=world["alice"])
        assert r.status_code == 201 and r.json()["url"].startswith("/uploads/") and r.json()["url"].endswith(".jpg")
        assert (main.UPLOAD_DIR / r.json()["url"][9:]).exists()

    def test_exif_metadata_is_stripped(self, client, world):
        img = Image.new("RGB", (50, 50), "blue"); exif = Image.Exif(); exif[0x010F] = "SecretPhoneBrand"
        buf = io.BytesIO(); img.save(buf, "JPEG", exif=exif)
        r = client.post("/api/uploads", json={"image_base64": base64.b64encode(buf.getvalue()).decode()}, headers=world["alice"])
        saved = Image.open(main.UPLOAD_DIR / r.json()["url"][9:])
        assert not saved.getexif() and b"SecretPhoneBrand" not in (main.UPLOAD_DIR / r.json()["url"][9:]).read_bytes()

    def test_large_images_are_downscaled(self, client, world):
        r = client.post("/api/uploads", json={"image_base64": png_b64((3000, 2000))}, headers=world["alice"])
        assert max(Image.open(main.UPLOAD_DIR / r.json()["url"][9:]).size) <= 1280

    def test_rejects_bad_data_and_requires_auth(self, client, world):
        assert client.post("/api/uploads", json={"image_base64": "***"}, headers=world["alice"]).status_code == 422
        assert client.post("/api/uploads", json={"image_base64": base64.b64encode(b"not an image").decode()}, headers=world["alice"]).status_code == 422
        assert client.post("/api/uploads", json={"image_base64": png_b64()}).status_code == 401

    def test_rejects_oversized_upload(self, client, world):
        big = base64.b64encode(b"0" * 4_100_000).decode()
        assert client.post("/api/uploads", json={"image_base64": big}, headers=world["alice"]).status_code == 413

    def test_post_with_photo(self, client, world):
        url = client.post("/api/uploads", json={"image_base64": png_b64()}, headers=world["alice"]).json()["url"]
        p = struggle(client, world["alice"], world["cid"], photo_url=url, is_anonymous=True)
        assert p.status_code == 201 and p.json()["photo_url"] == url
        assert client.get(f"/api/classes/{world['cid']}/posts", headers=world["bob"]).json()[0]["photo_url"] == url

    @pytest.mark.parametrize("bad", ["http://evil.com/x.jpg", "/uploads/../etc/passwd", "/uploads/" + "a" * 32 + ".jpg"])
    def test_post_rejects_unknown_photo_urls(self, client, world, bad):
        assert struggle(client, world["alice"], world["cid"], photo_url=bad).status_code == 422


class TestModeration:
    def test_class_detail_marks_owner(self, client, world):
        assert client.get(f"/api/classes/{world['cid']}", headers=world["alice"]).json()["is_owner"] is True
        assert client.get(f"/api/classes/{world['cid']}", headers=world["bob"]).json()["is_owner"] is False

    def test_owner_sees_grouped_reports_without_identities(self, client, world):
        cid = world["cid"]
        p = struggle(client, world["bob"], cid, is_anonymous=True).json()
        client.post(f"/api/posts/{p['id']}/report", json={"reason": "rude"}, headers=world["alice"])
        client.post(f"/api/posts/{p['id']}/report", json={"reason": "rude"}, headers=world["alice"])  # duplicate ignored
        r = client.get(f"/api/classes/{cid}/reports", headers=world["alice"])
        assert r.status_code == 200 and r.json()[0]["report_count"] == 1 and r.json()[0]["reasons"] == ["rude"]
        assert "Bob" not in r.text and "Alice" not in r.text and "user_id" not in r.text

    def test_only_owner_can_view_or_dismiss_reports(self, client, world):
        cid = world["cid"]
        assert client.get(f"/api/classes/{cid}/reports", headers=world["bob"]).status_code == 403
        assert client.get(f"/api/classes/{cid}/reports", headers=world["eve"]).status_code == 403
        assert client.delete(f"/api/classes/{cid}/reports/1", headers=world["bob"]).status_code == 403

    def test_owner_can_dismiss_reports(self, client, world):
        cid = world["cid"]
        p = struggle(client, world["bob"], cid).json()
        client.post(f"/api/posts/{p['id']}/report", json={}, headers=world["alice"])
        assert client.delete(f"/api/classes/{cid}/reports/{p['id']}", headers=world["alice"]).status_code == 204
        assert client.get(f"/api/classes/{cid}/reports", headers=world["alice"]).json() == []

    def test_owner_can_remove_anyones_post_but_members_cannot(self, client, world):
        cid = world["cid"]
        p = struggle(client, world["bob"], cid, is_anonymous=True).json()
        assert client.get(f"/api/posts/{p['id']}", headers=world["alice"]).json()["can_delete"] is True
        q = struggle(client, world["alice"], cid).json()
        assert client.get(f"/api/posts/{q['id']}", headers=world["bob"]).json()["can_delete"] is False
        assert client.delete(f"/api/posts/{q['id']}", headers=world["bob"]).status_code == 403
        assert client.delete(f"/api/posts/{p['id']}", headers=world["alice"]).status_code == 204


class FakeResp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


class TestCloudinary:
    URL = "https://res.cloudinary.com/democloud/image/upload/v17/studypulse/abc_123.jpg"

    def setup_cloud(self, monkeypatch, calls):
        monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://key123:secret456@democloud")
        monkeypatch.setattr(main.time, "time", lambda: 1700000000)
        def fake_post(url, **kw):
            calls.append((url, kw)); return FakeResp({"secure_url": self.URL})
        monkeypatch.setattr(main.httpx, "post", fake_post)

    def test_upload_goes_to_cloudinary_with_valid_signature(self, client, world, monkeypatch):
        import hashlib
        calls = []; self.setup_cloud(monkeypatch, calls)
        r = client.post("/api/uploads", json={"image_base64": png_b64()}, headers=world["alice"])
        assert r.status_code == 201 and r.json()["url"] == self.URL
        url, kw = calls[0]
        assert url == "https://api.cloudinary.com/v1_1/democloud/image/upload"
        want = hashlib.sha1(b"folder=studypulse&timestamp=1700000000secret456").hexdigest()
        assert kw["data"]["signature"] == want and kw["data"]["api_key"] == "key123" and "secret456" not in json.dumps(kw["data"])
        assert kw["files"]["file"][1][:2] == b"\xff\xd8"   # JPEG bytes, re-encoded
        assert not main.UPLOAD_DIR.exists()

    def test_post_accepts_only_this_clouds_studypulse_urls(self, client, world, monkeypatch):
        self.setup_cloud(monkeypatch, [])
        assert struggle(client, world["alice"], world["cid"], photo_url=self.URL).status_code == 201
        for bad in ("https://res.cloudinary.com/othercloud/image/upload/v1/studypulse/a.jpg",
                    "https://res.cloudinary.com/democloud/image/upload/v1/private/a.jpg",
                    "https://evil.com/studypulse/a.jpg"):
            assert struggle(client, world["alice"], world["cid"], photo_url=bad).status_code == 422

    def test_cloudinary_failure_returns_502(self, client, world, monkeypatch):
        monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://k:s@c")
        def boom(*a, **k): raise RuntimeError("down")
        monkeypatch.setattr(main.httpx, "post", boom)
        assert client.post("/api/uploads", json={"image_base64": png_b64()}, headers=world["alice"]).status_code == 502


class TestGroq:
    def capture(self, monkeypatch, content):
        calls = []
        def fake_post(url, **kw):
            calls.append((url, kw)); return FakeResp({"choices": [{"message": {"content": content}}]} if "chat" in url else {"text": " lab report due friday "})
        monkeypatch.setattr(radar.httpx, "post", fake_post)
        return calls

    def test_text_uses_text_model_with_json_mode(self, client, world, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        calls = self.capture(monkeypatch, 'Sure! {"title": "Lab report", "subject": "Physics", "due_date": "2026-10-09T17:00:00+01:00", "confidence": 0.9}')
        r = client.post("/api/radar/parse", json={"text": "lab report due friday 5pm", "timezone": "Africa/Lagos"}, headers=world["alice"]).json()
        url, kw = calls[0]
        assert url == "https://api.groq.com/openai/v1/chat/completions" and kw["headers"]["Authorization"] == "Bearer gsk_test"
        assert kw["json"]["model"] == "llama-3.3-70b-versatile" and kw["json"]["response_format"] == {"type": "json_object"}
        assert "Africa/Lagos" in kw["json"]["messages"][0]["content"]
        assert r["title"] == "Lab report" and r["needs_clarification"] is False

    def test_image_uses_vision_model(self, client, world, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        calls = self.capture(monkeypatch, '{"title": "Worksheet", "due_date": null}')
        r = client.post("/api/radar/parse", json={"image_base64": "aGk=", "media_type": "image/png"}, headers=world["alice"]).json()
        body = calls[0][1]["json"]
        assert "llama-4-scout" in body["model"] and body["messages"][1]["content"][1]["image_url"]["url"] == "data:image/png;base64,aGk="
        assert r["needs_clarification"] is True

    def test_groq_failure_falls_back_to_rules(self, client, world, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        def boom(*a, **k): raise RuntimeError("down")
        monkeypatch.setattr(radar.httpx, "post", boom)
        r = client.post("/api/radar/parse", json={"text": "Chemistry worksheet due Friday 5pm"}, headers=world["alice"]).json()
        assert r["title"] == "Chemistry worksheet" and r["due_date"]

    def test_transcribe_returns_text(self, client, world, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        calls = self.capture(monkeypatch, "")
        r = client.post("/api/radar/transcribe", json={"audio_base64": base64.b64encode(b"fakeaudio").decode(), "media_type": "audio/webm;codecs=opus"}, headers=world["alice"])
        assert r.status_code == 200 and r.json() == {"text": "lab report due friday"}
        url, kw = calls[0]
        assert url.endswith("/audio/transcriptions") and kw["data"]["model"] == "whisper-large-v3-turbo" and kw["files"]["file"][0] == "voice.webm"

    def test_transcribe_errors(self, client, world, monkeypatch):
        ok = {"audio_base64": base64.b64encode(b"x").decode()}
        assert client.post("/api/radar/transcribe", json=ok, headers=world["alice"]).status_code == 503
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        assert client.post("/api/radar/transcribe", json={"audio_base64": "***"}, headers=world["alice"]).status_code == 422
        assert client.post("/api/radar/transcribe", json={"audio_base64": ""}, headers=world["alice"]).status_code == 413
        def boom(*a, **k): raise RuntimeError("down")
        monkeypatch.setattr(radar.httpx, "post", boom)
        assert client.post("/api/radar/transcribe", json=ok, headers=world["alice"]).status_code == 502
        assert client.post("/api/radar/transcribe", json=ok).status_code == 401


class TestLiveChat:
    def conv(self, client, world):
        p = struggle(client, world["alice"], world["cid"], is_anonymous=True).json()
        return client.post("/api/conversations", json={"post_id": p["id"]}, headers=world["bob"]).json()["id"]

    def tok(self, h):
        return h["Authorization"].split(" ")[1]

    def test_message_is_pushed_to_other_participant(self, client, world):
        cid = self.conv(client, world)
        with client.websocket_connect(f"/ws/conversations/{cid}?token={self.tok(world['alice'])}") as alice_ws:
            client.post(f"/api/conversations/{cid}/messages", json={"content": "Hi from Bob"}, headers=world["bob"])
            got = alice_ws.receive_json()
        assert got["content"] == "Hi from Bob" and got["is_mine"] is False
        assert "sender" not in json.dumps(got) and "user" not in json.dumps(got)

    def test_sender_socket_sees_is_mine(self, client, world):
        cid = self.conv(client, world)
        with client.websocket_connect(f"/ws/conversations/{cid}?token={self.tok(world['bob'])}") as ws:
            client.post(f"/api/conversations/{cid}/messages", json={"content": "me"}, headers=world["bob"])
            assert ws.receive_json()["is_mine"] is True

    def test_rejects_bad_token_and_non_participants(self, client, world):
        cid = self.conv(client, world)
        for token in ("junk", self.tok(world["eve"]), ""):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/ws/conversations/{cid}?token={token}"):
                    pass

    def test_unknown_conversation_rejected(self, client, world):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/conversations/999?token={self.tok(world['alice'])}"):
                pass

    def test_reveal_event_reaches_other_side_without_identity(self, client, world):
        cid = self.conv(client, world)
        with client.websocket_connect(f"/ws/conversations/{cid}?token={self.tok(world['bob'])}") as bob_ws:
            client.post(f"/api/conversations/{cid}/reveal", headers=world["alice"])
            ev = bob_ws.receive_json()
        assert ev["type"] == "reveal" and "Alice" not in json.dumps(ev)

    def test_message_events_are_typed(self, client, world):
        cid = self.conv(client, world)
        with client.websocket_connect(f"/ws/conversations/{cid}?token={self.tok(world['alice'])}") as ws:
            client.post(f"/api/conversations/{cid}/messages", json={"content": "yo"}, headers=world["bob"])
            assert ws.receive_json()["type"] == "message"


class TestRadarRules:
    def test_title_drops_date_words_and_trailing_prepositions(self):
        now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
        assert radar.fallback("Read chapter 4 tomorrow", "UTC", now)["title"] == "Read chapter 4"
        assert radar.fallback("Essay on Friday", "UTC", now)["title"] == "Essay"
        assert radar.fallback("Maths worksheet due today 3pm", "UTC", now)["due_date"].startswith("2026-10-02T15:00")
        assert radar.fallback("Quiz tonight", "UTC", now)["due_date"].startswith("2026-10-02T23:59")

    def test_unparseable_text_keeps_whole_text_as_title(self):
        r = radar.fallback("maths homework", "UTC")
        assert r["title"] == "Maths homework" and r["needs_clarification"] is True
