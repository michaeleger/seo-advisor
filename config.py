import os
from dotenv import load_dotenv

load_dotenv()

GSC_CREDENTIALS_FILE = os.getenv("GSC_CREDENTIALS_FILE", "client_secret.json")
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "https://eagertobehealthy.com/")
WP_SITE_URL = os.getenv("WP_SITE_URL", "https://eagertobehealthy.com")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

DATE_RANGE_DAYS = int(os.getenv("DATE_RANGE_DAYS", "90"))
MIN_IMPRESSIONS = int(os.getenv("MIN_IMPRESSIONS", "50"))
MAX_CTR = float(os.getenv("MAX_CTR", "0.05"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "20"))
MAX_POSTS_TO_ANALYZE = int(os.getenv("MAX_POSTS_TO_ANALYZE", "10"))

COOLDOWN_DAYS = int(os.getenv("COOLDOWN_DAYS", "60"))
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
