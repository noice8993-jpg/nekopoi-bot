import logging
from html import unescape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

from config import BOT_TOKEN, CATEGORIES, MAX_FILE_SIZE
from api import get_posts, search_posts, get_posts_by_category, get_post
from extractor import get_download_link

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE = {}  # simple in-memory: {key: {posts, page, total}}


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\u2728 *Nekopoi Bot*\n\n"
        "/search <keyword> - Cari video\n"
        "/latest - Video terbaru\n"
        "/categories - Pilih kategori\n"
        "/download <id> - Download video\n\n"
        "Powered by nekopoi.care",
        parse_mode="Markdown",
    )


async def latest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data, _ = await get_posts(page=1)
    await _show_post_list(update, ctx, data, "latest_1")


async def search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: /search <keyword>")
        return
    keyword = " ".join(ctx.args)
    data = await search_posts(keyword)
    key = f"search_{keyword}"
    CACHE[key] = {"posts": data, "keyword": keyword}
    await _show_post_list(update, ctx, data, key)


async def categories_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"cat_{cid}")]
        for cid, name in CATEGORIES.items()
    ]
    await update.message.reply_text(
        "Pilih kategori:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("cat_"):
        cat_id = int(data.split("_")[1])
        posts = await get_posts_by_category(cat_id)
        key = f"cat_{cat_id}"
        CACHE[key] = {"posts": posts}
        await _show_post_list(update, ctx, posts, key, edit=True)

    elif data.startswith("dl_"):
        post_id = int(data.split("_")[1])
        await _handle_download(query, ctx, post_id)

    elif data.startswith("page_"):
        _, cache_key, page_str = data.split("_", 2)
        page = int(page_str)
        cached = CACHE.get(cache_key)
        if not cached:
            await query.edit_message_text("Session expired, cari lagi.")
            return
        keyword = cached.get("keyword")
        cat_id = cached.get("cat_id")
        if keyword:
            posts = await search_posts(keyword, page=page)
        elif cat_id:
            posts = await get_posts_by_category(cat_id, page=page)
        else:
            posts, _ = await get_posts(page=page)
        await _show_post_list(update, ctx, posts, cache_key, edit=True)


async def _show_post_list(update, ctx, posts, cache_key, edit=False):
    if not posts:
        text = "Tidak ada hasil."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    lines = []
    keyboard = []
    for p in posts[:10]:
        pid = p["id"]
        title = unescape(p.get("title", {}).get("rendered", "No title"))
        date = p.get("date", "")[:10]
        lines.append(f"<b>{pid}</b>. {title} ({date})")
        keyboard.append([InlineKeyboardButton(f"{pid} - {title[:40]}", callback_data=f"dl_{pid}")])

    text = "\n".join(lines)

    if edit:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def _handle_download(obj, ctx, post_id):
    """obj is either a CallbackQuery or Update."""
    chat_id = obj.message.chat_id if hasattr(obj, "message") else obj.effective_chat.id
    edit = obj.edit_message_text if hasattr(obj, "edit_message_text") else None

    if edit:
        await edit("Mengambil info video...")
    try:
        post = await get_post(post_id)
    except Exception as e:
        msg = f"Gagal ambil post: {e}"
        if edit:
            await edit(msg)
        return

    dl = await get_download_link(post)
    if not dl:
        msg = "Tidak ada video yang ditemukan di post ini."
        if edit:
            await edit(msg)
        return

    title = dl["title"]
    video_url = dl["video_url"]
    post_link = dl["post_link"]

    msg = None
    if edit:
        msg = await edit(
            f"*Download:* {title}\n\n"
            f"Mengirim video... (bisa lama untuk file besar)",
            parse_mode="Markdown",
        )

    try:
        await ctx.bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=f"<b>{title}</b>\n\n{post_link}",
            parse_mode="HTML",
            supports_streaming=True,
            read_timeout=600,
            write_timeout=600,
            connect_timeout=60,
            pool_timeout=600,
        )
        if msg:
            await msg.delete()
    except Exception:
        try:
            await ctx.bot.send_document(
                chat_id=chat_id,
                document=video_url,
                caption=f"<b>{title}</b>\n\n{post_link}",
                parse_mode="HTML",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=600,
            )
            if msg:
                await msg.delete()
        except Exception as e2:
            text = f"Gagal kirim video.\nLink langsung: {video_url}\n\nError: {e2}"
            if edit:
                await edit(text)
            else:
                await obj.message.reply_text(text) if hasattr(obj, "message") else None


async def download_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: /download <post_id>")
        return
    try:
        post_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("ID harus angka.")
        return
    await _handle_download(update, ctx, post_id)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("categories", categories_menu))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Set BOT_TOKEN environment variable!")
        exit(1)
    main()