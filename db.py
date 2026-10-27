import os
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import DB_URL

if DB_URL.startswith("sqlite"):
    path = DB_URL.split("///")[-1]
    if path and not path.startswith(":memory:"):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

class Base(DeclarativeBase):
    pass

class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), unique=True)
    last_checked: Mapped["DateTime"] = mapped_column(DateTime, default=func.now())

class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"))
    tiktok_id: Mapped[str] = mapped_column(String(128), unique=True)
    author: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)

class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped["DateTime"] = mapped_column(DateTime, default=func.now())

engine = create_async_engine(DB_URL)
Session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)