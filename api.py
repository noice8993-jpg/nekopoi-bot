import asyncio
import aiohttp
from config import API_BASE, HEADERS, RATE_LIMIT_DELAY, PER_PAGE

_last_request = 0


async def _rate_limited():
    """Ensure delay between requests to avoid getting banned."""
    global _last_request
    now = asyncio.get_event_loop().time()
    wait = RATE_LIMIT_DELAY - (now - _last_request)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request = now


async def fetch_json(url: str, params: dict = None) -> dict | list:
    await _rate_limited()
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(url, params=params, timeout=30) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_posts(page: int = 1, per_page: int = PER_PAGE):
    data = await fetch_json(f"{API_BASE}/posts", {"page": page, "per_page": per_page})
    return data


async def search_posts(keyword: str, page: int = 1, per_page: int = PER_PAGE):
    return await fetch_json(f"{API_BASE}/posts", {
        "search": keyword, "page": page, "per_page": per_page
    })


async def get_posts_by_category(category_id: int, page: int = 1, per_page: int = PER_PAGE):
    return await fetch_json(f"{API_BASE}/posts", {
        "categories": category_id, "page": page, "per_page": per_page
    })


async def get_post(post_id: int) -> dict:
    return await fetch_json(f"{API_BASE}/posts/{post_id}")


async def get_categories():
    return await fetch_json(f"{API_BASE}/categories", {"per_page": 50})