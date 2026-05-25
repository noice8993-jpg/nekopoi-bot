import aiohttp
from config import API_BASE, HEADERS


async def fetch_json(url: str, params: dict = None) -> dict | list:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_posts(page: int = 1, per_page: int = 10):
    data = await fetch_json(f"{API_BASE}/posts", {"page": page, "per_page": per_page})
    total = 0
    return data, total


async def search_posts(keyword: str, page: int = 1, per_page: int = 10):
    return await fetch_json(f"{API_BASE}/posts", {
        "search": keyword, "page": page, "per_page": per_page
    })


async def get_posts_by_category(category_id: int, page: int = 1, per_page: int = 10):
    return await fetch_json(f"{API_BASE}/posts", {
        "categories": category_id, "page": page, "per_page": per_page
    })


async def get_post(post_id: int) -> dict:
    return await fetch_json(f"{API_BASE}/posts/{post_id}")


async def get_categories():
    return await fetch_json(f"{API_BASE}/categories", {"per_page": 50})