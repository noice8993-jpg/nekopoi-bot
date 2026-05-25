import re
import aiohttp
from bs4 import BeautifulSoup
from config import HEADERS


async def extract_video_urls(post_content: str) -> list[dict]:
    """Extract video URLs from post HTML content.

    Returns list of dicts: {label, url, resolution}
    """
    soup = BeautifulSoup(post_content, "lxml")
    results = []

    iframes = soup.find_all("iframe")
    for iframe in iframes:
        src = iframe.get("src", "")
        if not src:
            continue
        url = await _resolve_iframe(src)
        if url:
            results.append({"label": src, "url": url})

    return results


async def _resolve_iframe(src: str) -> str | None:
    """Follow iframe URL to find direct video source."""
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(src, allow_redirects=True, timeout=30) as resp:
                html = await resp.text()
    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")

    # Direct video tag
    video = soup.find("video")
    if video:
        src = video.get("src")
        if src:
            return src

    # Source tags inside video
    for source in soup.find_all("source"):
        s = source.get("src")
        if s:
            return s

    # DoodStream-style: pass_md5 token
    doodle_pattern = re.compile(r"/pass_md5/[^\'\"]+")
    match = doodle_pattern.search(html)
    if match:
        doodle_url = "https:" + match.group(0) if match.group(0).startswith("//") else match.group(0)
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as s:
                async with s.get(doodle_url, allow_redirects=True, timeout=30) as resp:
                    if resp.status == 200:
                        final_url = str(resp.url)
                        if final_url:
                            return final_url
        except Exception:
            pass

    # Generic: find any direct video URL in page
    vid_pattern = re.compile(r'https?://[^\s"\']+\.(mp4|m3u8)[^\s"\']*')
    for m in vid_pattern.finditer(html):
        return m.group(0)

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