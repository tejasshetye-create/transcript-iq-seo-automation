import base64
import os
import json
import re
import time
import requests
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# -- Config --
SITE_URL = os.environ.get('SITE_URL', 'sc-domain:transcript-iq.com')
WEBFLOW_API_TOKEN = os.environ.get('WEBFLOW_API_TOKEN', '')
WEBFLOW_COLLECTION_ID = os.environ.get('WEBFLOW_COLLECTION_ID', '')
GOOGLE_SA_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# -- Auth Google Search Console --
def get_gsc_service():
    sa_info = json.loads(base64.b64decode(GOOGLE_SA_JSON).decode('utf-8'))
    scopes = ['https://www.googleapis.com/auth/webmasters.readonly']
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)
    return build('searchconsole', 'v1', credentials=creds)

# -- Fetch GSC data --
def fetch_seo_opportunities(service):
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=90)
    body = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['query'],
        'rowLimit': 50,
        'orderBy': [{'fieldName': 'impressions', 'sortOrder': 'DESCENDING'}]
    }
    response = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    rows = response.get('rows', [])
    opportunities = []
    for row in rows:
        query = row['keys'][0]
        clicks = row.get('clicks', 0)
        impressions = row.get('impressions', 0)
        position = row.get('position', 0)
        if impressions > 50 and position > 5:
            opportunities.append({
                'query': query,
                'clicks': clicks,
                'impressions': impressions,
                'position': round(position, 1)
            })
    return opportunities[:5]

# -- Generate blog with Gemini REST API --
def generate_blog_post(keyword):
    models_to_try = [
        'gemini-2.0-flash-lite',
        'gemini-2.0-flash',
    ]
    prompt = f"""Write a comprehensive, SEO-optimized blog post for the keyword: "{keyword}"

The blog post should be for transcript-iq.com, a market research platform that provides AI-powered transcript analysis.

Requirements:
- Title: compelling, includes the keyword
- Length: 600-800 words
- Structure: intro, 3-4 sections with H2 headings, conclusion
- Natural keyword usage throughout
- Professional tone, helpful and informative
- End with a call to action mentioning Transcript IQ

Format the response as JSON with these exact keys:
{{"title": "...", "slug": "...", "meta_description": "...", "body": "..."}}

The slug should be lowercase with hyphens, max 60 chars.
The meta_description should be 150-160 characters.
The body should be HTML with <h2>, <p> tags."""

    payload = {
        'contents': [{'parts': [{'text': prompt}]}]
    }
    last_error = None
    for model in models_to_try:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}'
        print(f'Trying model: {model}')
        for attempt in range(3):
            resp = requests.post(url, json=payload)
            if resp.status_code == 200:
                text = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                raise ValueError(f'Could not parse JSON from Gemini: {text[:200]}')
            elif resp.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f'Rate limited (429). Waiting {wait_time}s...')
                time.sleep(wait_time)
            else:
                last_error = f'{model}: {resp.status_code} {resp.text[:100]}'
                print(f'Failed: {last_error}')
                break
        else:
            last_error = f'{model}: rate limited after 3 retries'
    raise Exception(f'All Gemini models failed. Last error: {last_error}')

# -- Publish to Webflow CMS --
def publish_to_webflow(post_data):
    headers = {
        'Authorization': f'Bearer {WEBFLOW_API_TOKEN}',
        'Content-Type': 'application/json',
        'accept-version': '1.0.0'
    }
    payload = {
        'fields': {
            'name': post_data['title'],
            'slug': post_data['slug'],
            '_archived': False,
            '_draft': False,
            'post-body': post_data['body'],
            'post-summary': post_data['meta_description'],
            'main-image': None
        }
    }
    url = f'https://api.webflow.com/collections/{WEBFLOW_COLLECTION_ID}/items'
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        item_id = resp.json().get('_id')
        print(f'Published: {post_data["title"]} (ID: {item_id})')
        # Publish live
        pub_url = f'https://api.webflow.com/collections/{WEBFLOW_COLLECTION_ID}/items/publish'
        pub_resp = requests.put(pub_url, headers=headers, json={'itemIds': [item_id]})
        if pub_resp.status_code in (200, 202):
            print(f'Live on site!')
        else:
            print(f'Publish live warning: {pub_resp.status_code} {pub_resp.text[:200]}')
        return item_id
    else:
        raise Exception(f'Webflow error {resp.status_code}: {resp.text[:300]}')

# -- Main --
def main():
    print('Starting SEO automation with Gemini AI...')
    if not GEMINI_API_KEY:
        raise ValueError('GEMINI_API_KEY not set')
    if not WEBFLOW_API_TOKEN:
        raise ValueError('WEBFLOW_API_TOKEN not set')
    if not WEBFLOW_COLLECTION_ID:
        raise ValueError('WEBFLOW_COLLECTION_ID not set')

    service = get_gsc_service()
    print('Connected to Google Search Console')

    opportunities = fetch_seo_opportunities(service)
    if not opportunities:
        print('No SEO opportunities found today.')
        return

    print(f'Found {len(opportunities)} opportunities:')
    for opp in opportunities:
        print(f'  - {opp["query"]} (pos {opp["position"]}, {opp["impressions"]} impressions)')

    # Write blog for top opportunity
    top = opportunities[0]
    keyword = top['query']
    print(f'\nGenerating blog post for: {keyword}')

    post_data = generate_blog_post(keyword)
    print(f'Generated: {post_data["title"]}')

    item_id = publish_to_webflow(post_data)
    print(f'Done! Blog post published. Item ID: {item_id}')

if __name__ == '__main__':
    main()
