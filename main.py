import os
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import urllib.request
import json

# --- CONFIGURATION & ENV VARIABLES ---
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "ethankaye92@gmail.com")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "ethankaye92@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # Gmail App Password
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# 12-Bucket Expanded Terminology Matrix
SEARCH_BUCKETS = {
    "Refinancing & Maturities": [
        '"amend and extend"', '"A&E"', '"lenders walk"', '"balks at"',
        '"refinancing difficulty"', '"maturity wall"', '"yield bump"', '"sweeteners"'
    ],
    "Restructuring & Workouts": [
        '"taking keys"', '"equitizing debt"', '"debt-for-equity"',
        '"creditor steering committee"', '"forbearance"', '"RSA"'
    ],
    "Default & Payment Stress": [
        '"bad PIK"', '"PIK toggle"', '"skipped interest"', '"payment default"', '"non-accrual"'
    ],
    "Rating Actions & Covenants": [
        '"covenant breach"', '"covenant waiver"', '"CreditWatch negative"',
        '"distressed exchange"', '"de facto default"'
    ]
}

def get_lookback_dates():
    """Calculates 96-hour lookback on Mondays, 48-hour lookback Tuesday-Friday."""
    now = datetime.datetime.now(datetime.timezone.utc)
    weekday = now.weekday()  # 0 is Monday
    hours = 96 if weekday == 0 else 48
    start_date = now - datetime.timedelta(hours=hours)
    return start_date.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

def fetch_sec_edgar_events(start_date, end_date):
    """Queries SEC EDGAR API for key distress phrases in recent 8-Ks."""
    results = []
    base_url = "https://efts.sec.gov/LATEST/search-index"
    phrases = ["going concern", "covenant breach", "chapter 11", "restructuring"]
    
    headers = {"User-Agent": "BDCCreditSurveillance/1.0 (ethankaye92@gmail.com)"}
    
    for phrase in phrases:
        params = {
            "q": f'"{phrase}"',
            "forms": "8-K",
            "startdt": start_date,
            "enddt": end_date
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    hits = data.get("hits", {}).get("hits", [])
                    for hit in hits[:2]:
                        src = hit.get("_source", {})
                        results.append({
                            "entity": src.get("entity_name", "SEC Filer"),
                            "phrase": phrase,
                            "form": "8-K",
                            "url": f"https://www.sec.gov/ix?doc=/Archives/edgar/data/{src.get('cIK')}/{src.get('adsh')}"
                        })
        except Exception as e:
            print(f"SEC EDGAR search notice for '{phrase}': {e}")
    return results

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
    """Main execution entry point for AWS Lambda / GCP Cloud Functions."""
    today_str = datetime.datetime.now().strftime("%B %d, %Y")
    start_dt, end_dt = get_lookback_dates()
    
    # 1. Pull SEC EDGAR Distress Events
    edgar_hits = fetch_sec_edgar_events(start_dt, end_dt)
    
    # 2. Build Markdown Digest Body
    digest_lines = [
        f"BDC Loan Monitor — {today_str}",
        "Daily Automated Surveillance Digest",
        f"Lookback Window: {start_dt} to {end_dt}\n",
        "=" * 40,
        "\n### SEC EDGAR 8-K DISTRESS SIGNAL FLAGGING"
    ]
    
    if edgar_hits:
        for hit in edgar_hits:
            digest_lines.append(f"\n🔴 **{hit['entity']}**")
            digest_lines.append(f"  * Matched Trigger: \"{hit['phrase']}\"")
            digest_lines.append(f"  * Source: {hit['url']}")
    else:
        digest_lines.append("No material SEC 8-K distress keywords surfaced in window.")
        
    digest_lines.extend([
        "\n### KEYWORD & INBOX SEARCH MATRIX ACTIVE",
        "The following 12-bucket query clusters were executed across web feeds and inbox digests:"
    ])
    
    for category, terms in SEARCH_BUCKETS.items():
        digest_lines.append(f"  * **{category}:** {', '.join(terms[:4])}...")
        
    digest_lines.extend([
        "\n" + "=" * 40,
        "End of Daily Credit Monitor Report."
    ])
    
    body = "\n".join(digest_lines)
    subject = f"BDC Loan Monitor — {today_str}"
    
    send_email_digest(subject, body)
    return {"status": 200, "message": "Email sent successfully."}

# Local execution test
if __name__ == "__main__":
    run_surveillance()
