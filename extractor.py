import re
import aiohttp
from bs4 import BeautifulSoup
from config import HEADERS

# Known embed domains that need special handling
DOODSTREAM_DOMAINS = {"doodstream.com", "dood.watch", "dood.la", "dooodster.com", "dood.sh"}
STREAMPOI_DOMAINS = {"streampoi.com", "streampoi.net"}
PLAYMOGO_DOMAINS = {"playmogo.com", "playmogo.net"}


async def extract_video_urls(post_content: str) -> list[dict]:
    """Extract video URLs from post HTML content.

    Returns list of dicts: {label, url, source}
    """
    soup = BeautifulSoup(post_content, "lxml")
    results = []

    iframes = soup.find_all("iframe")
    seen = set()
    for iframe in iframes:
        src = iframe.get("src", "")
        if not src or src in seen:
            continue
        seen.add(src)

        url = await _resolve_iframe(src)
        if url:
            results.append({"label": src, "url": url})

    # Fallback: check for direct video links in post content
    if not results:
        url = _find_direct_links(post_content)
        if url:
            results.append({"label": "direct", "url": url})

    return results


async def _resolve_iframe(src: str) -> str | None:
    """Follow iframe URL to find direct video source."""
    html = await _fetch_page(src)
    if not html:
        return None

    # Try each method
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


async def _fetch_page(url: str) -> str | None:
    """Fetch a page, handling redirects and SSL issues."""
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
            async with s.get(url, allow_redirects=True, ssl=False) as resp:
                return await resp.text()
    except Exception:
        return None


def _parse_video_tag(html: str) -> str | None:
    """Extract direct video URL from <video> or <source> tags."""
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
    """Extract DoodStream pass_md5 token URL."""
    # /pass_md5/<token>
    pattern = re.compile(r"[/]pass_md5/[^\"'\s]+")
    match = pattern.search(html)
    if not match:
        return None

    path = match.group(0)
    if not path.startswith("http"):
        base = page_url.split("/")[0]  # protocol
        doodle_url = f"{base}//{page_url.split('/')[2]}{path}"
    else:
        doodle_url = path

    return _resolve_doodstream(doodle_url)


def _parse_direct_links(html: str) -> str | None:
    """Find any direct .mp4/.m3u8 URL in page."""
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(html):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


def _find_direct_links(content: str) -> str | None:
    """Find direct video links in post content itself."""
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(content):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


async def _resolve_doodstream(url: str) -> str | None:
    """Resolve DoodStream pass_md5 to direct video URL."""
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
            async with s.get(url, allow_redirects=True, ssl=False) as resp:
                if resp.status == 200:
                    final = str(resp.url)
                    if final and final != url:
                        return final
                    # Some DoodStream endpoints return HTML with the URL
                    html = await resp.text()
                    return _parse_direct_links(html)
    except Exception:
        return None
    return None


async def get_download_link(post: dict) -> dict | None:
    """Get direct download link from a post object.

    Returns: {title, video_url, post_link} or None
    """
    content = post.get("content", {}).get("rendered", "")
    if not content:
        return None

    videos = await extract_video_urls(content)
    if not videos:
        return None

    return {
        "title": BeautifulSoup(post.get("title", {}).get("rendered", ""), "lxml").get_text(strip=True),
        "video_url": videos[0]["url"],
        "post_link": post.get("link", ""),
    }