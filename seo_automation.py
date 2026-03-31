import base64
import os
import json
import re
import requests
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# -- Config --
SITE_URL = os.environ.get('SITE_URL', 'sc-domain:transcript-iq.com')
WEBFLOW_API_TOKEN = os.environ.get('WEBFLOW_API_TOKEN', '')
WEBFLOW_COLLECTION_ID = os.environ.get('WEBFLOW_COLLECTION_ID', '')
GOOGLE_SA_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

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

# -- Generate blog with Groq --
def generate_blog_post(keyword):
    prompt = f"""Write a comprehensive, SEO-optimized blog post for the keyword: "{keyword}"
The blog post is for transcript-iq.com, a market research platform that provides AI-powered transcript analysis.
Requirements:
- Title: compelling, includes the keyword
- Length: 600-800 words
- Structure: intro, 3-4 sections with H2 headings, conclusion
- Natural keyword usage throughout
- Professional tone, helpful and informative
- End with a call to action mentioning Transcript IQ
Respond ONLY with valid JSON, no markdown, no code blocks. Use this exact structure:
{{"title": "...", "slug": "...", "meta_description": "...", "body": "..."}}
Rules:
- slug: lowercase with hyphens only, max 60 chars
- meta_description: 150-160 characters exactly
- body: valid HTML using only <h2> and <p> tags"""
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'llama-3.3-70b-versatile',
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 2048,
        'temperature': 0.7
    }
    resp = requests.post('https://api.groq.com/openai/v1/chat/completions',
                         headers=headers, json=payload, timeout=60)
    if resp.status_code == 200:
        text = resp.json()['choices'][0]['message']['content'].strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError(f'Could not parse JSON from Groq response: {text[:300]}')
    else:
        raise Exception(f'Groq API error {resp.status_code}: {resp.text[:300]}')

# -- List Webflow collections to find correct ID --
def list_webflow_collections():
    headers = {
        'Authorization': f'Bearer {WEBFLOW_API_TOKEN}',
        'accept': 'application/json'
    }
    # First get sites
    sites_resp = requests.get('https://api.webflow.com/v2/sites', headers=headers)
    print(f'Sites response: {sites_resp.status_code} {sites_resp.text[:500]}')
    if sites_resp.status_code == 200:
        sites = sites_resp.json().get('sites', [])
        for site in sites:
            site_id = site.get('id')
            print(f'Site: {site.get("displayName")} ID: {site_id}')
            colls_resp = requests.get(f'https://api.webflow.com/v2/sites/{site_id}/collections', headers=headers)
            print(f'Collections: {colls_resp.status_code} {colls_resp.text[:500]}')

# -- Publish to Webflow CMS v2 --
def publish_to_webflow(post_data):
    headers = {
        'Authorization': f'Bearer {WEBFLOW_API_TOKEN}',
        'Content-Type': 'application/json',
        'accept': 'application/json'
    }
    # Use Webflow API v2 format
    payload = {
        'fieldData': {
            'name': post_data['title'],
            'slug': post_data['slug'],
            'post-body': post_data['body'],
            'post-summary': post_data['meta_description']
        },
        'isDraft': False
    }
    url = f'https://api.webflow.com/v2/collections/{WEBFLOW_COLLECTION_ID}/items'
    print(f'Posting to Webflow URL: {url}')
    resp = requests.post(url, headers=headers, json=payload)
    print(f'Webflow create response: {resp.status_code} {resp.text[:500]}')
    if resp.status_code in (200, 201, 202):
        item_id = resp.json().get('id') or resp.json().get('_id')
        print(f'Published to Webflow: {post_data["title"]} (ID: {item_id})')
        # Publish live
        pub_url = f'https://api.webflow.com/v2/collections/{WEBFLOW_COLLECTION_ID}/items/{item_id}/live'
        pub_resp = requests.put(pub_url, headers=headers, json=payload)
        print(f'Publish live response: {pub_resp.status_code} {pub_resp.text[:200]}')
        if pub_resp.status_code in (200, 202):
            print('Blog post is now LIVE on transcript-iq.com!')
        else:
            print(f'Publish warning: {pub_resp.status_code} {pub_resp.text[:200]}')
        return item_id
    else:
        raise Exception(f'Webflow error {resp.status_code}: {resp.text[:500]}')

# -- Main --
def main():
    print('Starting SEO automation with Groq AI...')
    if not GROQ_API_KEY:
        raise ValueError('GROQ_API_KEY not set')
    if not WEBFLOW_API_TOKEN:
        raise ValueError('WEBFLOW_API_TOKEN not set')
    if not WEBFLOW_COLLECTION_ID:
        print('WEBFLOW_COLLECTION_ID not set - listing available collections...')
        list_webflow_collections()
        raise ValueError('WEBFLOW_COLLECTION_ID not set')

    # List collections for debugging
    print('Listing Webflow collections for reference...')
    list_webflow_collections()

    service = get_gsc_service()
    print('Connected to Google Search Console')
    opportunities = fetch_seo_opportunities(service)
    if not opportunities:
        print('No SEO opportunities found today. Exiting.')
        return
    print(f'Found {len(opportunities)} opportunities:')
    for opp in opportunities:
        print(f'  - {opp["query"]} (pos {opp["position"]}, {opp["impressions"]} impressions)')
    top = opportunities[0]
    keyword = top['query']
    print(f'Generating blog post for: {keyword}')
    post_data = generate_blog_post(keyword)
    print(f'Generated title: {post_data["title"]}')
    item_id = publish_to_webflow(post_data)
    print(f'SUCCESS! Blog post live on transcript-iq.com. Item ID: {item_id}')

if __name__ == '__main__':
    main()
