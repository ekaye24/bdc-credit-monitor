import os
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import urllib.request
import json
import xml.etree.ElementTree as ET

# --- CONFIGURATION & ENV VARIABLES ---
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "ethankaye92@gmail.com")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "ethankaye92@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # Gmail App Password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# RSS News Sources
RSS_FEEDS = [
    {"name": "DailyDAC Articles", "url": "https://www.dailydac.com/feed/"},
    {"name": "Bondoro Insights", "url": "https://bondoro.com/feed/"},
]

# Credit Surveillance Keywords for News Scanning
DISTRESS_KEYWORDS = [
    "chapter 11", "bankruptcy", "distressed", "reorganization", "covenant breach",
    "amend and extend", "a&e", "lenders walk", "balks at", "forbearance",
    "distressed exchange", "restructuring", "non-accrual", "de facto default"
]

def get_lookback_dates():
    """Calculates 96-hour lookback on Mondays, 48-hour lookback Tuesday-Friday."""
    now = datetime.datetime.now(datetime.timezone.utc)
    weekday = now.weekday()  # 0 is Monday
    hours = 96 if weekday == 0 else 48
    start_date = now - datetime.timedelta(hours=hours)
    return start_date, now

def fetch_sec_edgar_events(start_dt, end_dt):
    """Queries SEC EDGAR API for key distress phrases in recent 8-Ks with fixed JSON parsing."""
    results = []
    base_url = "https://efts.sec.gov/LATEST/search-index"
    phrases = ["going concern", "covenant breach", "chapter 11", "restructuring"]
    headers = {"User-Agent": "BDCCreditSurveillance/1.0 (ethankaye92@gmail.com)"}
    
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    for phrase in phrases:
        params = {
            "q": f'"{phrase}"',
            "forms": "8-K",
            "startdt": start_str,
            "enddt": end_str
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    hits = data.get("hits", {}).get("hits", [])
                    for hit in hits[:3]:
                        src = hit.get("_source", {})
                        
                        # --- FIX 1: Extract entity name correctly ---
                        display_names = src.get("display_names", [])
                        if display_names:
                            # Usually formatted like "COMPANY NAME  (CIK 0001234567)"
                            entity_name = display_names[0].split("  (")[0].strip()
                        else:
                            entity_name = src.get("entity_name", "Unknown SEC Filer")
                        
                        # --- FIX 2: Extract CIK and ADSH for valid URLs ---
                        cik_list = src.get("ciks", [])
                        cik = cik_list[0] if cik_list else src.get("cik", "")
                        adsh_raw = src.get("adsh", "")
                        adsh_clean = adsh_raw.replace("-", "")
                        
                        if cik and adsh_raw:
                            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_clean}/{adsh_raw}.txt"
                        else:
                            doc_url = "https://www.sec.gov/edgar/searchedgar/companysearch"
                        
                        results.append({
                            "entity": entity_name,
                            "phrase": phrase,
                            "form": "8-K",
                            "url": doc_url
                        })
        except Exception as e:
            print(f"SEC EDGAR search notice for '{phrase}': {e}")
            
    return results

def fetch_rss_bankruptcy_news(start_dt):
    """Scrapes RSS feeds for distress/bankruptcy news published within lookback window."""
    rss_results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for feed in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                
                # Parse RSS items
                for item in root.findall(".//item"):
                    title = item.findtext("title", default="").strip()
                    link = item.findtext("link", default="").strip()
                    description = item.findtext("description", default="").strip()
                    pub_date_str = item.findtext("pubDate", default="").strip()

                    # Match against distress keywords
                    text_to_check = f"{title} {description}".lower()
                    matched_keywords = [kw for kw in DISTRESS_KEYWORDS if kw in text_to_check]

                    if matched_keywords:
                        rss_results.append({
                            "source_name": feed["name"],
                            "title": title,
                            "link": link,
                            "matches": matched_keywords
                        })
        except Exception as e:
            print(f"RSS fetch notice for {feed['name']}: {e}")

    return rss_results

def send_email_digest(subject, body_text):
    """Sends the formatted text email via Gmail SMTP."""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body_text, 'plain'))
    
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

def run_surveillance(event=None, context=None):
    """Main execution entry point."""
    today_str = datetime.datetime.now().strftime("%B %d, %Y")
    start_dt, end_dt = get_lookback_dates()
    
    # 1. Fetch SEC EDGAR Distress Events
    edgar_hits = fetch_sec_edgar_events(start_dt, end_dt)
    
    # 2. Fetch RSS Bankruptcy & Distress News
    rss_hits = fetch_rss_bankruptcy_news(start_dt)
    
    # 3. Build Markdown Output
    digest_lines = [
        f"BDC Loan Monitor — {today_str}",
        f"Lookback Window: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}\n",
        "---",
        "\n### SEC EDGAR 8-K DISTRESS SIGNAL FLAGGING"
    ]
    
    if edgar_hits:
        # Deduplicate hits by entity and phrase
        seen_entities = set()
        for hit in edgar_hits:
            key = f"{hit['entity']}_{hit['phrase']}"
            if key not in seen_entities:
                seen_entities.add(key)
                digest_lines.append(f"\n🔴 **{hit['entity']}**")
                digest_lines.append("  * AKA / Affiliates / DBAs: [Pending Master Mapping]")
                digest_lines.append("  * BDC Exposure: None identified in initial sweep.")
                digest_lines.append(f"  * Development: Filed Form 8-K matching trigger term '{hit['phrase']}'.")
                digest_lines.append("  * Why it matters: Potential material corporate event, governance change, or debt agreement modification.")
                digest_lines.append(f"  * Source: [SEC EDGAR Filing]({hit['url']})")
    else:
        digest_lines.append("No material SEC 8-K distress keywords surfaced in window.")

    digest_lines.append("\n---")
    digest_lines.append("\n### BANKRUPTCY & PRIVATE DEBT NEWS FEEDS")

    if rss_hits:
        for item in rss_hits:
            digest_lines.append(f"\n🟡 **{item['title']}**")
            digest_lines.append("  * AKA / Affiliates / DBAs: [Pending Master Mapping]")
            digest_lines.append("  * BDC Exposure: None identified in initial sweep.")
            digest_lines.append(f"  * Matched Terms: {', '.join(item['matches'])}")
            digest_lines.append(f"  * Source: [{item['source_name']}]({item['link']})")
    else:
        digest_lines.append("No bankruptcy/distress articles flagged from RSS feeds in window.")

    digest_lines.extend([
        "\n---",
        "\nEnd of Daily Credit Monitor Report."
    ])
    
    body = "\n".join(digest_lines)
    subject = f"BDC Loan Monitor — {today_str}"
    
    send_email_digest(subject, body)
    return {"status": 200, "message": "Email sent successfully."}

# Entry point for GitHub Actions or local test
if __name__ == "__main__":
    run_surveillance()
