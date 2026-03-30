import time
import requests
import json
import time
import re
import traceback
from pathlib import Path
from bs4 import BeautifulSoup

# --- פרטי טלגרם שלך ---
BOT_TOKEN = "7657021379:AAEGJYIWlUFc6NvcKsxjDjbZqI4MdITgH90"
CHAT_ID = "507193413"

CHECK_EVERY_SECONDS = 20               # תדירות בדיקה (שנה ל-60/120/300 לפי הצורך)

# דף ההודעות הרשמי של aTyr:
NEWS_URL = "https://investors.atyrpharma.com/news-releases"

# קובץ מצב מקומי כדי לא לשלוח אותה הודעה פעמיים
STATE_FILE = Path("atyr_state.json")

# כותרות HTTP כדי להיראות "דפדפן רגיל"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

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
    """טוען כותרת/קישור אחרונים שנשלחו, אם קיימים."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_title": "", "last_href": ""}

def save_state(state: dict) -> None:
    """שומר מצב לקובץ."""
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def absolutize(href: str) -> str:
    """הופך href יחסי למוחלט."""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return "https://investors.atyrpharma.com" + href

def extract_candidates(soup: BeautifulSoup):
    """
    מחלץ רשימת מועמדים (כותרת, קישור) מהדף.
    משתמש בכמה סלקטורים כי אתרי IR נוטים לשנות HTML.
    """
    candidates = []

    # 1) הסלקטורים השכיחים באתרי IR של Q4/Intrado/Drupal
    for a in soup.select("div.view-news-releases a, ul.news-releases a, li.views-row a"):
        title = a.get_text(strip=True)
        href = a.get("href") or ""
        if title and href:
            candidates.append((title, absolutize(href)))

    # 2) אם אין — ננסה לינקים שמכילים "news" / "press" בכתובת
    if not candidates:
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href = a["href"]
            if title and href and re.search(r"(news|press)", href, re.I):
                candidates.append((title, absolutize(href)))

    # 3) Fallback קיצוני — כל לינק עם טקסט
    if not candidates:
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href = a["href"]
            if title and href:
                candidates.append((title, absolutize(href)))

    return candidates

def fetch_latest():
    """
    מוריד את דף החדשות ומחזיר את הפריט הראשון (העדכני ביותר):
    (title, href). יזרוק חריגה אם לא נמצא כלום.
    """
    r = requests.get(NEWS_URL, headers=HTTP_HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    candidates = extract_candidates(soup)
    if not candidates:
        raise RuntimeError("לא נמצאו פריטים בדף. ייתכן שה-HTML השתנה – צריך לעדכן סלקטור.")

    # נבחר הראשון ברשימה (בדרך כלל הכי חדש)
    return candidates[0]

# ===== Main Loop =====
def main():
    state = load_state()
    print("[START] ניטור ATYR מופעל.")
    if state["last_title"]:
        print("[STATE] כותרת אחרונה:", state["last_title"])
    else:
        print("[STATE] אין כותרת שמורה (הרצה ראשונה).")

    try:
        while True:
            try:
                title, href = fetch_latest()

                if title != state.get("last_title"):
                    print(f"[NEW] נמצא פרסום חדש: {title}")
                    msg = f"🚨 הודעה חדשה באתר ATYR!\n{title}\n{href}"
                    send_telegram(msg)
                    state["last_title"] = title
                    state["last_href"]  = href
                    save_state(state)
                else:
                    print(f"[OK] אין שינוי. עדיין: {title}")

            except requests.HTTPError as e:
                print("[HTTP] שגיאת HTTP:", e)
            except Exception:
                print("[ERR] חריגה לא צפויה:\n", traceback.format_exc())

            time.sleep(CHECK_EVERY_SECONDS)

    except KeyboardInterrupt:
        print("\n[EXIT] הופסק ע\"י המשתמש. ביי 👋")

if __name__ == "__main__":
    main()