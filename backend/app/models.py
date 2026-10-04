"""Data model. ANONYMITY: author ids live only in PostAuthor / CommentAuthor and are
never serialized by any endpoint. Public rows carry a copied display_name instead."""
from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)  # digits only, never exposed to others
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    recovery_hash: Mapped[str] = mapped_column(String(64), default="")
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")


class Klass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str | None] = mapped_column(String(80), nullable=True)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("class_id", "user_id"), UniqueConstraint("class_id", "anon_name"))
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    anon_name: Mapped[str] = mapped_column(String(20))


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    type: Mapped[str] = mapped_column(String(10))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(80))
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    radar_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PostAuthor(Base):
    __tablename__ = "post_authors"
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CommentAuthor(Base):
    __tablename__ = "comment_authors"
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class MeToo(Base):
    __tablename__ = "me_too"
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Deadline(Base):
    __tablename__ = "deadlines"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    title: Mapped[str] = mapped_column(String(120))
    due_at: Mapped[datetime] = mapped_column(DateTime)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("post_id", "user_a", "user_b"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    user_a: Mapped[int] = mapped_column(ForeignKey("users.id"))  # initiator
    user_b: Mapped[int] = mapped_column(ForeignKey("users.id"))  # target
    a_anon: Mapped[bool] = mapped_column(Boolean, default=False)
    b_anon: Mapped[bool] = mapped_column(Boolean, default=False)
    a_revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    b_revealed: Mapped[bool] = mapped_column(Boolean, default=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(200), default="")
