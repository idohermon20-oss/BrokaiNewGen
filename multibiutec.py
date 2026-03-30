# multi_biotech_alert_bot.py
# ניטור הודעות חדשות בכמה אתרי IR + התראה לטלגרם עם שם החברה, כותרת וקישור
# הפעלה: pip install requests beautifulsoup4

import json
import time
import re
import traceback
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ===== פרטי הטלגרם שלך =====
BOT_TOKEN = "7657021379:AAEGJYIWlUFc6NvcKsxjDjbZqI4MdITgH90"
CHAT_ID = "507193413"   # דוגמה: 123456789 (פרטי) או -100123456789 (קבוצה)

# ===== רשימת חברות למעקב (אפשר להוסיף/להוריד חופשי) =====
COMPANIES = [
    {
        "name": "aTyr Pharma",
        "ticker": "ATYR",
        "news_url": "https://investors.atyrpharma.com/news-releases",
        "base_url": "https://investors.atyrpharma.com",
        "selectors": [
            "div.view-news-releases a",
            "ul.news-releases a",
            "li.views-row a",
            "a[href*='news-release']",
            "a[href*='press']"
        ],
    },
    {
        "name": "KALA Bio",
        "ticker": "KALA",
        "news_url": "https://investors.kalarx.com/press-releases",
        "base_url": "https://investors.kalarx.com",
        "selectors": [
            "ul.press-releases a",
            "div.press-releases a",
            "li a",
            "a[href*='press']",
            "a[href*='news']"
        ],
    },
    {
        "name": "Rapport Therapeutics",
        "ticker": "RAPP",
        "news_url": "https://investors.rapportrx.com/news-events/news-releases",
        "base_url": "https://investors.rapportrx.com",
        "selectors": [
            "div.view-news-releases a",
            "ul.news-releases a",
            "li.views-row a",
            "a[href*='news-release']",
            "a[href*='press']",
            "a[href*='news']"
        ],
    },
    {
        "name": "Omeros",
        "ticker": "OMER",
        "news_url": "https://investor.omeros.com/press-releases",
        "base_url": "https://investor.omeros.com",
        "selectors": [
            "ul.press-releases a",
            "div.press-releases a",
            "li a",
            "a[href*='press-releases']",
            "a[href*='news']"
        ],
    },
    {
        "name": "Crinetics",
        "ticker": "CRNX",
        "news_url": "https://crinetics.com/press-releases/",
        "base_url": "https://crinetics.com",
        "selectors": [
            "div.news-list a",
            "ul.news a",
            "li a",
            "a[href*='press-releases']",
            "a[href*='news']"
        ],
    },
]


# ===== הגדרות כלליות =====
CHECK_EVERY_SECONDS = 60   # בדיקה כל דקה (שנה לפי הצורך)
STATE_FILE = Path("multi_biotech_state.json")
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ===== פונקציות עזר =====
def send_telegram(text: str) -> None:
    """שולח הודעת טקסט לטלגרם דרך הבוט."""
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(api, data=data, timeout=15)
        r.raise_for_status()
    except Exception:
        print("[TELEGRAM] כשל בשליחה:\n", traceback.format_exc())

def load_state() -> dict:
    """טוען מצב אחרון שנשלח לכל חברה כדי להימנע מכפילויות."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # מפתח הוא ה-ticker; כל ערך: {"last_title": "", "last_href": ""}
    return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def absolutize(href: str, base_url: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    # href יחסי
    return base_url.rstrip("/") + href

def fetch_latest_item(company: dict) -> tuple[str, str]:
    url = company["news_url"]
    base = company["base_url"]
    selectors = company["selectors"]

    r = requests.get(url, headers=HTTP_HEADERS, timeout=20)
    print(f"[FETCH] {company['ticker']} {r.status_code} {url}")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []

    for sel in selectors:
        found = soup.select(sel)
        if found:
            for a in found:
                title = (a.get_text(strip=True) or "").strip()
                href = (a.get("href") or "").strip()
                if not title or not href:
                    continue
                if href.startswith("#") or href.lower().startswith("javascript"):
                    continue
                if not href.startswith("http"):
                    href = base.rstrip("/") + (href if href.startswith("/") else "/" + href)
                candidates.append((title, href))
            if candidates:
                print(f"[SEL] {company['ticker']} matched selector: {sel} ({len(candidates)} links)")
                break

    # fallback: קישורים שמכילים 'press' או 'news'
    if not candidates:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            title = a.get_text(strip=True)
            if title and re.search(r"(press|news)", href, re.I):
                if not href.startswith("http"):
                    href = base.rstrip("/") + (href if href.startswith("/") else "/" + href)
                candidates.append((title, href))

    if not candidates:
        # דיאגנוסטיקה: הדפס 600 תווים ראשונים כדי לראות מה נטען
        snippet = soup.get_text(" ", strip=True)[:600]
        raise RuntimeError(f"{company['ticker']}: לא נמצאו פריטים. בדוק את ה-URL/selector. תוכן לדוגמה:\n{snippet}")

    return candidates[0]

# ===== Main =====
def main():
    state = load_state()
    print("[START] ניטור מרובה מופעל. חברות:", ", ".join([c["ticker"] for c in COMPANIES]))

    try:
        while True:
            for comp in COMPANIES:
                ticker = comp["ticker"]
                name   = comp["name"]
                try:
                    title, href = fetch_latest_item(comp)
                    last = state.get(ticker, {"last_title": "", "last_href": ""})

                    if title != last.get("last_title"):
                        print(f"[NEW] {ticker} | {title}")
                        msg = (
                            f"🚨 הודעה חדשה – {name} ({ticker})\n"
                            f"{title}\n"
                            f"{href}"
                        )
                        send_telegram(msg)
                        state[ticker] = {"last_title": title, "last_href": href}
                        save_state(state)
                    else:
                        print(f"[OK] {ticker}: אין שינוי ({title})")

                except requests.HTTPError as e:
                    print(f"[HTTP] {ticker}: {e}")
                except Exception:
                    print(f"[ERR] {ticker}:\n", traceback.format_exc())

            time.sleep(CHECK_EVERY_SECONDS)

    except KeyboardInterrupt:
        print("\n[EXIT] הופסק ע\"י המשתמש. ביי 👋")

if __name__ == "__main__":
    main()
