import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:   # one shared event loop so websockets and REST can talk
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    from app import main
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    for k in ("CLOUDINARY_URL", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    main.FAILS.clear()


@pytest.fixture()
def make_user(client):
    def _make(name="Mei L.", key=None):
        username = "u_" + re.sub(r"[^a-z0-9]", "", (key or name).lower())
        r = client.post("/api/auth/register", json={"username": username, "password": "secret1", "name": name})
        assert r.status_code == 201, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}
    return _make


@pytest.fixture()
def world(client, make_user):
    """Two students (alice, bob) in one class, plus an outsider."""
    alice, bob, eve = make_user("Alice A.", "a@x.com"), make_user("Bob B.", "b@x.com"), make_user("Eve E.", "e@x.com")
    k = client.post("/api/classes", json={"name": "Physics, Grade 11", "subject": "Physics"}, headers=alice).json()
    client.post("/api/classes/join", json={"code": k["code"]}, headers=bob)
    return {"alice": alice, "bob": bob, "eve": eve, "cls": k, "cid": k["id"]}
