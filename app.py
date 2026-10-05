import os
import re
import sys
import time
import json
import urllib.parse
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG = {
    'base_domain': 'https://themoviebox.xyz',
    'api_domain': 'https://h5-api.aoneroom.com',
    'jwt_token': '',
    
    'output_file': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'series_output.json'),
    'start_page': 1,
    'per_page': 24,       
    'delay_ms': 800,      
    
    'cooldown_every_pages': 10,
    'cooldown_seconds': 8, 
    'delay_between_episodes_ms': 120, # From PHP Logic
    
    'filter': {
        'tabId': 2, # 2 means strictly TV Shows
        'classify': 'Bengali dub',
        'country': 'All',
        'genre': 'All',
        'sort': 'ForYou', 
        'year': 'All'
    },
    'category_name': 'Bengali Collection' # From PHP Logic
}

CONFIG['api_url'] = f"{CONFIG['api_domain']}/wefeed-h5api-bff/subject/filter"
CONFIG['detail_api'] = f"{CONFIG['api_domain']}/wefeed-h5api-bff/subject/detail"
CONFIG['play_api'] = f"{CONFIG['api_domain']}/wefeed-h5api-bff/subject/play"

session = requests.Session()

def get_stealth_headers(token="", base_domain="", referer="", is_cross_site=False):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="127", "Chromium";v="127", "Not.A/Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        # CRITICAL FIX: Must be cross-site when calling api_domain from base_domain
        'sec-fetch-site': 'cross-site' if is_cross_site else 'same-origin'
    }
    
    if base_domain:
        headers['Origin'] = base_domain
    if referer:
        headers['Referer'] = referer
    elif base_domain:
        headers['Referer'] = f"{base_domain}/"

    if token:
        headers['Authorization'] = f"Bearer {token}"
        
    return headers

def fetch_initial_token_and_cookie():
    url = f"{CONFIG['base_domain']}/"
    headers = get_stealth_headers(base_domain=CONFIG['base_domain'], is_cross_site=False)
    
    try:
        res = session.get(url, headers=headers, timeout=15, verify=False)
        token = ""
        
        # 1. Next.js data extraction
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text, re.DOTALL)
        if match:
            t_match = re.search(r'"token"\s*:\s*"([a-zA-Z0-9\.\-_]+)"', match.group(1), re.IGNORECASE)
            if t_match:
                token = t_match.group(1)
                
        # 2. Generic Token Fallback from PHP script
        if not token:
            t_match = re.search(r'"(?:accessToken|jwtToken|token)"\s*:\s*"([a-zA-Z0-9\.\-_]{20,})"', res.text, re.IGNORECASE)
            if t_match:
                token = t_match.group(1)
                
        # 3. Direct Cookie extraction
        if not token:
            for cookie in session.cookies:
                if cookie.name in ['mb_auth_token', 'mb_token']:
                    token = cookie.value
                    break
                    
        return token
    except Exception as e:
        print(f"Error fetching initial token: {e}")
        return ""

def request_api(url, payload, token, base_domain):
    headers = get_stealth_headers(token, base_domain, is_cross_site=True)
    headers['Content-Type'] = 'application/json'
    
    try:
        # CRITICAL FIX: Manually forcing cookies because Python isolates cookies across different domains natively
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        response = session.post(url, json=payload, headers=headers, cookies=cookies_dict, timeout=20, verify=False)
        
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def get_safe_poster_url(data, fallback):
    possible_keys = ['cover', 'verticalCover', 'horizontalCover', 'poster', 'thumb', 'image', 'pic']
    for k in possible_keys:
        val = data.get(k)
        if val:
            if isinstance(val, str) and val.startswith('http'): return val
            if isinstance(val, dict) and val.get('url'): return val['url']
            
    for k in possible_keys:
        val = fallback.get(k)
        if val:
            if isinstance(val, str) and val.startswith('http'): return val
            if isinstance(val, dict) and val.get('url'): return val['url']
    return ""

def fetch_subject_detail(movie_id, detail_path, token):
    encoded_path = urllib.parse.quote(detail_path)
    detail_url = f"{CONFIG['detail_api']}?subjectId={movie_id}&detailPath={encoded_path}"
    detail_page_url = f"{CONFIG['base_domain']}/detail/{detail_path}?id={movie_id}&scene=&page_from=rank_detail&type=/movie/detail"
    
    headers = get_stealth_headers(token, CONFIG['base_domain'], detail_page_url, is_cross_site=True)
    
    try:
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        res = session.get(detail_url, headers=headers, cookies=cookies_dict, timeout=15, verify=False)
        if res.status_code == 200:
            data = res.json()
            if data.get('data') and isinstance(data['data'], dict):
                return data['data']
    except Exception:
        pass
    return {}

def fetch_stream_url_only(movie_id, se, ep, detail_path, token):
    play_api_url = f"{CONFIG['play_api']}?subjectId={movie_id}&se={se}&ep={ep}&detailPath={detail_path}&streamSignType=1&supportCodecs%5Bh264%5D=1"
    detail_page_url = f"{CONFIG['base_domain']}/movies/{detail_path}?id={movie_id}&type=/movie/detail&detailSe={se}&detailEp={ep}&lang=en"

    active_token = token
    for cookie in session.cookies:
        if cookie.name in ['mb_auth_token', 'mb_token']:
            active_token = cookie.value
            
    api_headers = get_stealth_headers(active_token, CONFIG['base_domain'], detail_page_url, is_cross_site=True)

    try:
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        res = session.get(play_api_url, headers=api_headers, cookies=cookies_dict, timeout=15, verify=False)
        if res.status_code != 200: 
            return None
        
        data = res.json()
        if not data.get('data'): 
            return None
            
        final_url = ""
        quality = "HD"
        
        if data['data'].get('streams'):
            mp4_list = {int(st.get('resolutions', 0)): st for st in data['data']['streams'] if st.get('url')}
            if mp4_list:
                best_res = max(mp4_list.keys())
                quality = f"{best_res}p"
                final_url = mp4_list[best_res]['url']
                
        elif data['data'].get('dash') and data['data']['dash'][0].get('url'):
            quality = 'DASH'
            final_url = data['data']['dash'][0]['url']
            
        if final_url:
            return {'url': final_url, 'quality': quality}
    except Exception:
        pass
    return None

def fetch_series_seasons_and_episodes(movie, fallback_token):
    movie_id = str(movie.get('subjectId', movie.get('id', '')))
    title = movie.get('title', movie.get('name', 'Unknown'))
    detail_path = movie.get('detailPath', '')

    if not detail_path:
        detail_path = re.sub(r'[^A-Za-z0-9-]+', '-', title).strip('-').lower()
        if not detail_path:
            detail_path = "detail"

    full_detail_data = fetch_subject_detail(movie_id, detail_path, fallback_token)
    if full_detail_data and full_detail_data.get('title'):
        title = full_detail_data['title']

    poster = get_safe_poster_url(full_detail_data, movie)
    if full_detail_data.get('resolvedPosterUrl'):
        poster = full_detail_data['resolvedPosterUrl']

    seasons_array = []
    overall_quality = "HD"
    total_episodes_found = 0
    
    s_num = 1
    # Mirrored 50 Seasons & 5000 Episodes Limit exactly as PHP
    while s_num <= 50:
        episodes_array = []
        e_num = 1
        consecutive_fails = 0
        
        print(f"\n        └─ Season {s_num}: ", end="", flush=True)

        while e_num <= 5000:
            stream_info = None
            attempts = 0

            while attempts < 3 and not stream_info:
                stream_info = fetch_stream_url_only(movie_id, s_num, e_num, detail_path, fallback_token)
                if not stream_info:
                    attempts += 1
                    if attempts < 3: 
                        time.sleep(0.15)
            
            # S0E0 Movie format fallback
            if not stream_info and s_num == 1 and e_num == 1:
                stream_info = fetch_stream_url_only(movie_id, 0, 0, detail_path, fallback_token)
                if stream_info:
                    e_num = 0

            if stream_info and stream_info.get('url'):
                consecutive_fails = 0
                overall_quality = stream_info['quality']
                ep_title = "Full Movie" if e_num == 0 else f"Ep{e_num}"

                headers_obj = {
                    "Referer": f"{CONFIG['base_domain']}/",
                    "Origin": "",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                }

                episodes_array.append({
                    "downStatus": "off",
                    "downUrl": stream_info['url'],
                    "duration": "--:--",
                    "episode_title": ep_title,
                    "headers": headers_obj,
                    "posterUrl": poster,
                    "streamUrl": stream_info['url'],
                    "view": 0
                })
                
                total_episodes_found += 1
                print(f"{ep_title}✓ ", end="", flush=True)

                if e_num == 0: 
                    break 
                e_num += 1
            else:
                consecutive_fails += 1
                print(".", end="", flush=True)
                
                # 25 consecutive fails means season ends
                if consecutive_fails >= 25:
                    break
                e_num += 1
                
            time.sleep(CONFIG['delay_between_episodes_ms'] / 1000.0)

        if episodes_array:
            season_title = "Movie Stream" if (e_num == 0 or (len(episodes_array) == 1 and episodes_array[0]['episode_title'] == 'Full Movie')) else f"Season {s_num}"
            seasons_array.append({
                "season_title": season_title,
                "episodes": episodes_array
            })
            
            if e_num == 0 or season_title == "Movie Stream":
                break
            s_num += 1
        else:
            break

    return {
        'fullDetailData': full_detail_data,
        'seasons': seasons_array,
        'quality': overall_quality,
        'resolvedTitle': title,
        'resolvedPoster': poster,
        'totalEpisodesFound': total_episodes_found
    }

def format_to_desired_json(movie, series_data):
    full_data = series_data.get('fullDetailData', {})
    title = series_data.get('resolvedTitle', movie.get('title', 'Unknown'))
    release_date = str(full_data.get('releaseDate', full_data.get('year', movie.get('releaseDate', ''))))

    year = ""
    yr_matches = re.search(r'\b(19\d{2}|20\d{2})\b', release_date)
    if yr_matches: 
        year = yr_matches.group(1)

    clean_title = title
    clean_title = re.sub(r'^Watch\s+', '', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\s*Streaming\s+Online.*$', '', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\s*on\s+Movie[s]?Box.*$', '', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'\[.*?\]', '', clean_title)
    clean_title = re.sub(r'\((?:19\d{2}|20\d{2})\)', '', clean_title)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    
    final_title = f"{clean_title} ({year})" if year and f"({year})" not in clean_title else clean_title

    poster = series_data.get('resolvedPoster', '')
    if not poster: 
        poster = get_safe_poster_url(full_data, movie)

    raw_storyline = str(full_data.get('description', full_data.get('brief', '')))
    clean_storyline = re.sub(r'free\s+streaming\s+online\s+on\s+Movie[s]?Box', 'MY TV', raw_storyline, flags=re.IGNORECASE)
    clean_storyline = re.sub(r'streaming\s+online\s+on\s+Movie[s]?Box', 'MY TV', clean_storyline, flags=re.IGNORECASE)
    clean_storyline = re.sub(r'Movie[s]?Box', 'MY TV', clean_storyline, flags=re.IGNORECASE)
    clean_storyline = re.sub(r'\s+', ' ', clean_storyline).strip()

    genres = ["Drama"]
    if full_data.get('genre'):
        if isinstance(full_data['genre'], list):
            genres = full_data['genre']
        else:
            genres = [g.strip() for g in full_data['genre'].split(',')]

    return {
        "category": CONFIG['category_name'],
        "director": "N/A",
        "genre": [g for g in genres if g],
        "imdbRating": float(full_data.get('imdbRatingValue', full_data.get('score', 7.8))),
        "imdbVotes": int(full_data.get('imdbRatingCount', 0)),
        "language": str(full_data.get('language', 'Bengali')),
        "posterUrl": str(poster),
        "premium": False,
        "quality": str(series_data.get('quality', 'HD')),
        "releaseDate": str(release_date),
        "resolution": str(series_data.get('quality', 'HD')),
        "seasons": series_data.get('seasons', []),
        "sliderStatus": "off",
        "sliderUrl": "",
        "status": "on",
        "storyline": clean_storyline,
        "title": final_title,
        "triler": ""
    }

def main():
    print("====================================================")
    print("    MovieBox TV Series Live Scraper (Python Edition)")
    print("====================================================")
    
    print("ℹ️  Initializing engine and fetching auth tokens...", flush=True)
    auto_token = fetch_initial_token_and_cookie()
    if auto_token:
        CONFIG['jwt_token'] = auto_token
        print("✅ [SUCCESS] Automatically fetched latest auth token & cookies!", flush=True)
    else:
        print("⚠️ [WARNING] Failed to fetch auto token, continuing with default setup...", flush=True)

    all_series = []
    series_map = {}
    seen_in_this_run = set()

    if os.path.exists(CONFIG['output_file']):
        try:
            with open(CONFIG['output_file'], 'r', encoding='utf-8') as f:
                existing = json.load(f)
                if isinstance(existing, list):
                    all_series = existing
                    for idx, s in enumerate(all_series):
                        if s.get('title'):
                            series_map[s['title']] = idx
                    print(f"[INFO] Previously saved: {len(all_series)} series found.", flush=True)
        except Exception as e:
            print(f"[WARNING] Could not read existing JSON: {e}")

    page = CONFIG['start_page']
    pages_scraped = 0

    while True:
        print(f"\n[PAGE {page}] Fetching TV series list...", flush=True)

        payload = {
            'tabId': CONFIG['filter']['tabId'],
            'classify': CONFIG['filter']['classify'],
            'country': CONFIG['filter']['country'],
            'genre': CONFIG['filter']['genre'],
            'sort': CONFIG['filter']['sort'],
            'year': CONFIG['filter']['year'],
            'page': page,
            'perPage': CONFIG['per_page']
        }

        response = request_api(CONFIG['api_url'], payload, CONFIG['jwt_token'], CONFIG['base_domain'])

        if not response:
            print("[STOP] API connection failed. Terminating.", flush=True)
            break

        items = response.get('data', {}).get('list', response.get('data', {}).get('items', []))
        count = len(items)
        print(f" -> Found: {count} items.", flush=True)

        if count == 0:
            print("🎉 [COMPLETE] No more items left!", flush=True)
            break

        processed_this_page = 0

        for movie in items:
            mid = str(movie.get('subjectId', movie.get('id', '')))
            title = movie.get('title', movie.get('name', 'Unknown'))

            if not mid or mid in seen_in_this_run:
                continue
                
            seen_in_this_run.add(mid)
            processed_this_page += 1

            print(f"   ▶ {title} [Fetching]... ", end="", flush=True)

            series_data = fetch_series_seasons_and_episodes(movie, CONFIG['jwt_token'])

            if not series_data or not series_data.get('seasons'):
                print("\n      [No stream link - Skipped]", flush=True)
                continue

            formatted = format_to_desired_json(movie, series_data)
            
            if formatted['title'] in series_map:
                idx = series_map[formatted['title']]
                all_series[idx] = formatted
                print(f"\n      [Success - Updated {series_data['totalEpisodesFound']} Eps]", flush=True)
            else:
                all_series.append(formatted)
                series_map[formatted['title']] = len(all_series) - 1
                print(f"\n      [Success - Added New {series_data['totalEpisodesFound']} Eps]", flush=True)
                
        if processed_this_page == 0:
            print("🛑 [LOOP DETECTED] Server repeating data. Terminated.", flush=True)
            break

        with open(CONFIG['output_file'], 'w', encoding='utf-8') as f:
            json.dump(all_series, f, indent=4, ensure_ascii=False)

        pages_scraped += 1
        if CONFIG['cooldown_every_pages'] > 0 and (pages_scraped % CONFIG['cooldown_every_pages'] == 0):
            print(f"\n☕ [Cooldown] Waiting {CONFIG['cooldown_seconds']}s...", flush=True)
            time.sleep(CONFIG['cooldown_seconds'])
        else:
            time.sleep(CONFIG['delay_ms'] / 1000.0)
            
        page += 1

    print("\n====================================================")
    print(f"[FINISHED] Total Series Saved: {len(all_series)}")
    print("====================================================", flush=True)

if __name__ == "__main__":
    main()
