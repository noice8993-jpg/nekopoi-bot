import re
import aiohttp
from bs4 import BeautifulSoup
from config import HEADERS


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

    # Fallback: direct video links in content
    if not results:
        url = _find_direct_links(post_content)
        if url:
            results.append({"label": "direct", "url": url})

    return results


def _find_iframes_in_html(html: str) -> list[str]:
    """Extract iframe src URLs from HTML string."""
    pattern = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
    return [m.group(1) for m in pattern.finditer(html)]


async def _resolve_iframe(src: str) -> str | None:
    """Follow iframe URL to find direct video source."""
    html = await _fetch_page(src)
    if not html:
        return None

    # Method 1: Direct <video> or <source> tags
    url = _parse_video_tag(html)
    if url:
        return url

    # Method 2: DoodStream pass_md5 token
    url = _parse_doodstream(html, src)
    if url:
        return url

    # Method 3: Any direct .mp4/.m3u8 URL in page
    url = _parse_direct_links(html)
    if url:
        return url

    return None


async def _fetch_page(url: str) -> str | None:
    """Fetch a page, handling redirects."""
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
    """Extract DoodStream pass_md5 token and resolve to direct URL."""
    pattern = re.compile(r"/pass_md5/[^\"'\s]+")
    match = pattern.search(html)
    if not match:
        return None

    path = match.group(0)

    # Build full URL
    if path.startswith("http"):
        doodle_url = path
    elif path.startswith("//"):
        doodle_url = "https:" + path
    else:
        # Extract domain from page_url
        from urllib.parse import urlparse
        parsed = urlparse(page_url)
        doodle_url = f"{parsed.scheme}://{parsed.netloc}{path}"

    return _resolve_doodstream(doodle_url)


def _parse_direct_links(html: str) -> str | None:
    """Find any direct .mp4/.m3u8 URL in page."""
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(html):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


def _find_direct_links(content: str) -> str | None:
    """Find direct video links in post content."""
    pattern = re.compile(r'https?://[^\s"\'<>]+\.(mp4|m3u8)([^\s"\'<>]*)', re.IGNORECASE)
    for m in pattern.finditer(content):
        url = m.group(0).rstrip(".,;:!?)")
        return url
    return None


async def _resolve_doodstream(url: str) -> str | None:
    """Follow pass_md5 redirect to get direct video URL."""
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
            async with s.get(url, allow_redirects=True, ssl=False) as resp:
                if resp.status == 200:
                    final = str(resp.url)
                    if final and final != url:
                        return final
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