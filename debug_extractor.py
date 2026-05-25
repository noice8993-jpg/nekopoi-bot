#!/usr/bin/env python3
"""Debug script to test the video extraction flow step by step."""
import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup

API_BASE = "https://nekopoi.care/wp-json/wp/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def step1_get_latest_posts():
    print("\n=== STEP 1: Get latest posts ===")
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(f"{API_BASE}/posts?per_page=3") as resp:
            data = await resp.json()
            for p in data:
                print(f"  ID: {p['id']} | Title: {p['title']['rendered'][:60]}")
                print(f"  Link: {p['link']}")
            return data[0] if data else None


async def step2_check_api_content(post):
    print("\n=== STEP 2: Check WordPress API content.rendered ===")
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(f"{API_BASE}/posts/{post['id']}") as resp:
            full = await resp.json()
            content = full.get("content", {}).get("rendered", "")
            # Search for iframes in content
            iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
            print(f"  Content length: {len(content)} chars")
            print(f"  Iframes found in API content: {len(iframes)}")
            if iframes:
                for i, src in enumerate(iframes[:3]):
                    print(f"    [{i}] {src}")
            else:
                print("  (No iframes in API content - need to fetch full page)")
            return content, iframes


async def step3_fetch_full_page(post_url):
    print(f"\n=== STEP 3: Fetch full HTML page ===")
    print(f"  URL: {post_url}")
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HTML_HEADERS, timeout=timeout) as s:
            async with s.get(post_url, allow_redirects=True, ssl=False) as resp:
                status = resp.status
                final_url = str(resp.url)
                print(f"  Status: {status}")
                print(f"  Final URL: {final_url}")
                html = await resp.text()
                print(f"  HTML size: {len(html)} bytes")

                # Check if Cloudflare challenge
                if "cdn-cgi/challenge" in html or "cloudflare" in html.lower() and "challenge" in html.lower():
                    print("  !! CLOUDFLARE CHALLENGE DETECTED !!")
                    print(f"  HTML preview: {html[:500]}")
                    return None

                # Search for iframes
                iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
                print(f"  Iframes found: {len(iframes)}")
                if iframes:
                    for i, src in enumerate(iframes[:5]):
                        print(f"    [{i}] {src}")
                else:
                    print("  No iframes found!")
                    # Try BeautifulSoup as backup
                    soup = BeautifulSoup(html, "lxml")
                    bs_iframes = soup.find_all("iframe")
                    print(f"  BS4 iframes: {len(bs_iframes)}")
                    for i, ifr in enumerate(bs_iframes[:5]):
                        print(f"    [{i}] src={ifr.get('src')}")

                return html
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


async def step4_resolve_iframe(iframe_src):
    print(f"\n=== STEP 4: Resolve iframe: {iframe_src} ===")
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HTML_HEADERS, timeout=timeout) as s:
            async with s.get(iframe_src, allow_redirects=True, ssl=False) as resp:
                html = await resp.text()
                print(f"  Status: {resp.status}, HTML size: {len(html)} bytes")

                # Search for pass_md5
                pass_md5 = re.search(r'/pass_md5/[^"\'\s]+', html)
                if pass_md5:
                    path = pass_md5.group(0)
                    print(f"  Found pass_md5: {path}")

                    # Build full URL
                    from urllib.parse import urlparse
                    parsed = urlparse(iframe_src)
                    doodle_url = f"{parsed.scheme}://{parsed.netloc}{path}"
                    print(f"  Doodle URL: {doodle_url}")

                    # Resolve it
                    print("  Resolving pass_md5...")
                    async with s.get(doodle_url, allow_redirects=True, ssl=False) as dr:
                        print(f"  pass_md5 status: {dr.status}")
                        print(f"  pass_md5 final URL: {dr.url}")
                        body = await dr.text()
                        print(f"  pass_md5 body: [{body[:300}]")
                        return body.strip()
                else:
                    print("  No pass_md5 found")
                    return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


async def main():
    print("=" * 60)
    print("NEKOPOI VIDEO EXTRACTOR DEBUG")
    print("=" * 60)

    post = await step1_get_latest_posts()
    if not post:
        print("FAILED: No posts found")
        return

    print(f"\nSelected post: ID={post['id']}, URL={post['link']}")

    api_content, api_iframes = await step2_check_api_content(post)

    page_html = await step3_fetch_page(post['link'])
    if not page_html:
        print("\n*** PAGE FETCH FAILED - this is likely the bug ***")
        return

    # Try first iframe
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
    if not iframes:
        # Try BeautifulSoup
        soup = BeautifulSoup(page_html, "lxml")
        iframes = [ifr.get('src') for ifr in soup.find_all('iframe') if ifr.get('src')]

    if iframes:
        print(f"\nWill try to resolve first iframe: {iframes[0]}")
        video_url = await step4_resolve_iframe(iframes[0])
        if video_url and video_url.startswith("http"):
            print(f"\n*** SUCCESS! Video URL: {video_url[:100]} ***")
        else:
            print(f"\n*** FAILED to resolve video URL ***")
    else:
        print("\n*** NO IFRAMES FOUND IN PAGE ***")


if __name__ == "__main__":
    asyncio.run(main())