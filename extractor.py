import re
import asyncio
import cloudscraper
from bs4 import BeautifulSoup
from config import HEADERS

_SCRAPER = cloudscraper.create_scraper()
_LOCK = asyncio.Lock()


async def extract_video_urls(post_content: str, page_url: str = None) -> list[dict]:
    """Extract video URLs from post.

    The WordPress API content often lacks iframes, so we fetch the full page
    if page_url is provided and no iframes found in content.
    """
    iframes = _find_iframes_in_html(post_content)

    # If no iframes in API content, fetch full page
    if not iframes and page_url:
        html = await _fetch_page(page_url)
        if html:
            iframes = _find_iframes_in_html(html)

    results = []
    seen = set()
    for src in iframes:
        if src in seen:
            continue
        seen.add(src)
        url = await _resolve_iframe(src)
        if url:
            results.append({"label": src, "url": url})

    if not results:
        url = _find_direct_links(post_content)
        if url:
            results.append({"label": "direct", "url": url})

    return results


def _find_iframes_in_html(html: str) -> list[str]:
    pattern = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
    return [m.group(1) for m in pattern.finditer(html)]


async def _fetch_page(url: str) -> str | None:
    """Fetch a page using cloudscraper to bypass Cloudflare."""
    loop = asyncio.get_event_loop()
    try:
        async with _LOCK:
            return await loop.run_in_executor(None, _sync_fetch, url)
    except Exception:
        return None


def _sync_fetch(url: str) -> str:
    resp = _SCRAPER.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _resolve_iframe(src: str) -> str | None:
    html = await _fetch_page(src)
    if not html:
        return None

    url = _parse_video_tag(html)
    if url:
        return url

    url = _parse_doodstream(html, src)
    if url:
        return url

    url = _parse_direct_links(html)
    if url:
        return url

    return None


def _parse_video_tag(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    video = soup.find("video")
    if video:
        src = video.get("src")
        if src:
            return src
    for source in soup.find_all("source"):
        src = source.get("src")
        if src:
            return src
    return None


def _parse_doodstream(html: str, page_url: str) -> str | None:
    pattern = re.compile(r"/pass_md5/[^\"'\s]+")
    match = pattern.search(html)
    if not match:
        return None

    path = match.group(0)
    if path.startswith("http"):
        doodle_url = path
    elif path.startswith("//"):
        doodle_url = "https:" + path
    else:
        from urllib.parse import urlparse
        parsed = urlparse(page_url)
        doodle_url = f"{parsed.scheme}://{parsed.netloc}{path}"

    return _resolve_doodstream(doodle_url)


def _parse_direct_links(html: str) -> str | None:
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(html):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


def _find_direct_links(content: str) -> str | None:
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(content):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


def _sync_fetch_doodstream(url: str) -> str | None:
    """Sync resolve DoodStream pass_md5 using cloudscraper."""
    try:
        resp = _SCRAPER.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            return None
        final = str(resp.url)
        if final != url:
            return final
        body = resp.text.strip()
        if body.startswith("http://") or body.startswith("https://"):
            if not body.startswith("<"):
                return body.split("\n")[0].strip()
        return _parse_direct_links(body)
    except Exception:
        return None


async def _resolve_doodstream(url: str) -> str | None:
    loop = asyncio.get_event_loop()
    try:
        async with _LOCK:
            return await loop.run_in_executor(None, _sync_fetch_doodstream, url)
    except Exception:
        return None


async def get_download_link(post: dict) -> dict | None:
    content = post.get("content", {}).get("rendered", "")
    link = post.get("link", "")

    videos = await extract_video_urls(content, page_url=link)
    if not videos:
        return None

    return {
        "title": BeautifulSoup(
            post.get("title", {}).get("rendered", ""), "lxml"
        ).get_text(strip=True),
        "video_url": videos[0]["url"],
        "post_link": link,
    }