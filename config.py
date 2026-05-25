import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8009135836:AAGlWC2Jaj47bF8C29Yd22nOQJLKfvoWCAM")
API_BASE = "https://nekopoi.care/wp-json/wp/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

CATEGORIES = {
    2: "Hentai",
    81: "3D Hentai",
    4: "JAV",
    682: "2D Animation",
    1: "JAV Cosplay",
    597: "JAV Subtitle Indonesia",
}

MAX_FILE_SIZE = 1.8 * 1024 * 1024 * 1024  # 1.8GB (Telegram Local API limit)

# Rate limiting - delay detween API calls (seconds)
RATE_LIMIT_DELAY = 1.0

# Download config
DOWNLOAD_TIMEOUT = 900  # 15 minutes max for downloads
PER_PAGE = 10