import base64, hashlib, hmac, io, os, random, re, secrets, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from typing import Annotated, Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import radar
from .db import Base, engine, get_db
from .models import *
from .security import hash_password, make_token, read_token, verify_password

app = FastAPI(title="Study Pulse API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_cols = {c['name'] for c in inspect(engine).get_columns('users')} if inspect(engine).has_table('users') else None
if _cols is not None and 'username' not in _cols:
    raise RuntimeError("This database was created by an older version of Study Pulse. Delete studypulse.db (or point DATABASE_URL at a new database) and restart.")
Base.metadata.create_all(engine)


@app.exception_handler(IntegrityError)
async def conflict(_req, _exc):   # e.g. a double-tapped button racing itself
    return JSONResponse({"detail": "That already exists. Please refresh and try again."}, status_code=409)


# ---------- schemas ----------
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Chat = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class RegisterIn(BaseModel):
    name: Name
    username: str | None = None
    phone: str | None = None
    password: str = Field(min_length=6)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def need_one(self):
        if not ((self.username or "").strip() or (self.phone or "").strip()):
            raise ValueError("Enter a username or a phone number")
        return self

class LoginIn(BaseModel):
    identifier: str   # username or phone number
    password: str

class ResetIn(BaseModel):
    identifier: str
    recovery_code: str
    password: str = Field(min_length=6)

class ClassIn(BaseModel):
    name: Short
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None

class JoinIn(BaseModel):
    code: str

class PostIn(BaseModel):
    type: Literal["struggle", "radar"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    topic: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    is_anonymous: bool = False
    radar_title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    due_at: datetime | None = None
    photo_url: str | None = None

class CommentIn(BaseModel):
    content: Chat
    is_anonymous: bool = False

class RadarIn(BaseModel):
    text: str | None = None
    image_base64: str | None = None
    media_type: str | None = None
    timezone: str = "UTC"

class DeadlineIn(BaseModel):
    title: Short
    due_at: datetime

class ConvIn(BaseModel):
    post_id: int
    comment_id: int | None = None
    anonymous: bool = False

class MsgIn(BaseModel):
    content: Chat

class ReportIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""

class UploadIn(BaseModel):
    image_base64: str

class TranscribeIn(BaseModel):
    audio_base64: str
    media_type: str | None = None


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))


class Hub:
    """Live chat: connected sockets per conversation."""
    def __init__(self):
        self.rooms: dict[int, list[tuple[WebSocket, int]]] = {}

    async def broadcast(self, cid, payload, sender_id):
        for ws, uid in list(self.rooms.get(cid, [])):
            try:
                await ws.send_json({**payload, "is_mine": uid == sender_id})
            except Exception:
                self.drop(cid, ws)

    def drop(self, cid, ws):
        self.rooms[cid] = [x for x in self.rooms.get(cid, []) if x[0] is not ws]


hub = Hub()


# ---------- helpers ----------
def iso(d):
    return d.isoformat() + "Z" if d else None

def to_utc(d: datetime):
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d

def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    uid = read_token(authorization.split(" ", 1)[1]) if authorization and authorization.startswith("Bearer ") else None
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user

def membership(db, user, class_id) -> Member:
    m = db.scalar(select(Member).where(Member.class_id == class_id, Member.user_id == user.id))
    if not m:
        raise HTTPException(403, "You are not in this class")
    return m

def get_post(db, user, post_id) -> Post:
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Post not found")
    membership(db, user, p.class_id)
    return p

def join(db, user, class_id) -> Member:
    m = db.scalar(select(Member).where(Member.class_id == class_id, Member.user_id == user.id))
    if m:
        return m
    taken = set(db.scalars(select(Member.anon_name).where(Member.class_id == class_id)))
    while True:
        name = f"Anon_{random.randint(100, 999)}"
        if name not in taken:
            break
    m = Member(class_id=class_id, user_id=user.id, anon_name=name)
    db.add(m); db.commit()
    return m

def class_out(db, k, m):
    n = db.scalar(select(func.count()).select_from(Member).where(Member.class_id == k.id))
    return {"id": k.id, "name": k.name, "subject": k.subject, "code": k.code, "member_count": n, "my_anon_name": m.anon_name, "is_owner": k.created_by == m.user_id}

def post_out(db, p, user):
    mine = db.get(PostAuthor, p.id).author_id == user.id
    owner = db.get(Klass, p.class_id).created_by == user.id
    return {"id": p.id, "class_id": p.class_id, "type": p.type, "content": p.content, "topic": p.topic,
            "display_name": p.display_name, "is_anonymous": p.is_anonymous, "radar_title": p.radar_title,
            "due_at": iso(p.due_at), "created_at": iso(p.created_at), "is_mine": mine, "can_delete": mine or owner, "photo_url": p.photo_url,
            "me_too_count": db.scalar(select(func.count()).select_from(MeToo).where(MeToo.post_id == p.id)),
            "comment_count": db.scalar(select(func.count()).select_from(Comment).where(Comment.post_id == p.id)),
            "i_said_me_too": db.get(MeToo, (p.id, user.id)) is not None}

def comment_out(db, c, user):
    return {"id": c.id, "post_id": c.post_id, "content": c.content, "display_name": c.display_name,
            "is_anonymous": c.is_anonymous, "created_at": iso(c.created_at),
            "is_mine": db.get(CommentAuthor, c.id).author_id == user.id}

def conv_for(db, user, cid) -> Conversation:
    c = db.get(Conversation, cid)
    if not c or user.id not in (c.user_a, c.user_b):
        raise HTTPException(404, "Conversation not found")
    return c

def conv_out(db, c, user):
    a = user.id == c.user_a
    other = db.get(User, c.user_b if a else c.user_a)
    hidden = (c.b_anon and not c.b_revealed) if a else (c.a_anon and not c.a_revealed)
    p = db.get(Post, c.post_id)
    return {"id": c.id, "post_id": c.post_id, "topic": p.topic or p.radar_title,
            "other_label": "Anonymous student" if hidden else other.name, "other_hidden": hidden,
            "me_anon": c.a_anon if a else c.b_anon, "me_revealed": c.a_revealed if a else c.b_revealed}


# ---------- auth ----------
USERNAME = re.compile(r"(?=.*[a-z])[a-z0-9_]{3,30}")
FAILS: dict[str, list[float]] = {}   # simple brute-force guard: 5 failures / 15 min per (client IP, identifier)

def norm_phone(v):
    d = re.sub(r"[\s().-]", "", v or "").lstrip("+")
    return d if re.fullmatch(r"\d{7,15}", d) else None

def find_user(db, ident):
    ident = (ident or "").strip().lower()
    ph = norm_phone(ident)
    return db.scalar(select(User).where(User.phone == ph)) if ph else db.scalar(select(User).where(User.username == ident))

def throttle(key):
    FAILS[key] = [t for t in FAILS.get(key, []) if time.time() - t < 900]
    if len(FAILS[key]) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")

def new_recovery():
    c = secrets.token_hex(4).upper()
    return f"{c[:4]}-{c[4:]}"

def rhash(code):
    return hashlib.sha256(code.replace("-", "").replace(" ", "").upper().encode()).hexdigest()

def user_out(u):
    return {"id": u.id, "name": u.name, "username": u.username}

@app.post("/api/auth/register", status_code=201)
def register(b: RegisterIn, db: Session = Depends(get_db)):
    uname = (b.username or "").strip().lower() or None
    phone = norm_phone(b.phone) if (b.phone or "").strip() else None
    if uname and not USERNAME.fullmatch(uname):
        raise HTTPException(422, "Username: 3-30 letters, numbers or _ (at least one letter)")
    if (b.phone or "").strip() and not phone:
        raise HTTPException(422, "Enter the phone number with country code, e.g. +234 801 234 5678")
    if uname and db.scalar(select(User).where(User.username == uname)):
        raise HTTPException(409, "That username is taken")
    if phone and db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(409, "That phone number is already registered")
    code = new_recovery()
    u = User(username=uname, phone=phone, name=b.name.strip(), password_hash=hash_password(b.password), recovery_hash=rhash(code), timezone=b.timezone)
    db.add(u); db.commit()
    return {"token": make_token(u.id), "user": user_out(u), "recovery_code": code}   # code is shown once; only its hash is stored

@app.post("/api/auth/login")
def login(b: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = f"login:{request.client.host if request.client else '-'}:{b.identifier.strip().lower()}"
    throttle(key)
    u = find_user(db, b.identifier)
    if not u or not verify_password(b.password, u.password_hash):
        FAILS.setdefault(key, []).append(time.time())
        raise HTTPException(401, "Wrong username/phone or password")
    return {"token": make_token(u.id), "user": user_out(u)}

@app.post("/api/auth/reset")
def reset(b: ResetIn, request: Request, db: Session = Depends(get_db)):
    key = f"reset:{request.client.host if request.client else '-'}:{b.identifier.strip().lower()}"
    throttle(key)
    u = find_user(db, b.identifier)
    if not u or not u.recovery_hash or not hmac.compare_digest(u.recovery_hash, rhash(b.recovery_code)):
        FAILS.setdefault(key, []).append(time.time())
        raise HTTPException(400, "Wrong username/phone or recovery code")
    code = new_recovery()
    u.password_hash, u.recovery_hash = hash_password(b.password), rhash(code)
    db.commit()
    return {"ok": True, "recovery_code": code}   # old code stops working; show the new one

@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "username": user.username, "phone": user.phone, "timezone": user.timezone}


# ---------- classes ----------
@app.post("/api/classes", status_code=201)
def create_class(b: ClassIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    k = Klass(name=b.name.strip(), subject=b.subject, code=secrets.token_hex(3).upper(), created_by=user.id)
    db.add(k); db.commit()
    return class_out(db, k, join(db, user, k.id))

@app.post("/api/classes/join")
def join_class(b: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    k = db.scalar(select(Klass).where(Klass.code == b.code.strip().upper()))
    if not k:
        raise HTTPException(404, "No class with that code")
    return class_out(db, k, join(db, user, k.id))

@app.get("/api/classes")
def my_classes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Klass, Member).join(Member, Member.class_id == Klass.id).where(Member.user_id == user.id)).all()
    return [class_out(db, k, m) for k, m in rows]

@app.get("/api/classes/{class_id}")
def class_detail(class_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = membership(db, user, class_id)
    return class_out(db, db.get(Klass, class_id), m)


# ---------- posts ----------
@app.get("/api/classes/{class_id}/posts")
def list_posts(class_id: int, type: str | None = None, topic: str | None = None, limit: int = Query(100, ge=1, le=200),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership(db, user, class_id)
    q = select(Post).where(Post.class_id == class_id)
    if type:
        q = q.where(Post.type == type)
    if topic:
        q = q.where(Post.topic == topic)
    q = q.order_by(Post.due_at if type == "radar" else Post.created_at.desc()).limit(limit)
    return [post_out(db, p, user) for p in db.scalars(q)]

@app.get("/api/classes/{class_id}/topics")
def hot_topics(class_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership(db, user, class_id)
    stuck = func.count(func.distinct(Post.id)) + func.count(MeToo.user_id)   # each poster is stuck, plus everyone who tapped Me too
    rows = db.execute(select(Post.topic, stuck).outerjoin(MeToo, MeToo.post_id == Post.id)
                      .where(Post.class_id == class_id, Post.type == "struggle").group_by(Post.topic)
                      .order_by(stuck.desc(), Post.topic)).all()
    return [{"topic": t, "stuck_count": n} for t, n in rows if t]

@app.post("/api/classes/{class_id}/posts", status_code=201)
def create_post(class_id: int, b: PostIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = membership(db, user, class_id)
    if b.type == "struggle" and not (b.content or "").strip():
        raise HTTPException(422, "Struggle posts need content")
    if b.type == "radar" and not ((b.radar_title or "").strip() and b.due_at):
        raise HTTPException(422, "Radar posts need a title and due date")
    if b.photo_url and not photo_ok(b.photo_url):
        raise HTTPException(422, "Unknown photo")
    anon = b.is_anonymous and b.type == "struggle"   # deadlines are always public
    p = Post(class_id=class_id, type=b.type, content=b.content, topic=(b.topic or "General") if b.type == "struggle" else None,
             is_anonymous=anon, display_name=m.anon_name if anon else user.name,
             radar_title=b.radar_title, photo_url=b.photo_url, due_at=to_utc(b.due_at) if b.due_at else None)
    db.add(p); db.flush()
    db.add(PostAuthor(post_id=p.id, author_id=user.id)); db.commit()
    return post_out(db, p, user)

@app.get("/api/posts/{post_id}")
def read_post(post_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return post_out(db, get_post(db, user, post_id), user)

@app.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, post_id)
    if db.get(PostAuthor, p.id).author_id != user.id and db.get(Klass, p.class_id).created_by != user.id:
        raise HTTPException(403, "Only the author or class owner can delete this")
    cids = list(db.scalars(select(Comment.id).where(Comment.post_id == p.id)))
    convs = list(db.scalars(select(Conversation.id).where(Conversation.post_id == p.id)))
    db.execute(delete(Message).where(Message.conversation_id.in_(convs)))
    db.execute(delete(Conversation).where(Conversation.post_id == p.id))
    db.execute(delete(CommentAuthor).where(CommentAuthor.comment_id.in_(cids)))
    for model in (Comment, MeToo, Report, PostAuthor):
        db.execute(delete(model).where(model.post_id == p.id))
    db.delete(p); db.commit()

@app.post("/api/posts/{post_id}/me-too")
def toggle_me_too(post_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, post_id)
    row = db.get(MeToo, (p.id, user.id))
    if row:
        db.delete(row)
    else:
        db.add(MeToo(post_id=p.id, user_id=user.id))
    db.commit()
    return {"active": row is None, "count": db.scalar(select(func.count()).select_from(MeToo).where(MeToo.post_id == p.id))}

@app.post("/api/posts/{post_id}/report", status_code=201)
def report_post(post_id: int, b: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, post_id)
    if not db.scalar(select(Report).where(Report.post_id == p.id, Report.reporter_id == user.id)):
        db.add(Report(post_id=p.id, reporter_id=user.id, reason=b.reason[:200])); db.commit()
    return {"ok": True}


# ---------- comments ----------
@app.get("/api/posts/{post_id}/comments")
def list_comments(post_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, post_id)
    return [comment_out(db, c, user) for c in db.scalars(select(Comment).where(Comment.post_id == p.id).order_by(Comment.created_at, Comment.id))]

@app.post("/api/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, b: CommentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, post_id)
    m = membership(db, user, p.class_id)
    c = Comment(post_id=p.id, content=b.content, is_anonymous=b.is_anonymous, display_name=m.anon_name if b.is_anonymous else user.name)
    db.add(c); db.flush()
    db.add(CommentAuthor(comment_id=c.id, author_id=user.id)); db.commit()
    return comment_out(db, c, user)


# ---------- radar + private deadlines ----------
@app.post("/api/radar/parse")
def radar_parse(b: RadarIn, user: User = Depends(current_user)):
    if not (b.text or "").strip() and not b.image_base64:
        raise HTTPException(422, "Send text or an image")
    return radar.parse(b.text, b.image_base64, b.media_type, b.timezone)

@app.post("/api/radar/transcribe")
def radar_transcribe(b: TranscribeIn, user: User = Depends(current_user)):
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(503, "Voice notes need GROQ_API_KEY on the server. Type the deadline instead.")
    try:
        audio = base64.b64decode(b.audio_base64, validate=True)
    except Exception:
        raise HTTPException(422, "Invalid audio data")
    if not audio or len(audio) > 8_000_000:
        raise HTTPException(413, "Audio is empty or too long")
    try:
        return {"text": radar.transcribe(audio, b.media_type)}
    except Exception:
        raise HTTPException(502, "Could not transcribe that recording")

@app.get("/api/classes/{class_id}/deadlines")
def list_deadlines(class_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership(db, user, class_id)
    rows = db.scalars(select(Deadline).where(Deadline.class_id == class_id, Deadline.user_id == user.id).order_by(Deadline.due_at))
    return [{"id": d.id, "title": d.title, "due_at": iso(d.due_at)} for d in rows]

@app.post("/api/classes/{class_id}/deadlines", status_code=201)
def add_deadline(class_id: int, b: DeadlineIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership(db, user, class_id)
    d = Deadline(user_id=user.id, class_id=class_id, title=b.title.strip(), due_at=to_utc(b.due_at))
    db.add(d); db.commit()
    return {"id": d.id, "title": d.title, "due_at": iso(d.due_at)}

@app.delete("/api/deadlines/{deadline_id}", status_code=204)
def delete_deadline(deadline_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Deadline, deadline_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Deadline not found")
    db.delete(d); db.commit()


# ---------- direct messages ----------
@app.post("/api/conversations", status_code=201)
def start_conversation(b: ConvIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_post(db, user, b.post_id)
    if b.comment_id:
        c = db.get(Comment, b.comment_id)
        if not c or c.post_id != p.id:
            raise HTTPException(404, "Comment not found")
        target, t_anon = db.get(CommentAuthor, c.id).author_id, c.is_anonymous
    else:
        target, t_anon = db.get(PostAuthor, p.id).author_id, p.is_anonymous
    if target == user.id:
        raise HTTPException(400, "You cannot message yourself")
    conv = db.scalar(select(Conversation).where(Conversation.post_id == p.id, Conversation.user_a == user.id, Conversation.user_b == target))
    if not conv:
        conv = Conversation(post_id=p.id, user_a=user.id, user_b=target, a_anon=b.anonymous, b_anon=t_anon)
        db.add(conv); db.commit()
    return conv_out(db, conv, user)

@app.get("/api/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Conversation).where(or_(Conversation.user_a == user.id, Conversation.user_b == user.id)).order_by(Conversation.id.desc())
    return [conv_out(db, c, user) for c in db.scalars(q)]

@app.get("/api/conversations/{cid}/messages")
def list_messages(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = conv_for(db, user, cid)
    msgs = db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.id))
    return {"conversation": conv_out(db, c, user),
            "messages": [{"id": m.id, "content": m.content, "is_mine": m.sender_id == user.id, "created_at": iso(m.created_at)} for m in msgs]}

@app.post("/api/conversations/{cid}/messages", status_code=201)
async def send_message(cid: int, b: MsgIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = conv_for(db, user, cid)
    m = Message(conversation_id=c.id, sender_id=user.id, content=b.content)
    db.add(m); db.commit()
    out = {"type": "message", "id": m.id, "content": m.content, "created_at": iso(m.created_at)}
    await hub.broadcast(cid, out, user.id)
    return {**out, "is_mine": True}

@app.websocket("/ws/conversations/{cid}")
async def chat_socket(ws: WebSocket, cid: int, token: str = ""):
    db = next((app.dependency_overrides.get(get_db) or get_db)())
    uid = read_token(token)
    c = db.get(Conversation, cid) if uid else None
    ok = bool(c and uid in (c.user_a, c.user_b))
    db.close()
    if not ok:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.rooms.setdefault(cid, []).append((ws, uid))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.drop(cid, ws)

@app.post("/api/conversations/{cid}/reveal")
async def reveal(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = conv_for(db, user, cid)
    if user.id == c.user_a:
        c.a_revealed = True
    else:
        c.b_revealed = True
    db.commit()
    await hub.broadcast(cid, {"type": "reveal"}, user.id)   # tells the other side to refresh the header (no identity in the event)
    return conv_out(db, c, user)


# ---------- uploads (Cloudinary when CLOUDINARY_URL is set, local disk otherwise) ----------
def cloudinary_cfg():
    u = os.getenv("CLOUDINARY_URL")
    if not u:
        return None
    p = urlparse(u)
    return p.username, p.password, p.hostname   # cloudinary://API_KEY:API_SECRET@CLOUD_NAME

def photo_ok(url):
    cfg = cloudinary_cfg()
    if cfg and re.fullmatch(rf"https://res\.cloudinary\.com/{re.escape(cfg[2])}/image/upload/(?:v\d+/)?studypulse/[A-Za-z0-9_-]+\.jpg", url):
        return True
    return bool(re.fullmatch(r"/uploads/[0-9a-f]{32}\.jpg", url) and (UPLOAD_DIR / url[9:]).exists())

def store_image(jpeg: bytes) -> str:
    cfg = cloudinary_cfg()
    if cfg:
        key, secret, cloud = cfg
        params = {"folder": "studypulse", "timestamp": int(time.time())}
        sig = hashlib.sha1(("&".join(f"{k}={v}" for k, v in sorted(params.items())) + secret).encode()).hexdigest()
        try:
            r = httpx.post(f"https://api.cloudinary.com/v1_1/{cloud}/image/upload", data={**params, "api_key": key, "signature": sig},
                           files={"file": ("photo.jpg", jpeg, "image/jpeg")}, timeout=30)
            r.raise_for_status()
            return r.json()["secure_url"]
        except Exception:
            raise HTTPException(502, "Photo storage is unavailable right now")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + ".jpg"
    (UPLOAD_DIR / name).write_bytes(jpeg)
    return "/uploads/" + name

@app.post("/api/uploads", status_code=201)
def upload_image(b: UploadIn, user: User = Depends(current_user)):
    try:
        raw = base64.b64decode(b.image_base64, validate=True)
    except Exception:
        raise HTTPException(422, "Invalid image data")
    if len(raw) > 4_000_000:
        raise HTTPException(413, "Image too large (4 MB max)")
    try:
        img = Image.open(io.BytesIO(raw)); img.load()
    except Exception:
        raise HTTPException(422, "Not a valid image")
    img = img.convert("RGB"); img.thumbnail((1280, 1280))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=82)   # re-encoding drops EXIF/GPS before the photo leaves our server
    return {"url": store_image(buf.getvalue())}


# ---------- moderation (class owner) ----------
def owner_only(db, user, class_id):
    membership(db, user, class_id)
    if db.get(Klass, class_id).created_by != user.id:
        raise HTTPException(403, "Only the class owner can do this")

@app.get("/api/classes/{class_id}/reports")
def list_reports(class_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_only(db, user, class_id)
    rows = db.execute(select(Report.post_id, func.count(Report.id)).join(Post, Post.id == Report.post_id)
                      .where(Post.class_id == class_id).group_by(Report.post_id)).all()
    out = []
    for pid, n in rows:   # never includes reporter or author ids
        p = db.get(Post, pid)
        out.append({"post_id": pid, "preview": (p.content or p.radar_title or "")[:140], "display_name": p.display_name,
                    "report_count": n, "reasons": [r for r in db.scalars(select(Report.reason).where(Report.post_id == pid)) if r]})
    return out

@app.delete("/api/classes/{class_id}/reports/{post_id}", status_code=204)
def dismiss_reports(class_id: int, post_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owner_only(db, user, class_id)
    db.execute(delete(Report).where(Report.post_id == post_id)); db.commit()


# ---------- serve built frontend (single-container deploy) ----------
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR, check_dir=False), name="uploads")
STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
