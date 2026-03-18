import base64
import os
import json
import re
import requests
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import anthropic

# -- Config --
SITE_URL = os.environ.get('SITE_URL', 'https://www.transcript-iq.com')
WEBFLOW_API_TOKEN = os.environ.get('WEBFLOW_API_TOKEN', '')
WEBFLOW_COLLECTION_ID = os.environ.get('WEBFLOW_COLLECTION_ID', '')
GOOGLE_SA_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

def get_gsc_service():
    if not GOOGLE_SA_JSON:
        print('[WARN] No Google SA JSON found - skipping GSC step')
        return None
    raw = base64.b64decode(GOOGLE_SA_JSON).decode('utf-8')
    creds_info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    return build('searchconsole', 'v1', credentials=creds)

def fetch_search_analytics(service, days=28):
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

def find_opportunities(rows, ctr_threshold=0.03, min_impressions=30):
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

def generate_blog_post(query, position, impressions):
    if not ANTHROPIC_API_KEY:
        print('[WARN] No Anthropic API key - skipping blog generation')
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are an expert content writer for Transcript IQ, a market research platform that provides primary intelligence through expert call transcripts and research reports.

Write a comprehensive, SEO-optimized blog post targeting the keyword: "{query}"

Context:
- This keyword has {impressions} impressions but low click-through rate (position {position} in search results)
- Transcript IQ helps businesses make bold decisions using primary market research
- The tone should be professional, authoritative, and data-driven

Provide the response in this EXACT JSON format:
{{
  "title": "SEO-optimized blog post title (include the keyword naturally)",
  "summary": "2-3 sentence summary for the blog grid (compelling, keyword-rich, under 160 chars)",
  "body": "Full blog post in HTML format with h2/h3 headings, paragraphs, and bullet points. Minimum 600 words. Include the keyword naturally throughout."
}}

Return ONLY the JSON, no other text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    # Remove markdown code blocks if present
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

def make_slug(title):
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug[:80]

def publish_to_webflow(blog_data, query):
    if not WEBFLOW_API_TOKEN or not WEBFLOW_COLLECTION_ID:
        print('[WARN] Webflow credentials missing - skipping publish')
        return False
    slug = make_slug(blog_data['title'])
    payload = {
        "fieldData": {
            "name": blog_data['title'],
            "slug": slug,
            "post-body": blog_data['body'],
            "post-summary": blog_data['summary']
        },
        "isDraft": False
    }
    headers = {
        'Authorization': f'Bearer {WEBFLOW_API_TOKEN}',
        'Content-Type': 'application/json',
        'accept': 'application/json'
    }
    url = f'https://api.webflow.com/v2/collections/{WEBFLOW_COLLECTION_ID}/items/live'
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code in [200, 201, 202]:
        print(f'[WEBFLOW] Published: {blog_data["title"]}')
        return True
    else:
        print(f'[ERROR] Webflow publish failed: {resp.status_code} {resp.text}')
        return False

def main():
    print(f'[START] SEO Automation run at {datetime.utcnow().isoformat()}')
    print(f'[INFO] Target site: {SITE_URL}')

    service = get_gsc_service()
    opportunities = []

    if service:
        print('[GSC] Fetching search analytics...')
        rows = fetch_search_analytics(service)
        print(f'[GSC] Retrieved {len(rows)} keyword rows')
        opportunities = find_opportunities(rows)
        print(f'[GSC] Found {len(opportunities)} low-CTR opportunities')
    else:
        print('[SKIP] GSC step skipped - no credentials')

    # Write and publish blog posts for top 3 opportunities
    published_count = 0
    for opp in opportunities[:3]:
        query = opp['query']
        print(f'[BLOG] Generating blog for keyword: "{query}"')
        blog_data = generate_blog_post(query, opp['position'], opp['impressions'])
        if blog_data:
            success = publish_to_webflow(blog_data, query)
            if success:
                published_count += 1
                opp['published_title'] = blog_data['title']
                opp['published_slug'] = make_slug(blog_data['title'])

    # Save report
    report = {
        'generated_at': datetime.utcnow().isoformat(),
        'site': SITE_URL,
        'total_opportunities': len(opportunities),
        'blogs_published': published_count,
        'opportunities': opportunities[:50]
    }
    with open('seo_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f'[OK] Report saved: {len(opportunities)} opportunities, {published_count} blogs published')
    print('[DONE] SEO Automation run complete')

if __name__ == '__main__':
    main()
