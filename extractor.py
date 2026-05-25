import re
import asyncio
import subprocess
from bs4 import BeautifulSoup
from config import HEADERS


async def extract_video_urls(post_content: str, page_url: str = None) -> list[dict]:
    iframes = _find_iframes_in_html(post_content)
    if not iframes and page_url:
        html = await _fetch_page_with_curl(page_url)
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


async def _fetch_page_with_curl(url: str) -> str | None:
    """Use subprocess curl to bypass Cloudflare (same as working curl in terminal)."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _sync_curl, url)
    except Exception as e:
        return None


def _sync_curl(url: str) -> str:
    ua = HEADERS["User-Agent"]
    cmd = [
        "curl", "-s", "-L",
        "-A", ua,
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.5",
        "-H", "Referer: https://nekopoi.care/",
        "-H", "DNT: 1",
        "--max-time", "30",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if result.returncode != 0:
        return None
    html = result.stdout
    # Check if Cloudflare challenge
    if "cdn-cgi/challenge" in html or ("cloudflare" in html.lower() and "__cf_chl" in html):
        return None
    return html


def _sync_curl_get(url: str) -> str | None:
    """Fetch URL with curl and return response body."""
    ua = HEADERS["User-Agent"]
    cmd = [
        "curl", "-s", "-L",
        "-A", ua,
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Referer: https://playmogo.com/",
        "--max-time", "30",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if result.returncode != 0:
        return None
    return result.stdout


async def _resolve_iframe(src: str) -> str | None:
    html = await _fetch_page_with_curl(src)
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


async def _resolve_doodstream(url: str) -> str | None:
    """Resolve DoodStream pass_md5 via curl."""
    loop = asyncio.get_event_loop()
    try:
        body = await loop.run_in_executor(None, _sync_curl_get, url)
        if not body:
            return None
        body = body.strip()
        if body.startswith("http://") or body.startswith("https://"):
            if not body.startswith("<"):
                return body.split("\n")[0].strip()
        return _parse_direct_links(body)
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