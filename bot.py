import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from config import ADMIN_IDS, BOT_TOKEN, POLL_INTERVAL_SEC
from db import Comment, Draft, Session, Video, init_db
from tiktok_service import fetch_comments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("Приватный бот.")
    await m.answer(
        "<b>Помощник для TikTok</b>\n\n"
        "/watch &lt;url&gt; — отслеживать видео\n"
        "/list — список отслеживаемых\n"
        "/remove &lt;id&gt; — убрать\n"
        "/add &lt;url&gt; | &lt;автор&gt; | &lt;текст&gt; — вручную добавить комментарий\n"
        "/fetch — запустить сбор сейчас\n"
        "/drafts — очередь черновиков\n"
    )

@dp.message(Command("watch"))
async def cmd_watch(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    url = (command.args or "").strip()
    if not url or "tiktok.com" not in url:
        return await m.answer("Формат: /watch https://www.tiktok.com/@user/video/123")
    async with Session() as s:
        if (await s.execute(select(Video).where(Video.url == url))).scalar_one_or_none():
            return await m.answer("Уже отслеживается.")
        v = Video(url=url)
        s.add(v)
        await s.commit()
        vid = v.id
    await m.answer(f"✅ Добавил id={vid}. Опрос раз в {POLL_INTERVAL_SEC // 60} мин.")

@dp.message(Command("list"))
async def cmd_list(m: Message):
    if not is_admin(m.from_user.id):
        return
    async with Session() as s:
        videos = (await s.execute(select(Video).order_by(Video.id))).scalars().all()
    if not videos:
        return await m.answer("Пусто. /watch <url>")
    await m.answer("\n".join(f"<b>{v.id}</b> — {v.url}" for v in videos))

@dp.message(Command("remove"))
async def cmd_remove(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    try:
        vid = int((command.args or "").strip())
    except ValueError:
        return await m.answer("Формат: /remove <id>")
    async with Session() as s:
        v = await s.get(Video, vid)
        if not v:
            return await m.answer("Не найдено.")
        await s.delete(v)
        await s.commit()
    await m.answer(f"Удалено {vid}.")

@dp.message(Command("add"))
async def cmd_add(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    parts = [p.strip() for p in (command.args or "").split("|")]
    if len(parts) != 3:
        return await m.answer("Формат: /add <url> | <автор> | <текст>")
    url, author, text = parts
    async with Session() as s:
        v = (await s.execute(select(Video).where(Video.url == url))).scalar_one_or_none()
        if not v:
            v = Video(url=url)
            s.add(v)
            await s.flush()
        c = Comment(video_id=v.id, tiktok_id=f"manual:{m.message_id}", author=author, text=text)
        s.add(c)
        await s.flush()
        s.add(Draft(comment_id=c.id, text=f"@{author}, спасибо!"))
        await s.commit()
    await m.answer("Добавлено. /drafts")

@dp.message(Command("drafts"))
async def cmd_drafts(m: Message):
    if not is_admin(m.from_user.id):
        return
    async with Session() as s:
        rows = (await s.execute(
            select(Draft, Comment, Video)
            .join(Comment, Draft.comment_id == Comment.id)
            .join(Video, Comment.video_id == Video.id)
            .where(Draft.status == "pending")
            .order_by(Draft.id)
            .limit(15)
        )).all()
    if not rows:
        return await m.answer("Черновиков нет.")
    for d, c, v in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Готово", callback_data=f"pub:{d.id}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"rej:{d.id}"),
        ]])
        await m.answer(
            f"<b>Видео:</b> {v.url}\n"
            f"<b>@</b>{c.author}: <i>{c.text}</i>\n\n"
            f"<b>Черновик:</b>\n{d.text}",
            reply_markup=kb,
            disable_web_page_preview=True,
        )

@dp.callback_query(F.data.startswith(("pub:", "rej:")))
async def on_action(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    action, draft_id = cb.data.split(":")
    async with Session() as s:
        d = await s.get(Draft, int(draft_id))
        if not d:
            return await cb.answer("Черновик не найден")
        d.status = "approved" if action == "pub" else "rejected"
        await s.commit()
    await cb.answer("Готово. Скопируй текст и вставь в TikTok." if action == "pub" else "Удалено")

@dp.message(Command("fetch"))
async def cmd_fetch(m: Message):
    if not is_admin(m.from_user.id):
        return
    await m.answer("Собираю…")
    added = await run_fetch_cycle()
    await m.answer(f"Новых комментариев: {added}.")

async def run_fetch_cycle() -> int:
    total = 0
    async with Session() as s:
        videos = (await s.execute(select(Video).order_by(Video.id))).scalars().all()
    for v in videos:
        comments = await fetch_comments(v.url, max_count=30)
        if not comments:
            continue
        async with Session() as s:
            existing = {c.tiktok_id for c in (await s.execute(
                select(Comment).where(Comment.video_id == v.id)
            )).scalars().all()}
            for c in comments:
                if c["id"] in existing:
                    continue
                comment = Comment(video_id=v.id, tiktok_id=c["id"], author=c["author"], text=c["text"])
                s.add(comment)
                await s.flush()
                s.add(Draft(comment_id=comment.id, text=f"@{c['author']}, спасибо за комментарий!"))
                total += 1
            await s.commit()
    return total

async def scheduler_loop():
    while True:
        try:
            added = await run_fetch_cycle()
            if added:
                log.info("cycle: +%d", added)
                for aid in ADMIN_IDS:
                    try:
                        await bot.send_message(aid, f"🔔 {added} новых. /drafts")
                    except Exception:
                        pass
        except Exception as e:
            log.exception("scheduler: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SEC)

async def run_health_server():
    from aiohttp import web

    async def health(_):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    log.info("health on :%s", os.getenv("PORT", "8080"))

async def main():
    await init_db()
    if os.getenv("PORT"):
        await run_health_server()
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(scheduler_loop())
    log.info("polling…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())