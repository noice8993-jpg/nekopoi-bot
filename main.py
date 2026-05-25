import logging
import time
import math
from html import unescape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from telegram.error import TelegramError

from config import BOT_TOKEN, CATEGORIES, MAX_FILE_SIZE, DOWNLOAD_TIMEOUT
from api import get_posts, search_posts, get_posts_by_category, get_post
from extractor import get_download_link

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Cache: {key: {posts, keyword, cat_id, page, total}}
_CACHE = {}
# Track pending downloads to avoid duplicates: {chat_id: post_id}
_DOWNLOADING = {}


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\u2728 *Nekopoi Bot*\n\n"
        "/search <keyword> - Cari video\n"
        "/latest - Video terbaru\n"
        "/categories - Pilih kategori\n"
        "/download <id> - Download video langsung\n\n"
        "Powered by nekopoi.care",
        parse_mode="Markdown",
    )


async def latest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await get_posts(page=1)
    except Exception as e:
        await update.message.reply_text(f"Gagal ambil data: {e}")
        return
    key = "latest_1"
    _CACHE[key] = {"posts": data, "page": 1}
    await _show_post_list(update, ctx, data, key)


async def search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: /search <keyword>\nContoh: /search one piece")
        return
    keyword = " ".join(ctx.args)
    await update.message.reply_text(f"Mencari \"{keyword}\"...")
    try:
        data = await search_posts(keyword)
    except Exception as e:
        await update.message.reply_text(f"Gagal search: {e}")
        return

    key = f"search_{keyword}"
    _CACHE[key] = {"posts": data, "keyword": keyword, "page": 1}
    await _show_post_list(update, ctx, data, key)


async def categories_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    row = []
    for i, (cid, name) in enumerate(CATEGORIES.items()):
        row.append(InlineKeyboardButton(name, callback_data=f"cat_{cid}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "\U0001f4c2 *Pilih Kategori:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data.startswith("cat_"):
            cat_id = int(data.split("_")[1])
            name = CATEGORIES.get(cat_id, f"Kategori {cat_id}")
            await query.edit_message_text(f"Mengambil {name}...")
            posts = await get_posts_by_category(cat_id)
            key = f"cat_{cat_id}"
            _CACHE[key] = {"posts": posts, "cat_id": cat_id, "page": 1}
            await _show_post_list(update, ctx, posts, key, edit=True)

        elif data.startswith("dl_"):
            post_id = int(data.split("_")[1])
            await _handle_download(query, ctx, post_id)

        elif data.startswith("page_"):
            parts = data.split("_", 2)
            cache_key = parts[1]
            page = int(parts[2])
            cached = _CACHE.get(cache_key)
            if not cached:
                await query.edit_message_text("Session habis, cari lagi ya.")
                return

            keyword = cached.get("keyword")
            cat_id = cached.get("cat_id")
            try:
                if keyword:
                    posts = await search_posts(keyword, page=page)
                elif cat_id:
                    posts = await get_posts_by_category(cat_id, page=page)
                else:
                    posts = await get_posts(page=page)
            except Exception as e:
                await query.edit_message_text(f"Gagal ambil halaman: {e}")
                return

            cached["posts"] = posts
            cached["page"] = page
            await _show_post_list(update, ctx, posts, cache_key, edit=True)

        elif data.startswith("refresh_"):
            cache_key = data.split("_", 1)[1]
            cached = _CACHE.get(cache_key)
            if not cached:
                await query.edit_message_text("Session habis.")
                return
            page = cached.get("page", 1)
            keyword = cached.get("keyword")
            cat_id = cached.get("cat_id")
            try:
                if keyword:
                    posts = await search_posts(keyword, page=page)
                elif cat_id:
                    posts = await get_posts_by_category(cat_id, page=page)
                else:
                    posts = await get_posts(page=page)
            except Exception as e:
                await query.edit_message_text(f"Gagal refresh: {e}")
                return
            cached["posts"] = posts
            await _show_post_list(update, ctx, posts, cache_key, edit=True)

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        try:
            await query.edit_message_text(f"Error: {e}")
        except Exception:
            pass


async def _show_post_list(update, ctx, posts, cache_key, edit=False):
    """Show paginated post list with download buttons."""
    cached = _CACHE.get(cache_key, {})
    page = cached.get("page", 1)

    if not posts:
        text = "Tidak ada hasil."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    total_posts = len(posts)
    display = posts[:10]

    lines = []
    keyboard = []
    for p in display:
        pid = p["id"]
        title = unescape(p.get("title", {}).get("rendered", "No title"))
        date = p.get("date", "")[:10]
        lines.append(f"<b>{pid}.</b> {title} ({date})")
        keyboard.append([
            InlineKeyboardButton(f"\u25b6 Download {pid}", callback_data=f"dl_{pid}")
        ])

    text = "\n".join(lines)

    # Pagination buttons
    nav_buttons = []
    if page > 1:
        prev_page = page - 1
        nav_buttons.append(
            InlineKeyboardButton("\u25c0 Prev", callback_data=f"page_{cache_key}_{prev_page}")
        )
    if total_posts >= 10:
        next_page = page + 1
        nav_buttons.append(
            InlineKeyboardButton("Next \u25b6", callback_data=f"page_{cache_key}_{next_page}")
        )
    if nav_buttons:
        keyboard.append(nav_buttons)

    # Refresh button
    keyboard.append([
        InlineKeyboardButton("\U0001f504 Refresh", callback_data=f"refresh_{cache_key}")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = f"\U0001f4c1 Halaman {page}\n\n{text}"

    if edit:
        try:
            await update.callback_query.edit_message_text(
                msg_text, parse_mode="HTML", reply_markup=reply_markup
            )
        except TelegramError as e:
            if "not modified" in str(e).lower():
                pass
            else:
                raise
    else:
        await update.message.reply_text(
            msg_text, parse_mode="HTML", reply_markup=reply_markup
        )


async def _handle_download(obj, ctx, post_id):
    """Handle download flow with progress reporting."""
    chat_id = obj.message.chat_id if hasattr(obj, "message") else obj.effective_chat.id
    edit = obj.edit_message_text if hasattr(obj, "edit_message_text") else None
    reply = obj.reply_text if hasattr(obj, "reply_text") else None

    # Prevent duplicate downloads in same chat
    if _DOWNLOADING.get(chat_id) == post_id:
        msg = f"Post {post_id} sedang di-download, tunggu selesai."
        if edit:
            await edit(msg)
        return

    _DOWNLOADING[chat_id] = post_id
    status_msg = None

    try:
        # Step 1: Fetch post
        if edit:
            status_msg = await edit("\U0001f4e1 Mengambil info video...")
        else:
            status_msg = await obj.message.reply_text("\U0001f4e1 Mengambil info video...")

        try:
            post = await get_post(post_id)
        except Exception as e:
            err = f"Gagal ambil post {post_id}: {e}"
            if edit:
                await edit(err)
            else:
                await status_msg.edit_text(err)
            return

        # Step 2: Extract video
        if status_msg:
            await status_msg.edit_text("\U0001f50d Mengekstrak link video...")

        dl = await get_download_link(post)
        if not dl:
            err = "Tidak ada video yang ditemukan di post ini."
            if edit:
                await edit(err)
            else:
                await status_msg.edit_text(err)
            return

        title = dl["title"]
        video_url = dl["video_url"]
        post_link = dl["post_link"]

        # Step 3: Send video
        if status_msg:
            try:
                await status_msg.edit_text(
                    f"\u25b6 Mendownload: <b>{title[:50]}</b>\n"
                    f"Tunggu ya, bisa lama untuk file besar...",
                    parse_mode="HTML",
                )
            except TelegramError:
                pass

        # Get file size first via HEAD request
        file_size = None
        try:
            import aiohttp
            from config import HEADERS
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
                async with s.head(video_url, allow_redirects=True, ssl=False) as resp:
                    content_len = resp.headers.get("Content-Length")
                    if content_len:
                        file_size = int(content_len)
        except Exception:
            pass

        if file_size and file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            err = (
                f"File terlalu besar ({size_mb:.0f}MB > 1.8GB).\n"
                f"Link langsung: {video_url}"
            )
            if edit:
                await edit(err)
            else:
                await status_msg.edit_text(err)
            return

        # Send via Telegram
        caption = f"<b>{unescape(title)}</b>\n{post_link}"
        if file_size:
            size_mb = file_size / (1024 * 1024)
            caption += f"\n({size_mb:.0f}MB)" if size_mb > 0 else ""

        try:
            await ctx.bot.send_video(
                chat_id=chat_id,
                video=video_url,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                read_timeout=DOWNLOAD_TIMEOUT,
                write_timeout=DOWNLOAD_TIMEOUT,
                connect_timeout=120,
                pool_timeout=DOWNLOAD_TIMEOUT,
            )
            if status_msg:
                try:
                    await status_msg.delete()
                except TelegramError:
                    pass
        except TelegramError as e:
            err = str(e)
            if "413" in err or "too large" in err.lower():
                fallback = f"File terlalu besar untuk Telegram.\nLink langsung: {video_url}"
                if edit:
                    await edit(fallback)
                elif status_msg:
                    await status_msg.edit_text(fallback)
            else:
                # Fallback: send as document
                try:
                    await ctx.bot.send_document(
                        chat_id=chat_id,
                        document=video_url,
                        caption=caption,
                        parse_mode="HTML",
                        read_timeout=DOWNLOAD_TIMEOUT,
                        write_timeout=DOWNLOAD_TIMEOUT,
                        connect_timeout=120,
                        pool_timeout=DOWNLOAD_TIMEOUT,
                    )
                    if status_msg:
                        try:
                            await status_msg.delete()
                        except TelegramError:
                            pass
                except Exception as e2:
                    fallback = (
                        f"Gagal kirim video.\n"
                        f"Error: {e2}\n\n"
                        f"Link langsung: {video_url}"
                    )
                    if edit:
                        await edit(fallback)
                    elif status_msg:
                        await status_msg.edit_text(fallback)

    except Exception as e:
        logger.error(f"Download error post {post_id}: {e}", exc_info=True)
        try:
            err = f"Error download: {e}"
            if edit:
                await edit(err)
            elif status_msg:
                await status_msg.edit_text(err)
        except Exception:
            pass
    finally:
        _DOWNLOADING.pop(chat_id, None)


async def download_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Gunakan: /download <post_id>\nContoh: /download 12345")
        return
    try:
        post_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("ID harus angka.")
        return

    msg = await update.message.reply_text("\U0001f4e1 Memproses...")
    await _handle_download(msg, ctx, post_id)


def main():
    try:
        app = Application.builder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler(["latest", "terbaru"], latest))
        app.add_handler(CommandHandler(["search", "cari"], search))
        app.add_handler(CommandHandler(["categories", "kategori", "cat"], categories_menu))
        app.add_handler(CommandHandler(["download", "dl"], download_command))
        app.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("Bot started. Press Ctrl+C to stop.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()