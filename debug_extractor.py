#!/usr/bin/env python3
"""Debug script to test the video extraction flow step by step."""
import asyncio
import subprocess
import re
import json

API_BASE = "https://nekopoi.care/wp-json/wp/v2"
HEADERS_JSON = "-H", "Accept: application/json"
UA = "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def curl(url: str, extra_headers: list = None, timeout: int = 30) -> str:
    cmd = ["curl", "-s", "-L", UA, "--max-time", str(timeout)]
    if extra_headers:
        cmd.extend(extra_headers)
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    return r.stdout


async def debug():
    print("=" * 70)
    print("STEP 1: Get latest posts from API")
    print("=" * 70)
    data = curl(f"{API_BASE}/posts?per_page=3", [*HEADERS_JSON])
    posts = json.loads(data)

    for p in posts[:3]:
        print(f"  ID={p['id']} | Title={p['title']['rendered'][:60]}")
        print(f"  Link={p['link']}")

    post = posts[0]
    pid = post["id"]

    print(f"\n{'=' * 70}")
    print(f"STEP 2: Fetch full post ID={pid} via API + click link")
    print("=" * 70)

    print(f"\n--- 2a: API content.rendered (800 chars) ---")
    full = curl(f"{API_BASE}/posts/{pid}", [*HEADERS_JSON])
    fp = json.loads(full)
    content = fp.get("content", {}).get("rendered", "")
    iframes_in_api = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
    print(f"  Content length: {len(content)} chars")
    print(f"  Iframes in API content: {len(iframes_in_api)}")
    print(f"  Content preview: {content[:800]}")

    link = fp["link"]
    print(f"\n--- 2b: Fetch full HTML page: {link} ---")
    html = curl(link, ["-H", "Accept: text/html,*/*", "-H", "Referer: https://nekopoi.care/"])
    print(f"  HTML size: {len(html)} bytes")

    if "cdn-cgi/challenge" in html or "__cf_chl" in html:
        print("  !! CLOUDFLARE CHALLENGE - but also checking curl headers...")
        # Also try with -v to see response info
        cmd = ["curl", "-s", "-L", "-o", "/dev/null", "-w", "%{http_code} %{url_effective}", UA, link]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        print(f"  curl -w output: {r.stdout}")

    print(f"\n--- 2c: Look for iframes in full HTML ---")
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    print(f"  Iframes found: {len(iframes)}")
    for i, src in enumerate(iframes[:5]):
        print(f"    [{i}] {src}")

    if not iframes:
        print("\n  Try BeautifulSoup...")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        bs_frames = soup.find_all("iframe")
        print(f"  BS4 iframes: {len(bs_frames)}")
        for ifr in bs_frames[:5]:
            print(f"    src={ifr.get('src')}")

        # Search for any video-related content
        vid_urls = re.findall(r'https?://[^\s"\'<>]+\.(mp4|m3u8)', html, re.IGNORECASE)
        print(f"  Direct .mp4/.m3u8 URLs: {vid_urls}")

    if iframes:
        src = iframes[0]
        print(f"\n{'=' * 70}")
        print(f"STEP 3: Resolve iframe: {src}")
        print("=" * 70)

        embed = curl(src)
        print(f"  Embed HTML size: {len(embed)} bytes")

        pass_md5 = re.search(r'/pass_md5/[^"\'\s]+', embed)
        if pass_md5:
            path = pass_md5.group(0)
            print(f"  Found pass_md5: {path}")

            # Build doodle URL
            from urllib.parse import urlparse
            parsed = urlparse(src)
            doodle_url = f"{parsed.scheme}://{parsed.netloc}{path}"
            print(f"  Doodle URL: {doodle_url}")

            doodle_resp = curl(doodle_url)
            print(f"  Doodle response ({len(doodle_resp)} bytes): [{doodle_resp[:300}]")

            # Check if it's a raw URL
            trimmed = doodle_resp.strip()
            if trimmed.startswith("http"):
                print(f"\n*** SUCCESS! Raw video URL: {trimmed[:150]} ***")
            else:
                # Search for mp4/m3u8
                vids = re.findall(r'https?://[^\s"\'<>]+\.(mp4|m3u8)', trimmed, re.IGNORECASE)
                if vids:
                    print(f"\n*** SUCCESS! Video URL from HTML: {vids[0][:150]} ***")
                else:
                    vids = re.findall(r'https?://[^\s"\'<>]+', trimmed)
                    if vids:
                        print(f"\n*** Potential video URL: {vids[0][:150]} ***")
                    else:
                        print("\n*** NO VIDEO URL FOUND ***")


if __name__ == "__main__":
    asyncio.run(debug())