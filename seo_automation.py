import os
import json
import requests
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── Config ──────────────────────────────────────────────────────────────────
SITE_URL = os.environ.get('SITE_URL', 'https://www.transcript-iq.com')
WEBFLOW_API_TOKEN = os.environ.get('WEBFLOW_API_TOKEN', '')
WEBFLOW_COLLECTION_ID = os.environ.get('WEBFLOW_COLLECTION_ID', '')
GOOGLE_SA_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

# ── Google Search Console ────────────────────────────────────────────────────
def get_gsc_service():
    """Authenticate with Google Search Console via service account."""
    if not GOOGLE_SA_JSON:
        print('[WARN] No Google SA JSON found - skipping GSC step')
        return None
    creds_info = json.loads(GOOGLE_SA_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    return build('searchconsole', 'v1', credentials=creds)


def fetch_search_analytics(service, days=28):
    """Pull keyword data: queries with high impressions but low CTR."""
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)
    body = {
        'startDate': str(start_date),
        'endDate': str(end_date),
        'dimensions': ['query', 'page'],
        'rowLimit': 200,
        'orderBy': [{'fieldName': 'impressions', 'sortOrder': 'DESCENDING'}]
    }
    response = service.searchanalytics().query(
        siteUrl=SITE_URL, body=body
    ).execute()
    return response.get('rows', [])


def find_opportunities(rows, ctr_threshold=0.03, min_impressions=50):
    """Find pages with high impressions but low CTR - quick wins."""
    opportunities = []
    for row in rows:
        impressions = row.get('impressions', 0)
        ctr = row.get('ctr', 0)
        clicks = row.get('clicks', 0)
        position = row.get('position', 99)
        query = row['keys'][0]
        page = row['keys'][1] if len(row['keys']) > 1 else ''
        if impressions >= min_impressions and ctr < ctr_threshold:
            opportunities.append({
                'query': query,
                'page': page,
                'impressions': impressions,
                'clicks': clicks,
                'ctr': round(ctr * 100, 2),
                'position': round(position, 1)
            })
    return sorted(opportunities, key=lambda x: x['impressions'], reverse=True)


# ── Webflow CMS ──────────────────────────────────────────────────────────────
def get_webflow_items():
    """Fetch all CMS items from Webflow collection."""
    if not WEBFLOW_API_TOKEN or not WEBFLOW_COLLECTION_ID:
        print('[WARN] Webflow credentials missing - skipping Webflow step')
        return []
    url = f'https://api.webflow.com/v2/collections/{WEBFLOW_COLLECTION_ID}/items'
    headers = {
        'Authorization': f'Bearer {WEBFLOW_API_TOKEN}',
        'accept': 'application/json'
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json().get('items', [])
    print(f'[ERROR] Webflow fetch failed: {resp.status_code} {resp.text}')
    return []


def generate_meta_suggestion(query, position, impressions):
    """Generate an improved meta description suggestion for a given query."""
    return (
        f"Discover expert insights on '{query}' — "
        f"trusted by professionals. Explore transcripts, "
        f"research, and analysis on Transcript IQ."
    )


def save_opportunities_report(opportunities):
    """Save opportunities to a JSON report file."""
    report = {
        'generated_at': datetime.utcnow().isoformat(),
        'site': SITE_URL,
        'total_opportunities': len(opportunities),
        'opportunities': opportunities[:50]  # Top 50
    }
    with open('seo_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f'[OK] Report saved: {len(opportunities)} opportunities found')
    return report


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f'[START] SEO Automation run at {datetime.utcnow().isoformat()}')
    print(f'[INFO] Target site: {SITE_URL}')

    # Step 1: Pull GSC data
    service = get_gsc_service()
    if service:
        print('[GSC] Fetching search analytics...')
        rows = fetch_search_analytics(service)
        print(f'[GSC] Retrieved {len(rows)} keyword rows')
        opportunities = find_opportunities(rows)
        print(f'[GSC] Found {len(opportunities)} low-CTR opportunities')
        for opp in opportunities[:10]:
            opp['meta_suggestion'] = generate_meta_suggestion(
                opp['query'], opp['position'], opp['impressions']
            )
            print(f"  Query: '{opp['query']}' | Pos: {opp['position']} | "
                  f"Impressions: {opp['impressions']} | CTR: {opp['ctr']}%")
        save_opportunities_report(opportunities)
    else:
        print('[SKIP] GSC step skipped - no credentials')

    # Step 2: Audit Webflow CMS items
    items = get_webflow_items()
    if items:
        print(f'[WEBFLOW] Found {len(items)} CMS items')
        for item in items[:5]:
            name = item.get('fieldData', {}).get('name', 'N/A')
            print(f'  - {name}')
    else:
        print('[SKIP] Webflow step skipped - no credentials')

    print('[DONE] SEO Automation run complete')


if __name__ == '__main__':
    main()
