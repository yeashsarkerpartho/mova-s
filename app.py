import os
import re
import sys
import time
import json
import urllib.parse
import urllib3
import requests

# Suppress InsecureRequestWarning if strictly bypassing SSL verification (like CURLOPT_SSL_VERIFYPEER = false)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG = {
    'base_domain': 'https://themoviebox.xyz',
    'jwt_token': '',
    
    'output_file': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'b_dubseries.json'),
    'start_page': 1,
    'per_page': 24,       
    'delay_ms': 800,      
    
    'cooldown_every_pages': 10,
    'cooldown_seconds': 8, 
    
    'filter': {
        'tabId': 1, # TV Series
        'classify': 'Bengali dub',
        'country': 'All',
        'genre': 'All',
        'sort': 'ForYou', 
        'year': 'All'
    }
}

CONFIG['api_url'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/filter"
CONFIG['detail_api'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/detail"
CONFIG['play_api'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/play"

# Using requests.Session to handle cookies globally (replacing global_cookie_file)
session = requests.Session()

def get_stealth_headers(token="", base_domain=""):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
        'Origin': base_domain,
        'Referer': f"{base_domain}/",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="127", "Chromium";v="127", "Not.A/Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }
    if token:
        headers['Authorization'] = f"Bearer {token}"
    return headers

def fetch_initial_token_and_cookie():
    # Fetch token directly from the main filter page (100% success rate usually)
    url = f"{CONFIG['base_domain']}/web/film?type=/home/movieFilter"
    headers = get_stealth_headers(base_domain=CONFIG['base_domain'])
    
    try:
        response = session.get(url, headers=headers, timeout=15, verify=False)
        token = ""
        
        # 1. Check cookies first (this session automatically stores them)
        token = session.cookies.get('mb_auth_token') or session.cookies.get('mb_token')
        
        # 2. Fallback to NEXT_DATA extraction from HTML
        if not token:
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', response.text, re.DOTALL)
            if match:
                token_match = re.search(r'"token"\s*:\s*"([a-zA-Z0-9\.\-_]+)"', match.group(1), re.IGNORECASE)
                if token_match:
                    token = token_match.group(1)
        return token
    except Exception as e:
        print(f"Error fetching initial token: {e}")
        return ""

def request_api(url, payload, token, base_domain):
    headers = get_stealth_headers(token, base_domain)
    headers['Content-Type'] = 'application/json'
    
    try:
        response = session.post(
            url, 
            json=payload, 
            headers=headers, 
            timeout=20, 
            verify=False
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        pass
    return None

def get_safe_poster_url(data, fallback):
    cover = data.get('cover')
    if cover:
        if isinstance(cover, dict) and cover.get('url'):
            return str(cover['url'])
        if isinstance(cover, str):
            return cover
            
    fallback_cover = fallback.get('cover')
    if fallback_cover:
        if isinstance(fallback_cover, dict) and fallback_cover.get('url'):
            return str(fallback_cover['url'])
        if isinstance(fallback_cover, str):
            return fallback_cover
            
    return ""

def fetch_subject_detail(movie_id, detail_path, token):
    encoded_path = urllib.parse.quote(detail_path)
    detail_url = f"{CONFIG['detail_api']}?subjectId={movie_id}&detailPath={encoded_path}"
    headers = get_stealth_headers(token, CONFIG['base_domain'])
    
    try:
        res = session.get(detail_url, headers=headers, timeout=15, verify=False)
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

    # Use token from session if available, fallback to provided token
    active_token = session.cookies.get('mb_auth_token') or session.cookies.get('mb_token') or token

    api_headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9,bn;q=0.8',
        'origin': CONFIG['base_domain'],
        'referer': detail_page_url,
        'sec-ch-ua': '"Google Chrome";v="127", "Chromium";v="127", "Not.A/Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
    }

    if active_token:
        api_headers['authorization'] = f"Bearer {active_token}"

    try:
        res = session.get(play_api_url, headers=api_headers, timeout=15, verify=False)
        if res.status_code != 200:
            return None
        
        data = res.json()
        if not data.get('data'):
            return None
            
        final_url = ""
        quality = "HD"
        
        if data['data'].get('streams'):
            mp4_list = {}
            for st in data['data']['streams']:
                if st.get('url'):
                    res_val = int(st.get('resolutions', 0))
                    mp4_list[res_val] = st
                    
            if mp4_list:
                # Get highest resolution
                best_res = max(mp4_list.keys())
                best_mp4 = mp4_list[best_res]
                quality = f"{best_res}p"
                final_url = best_mp4['url']
                
        elif data['data'].get('dash') and data['data']['dash'][0].get('url'):
            quality = 'DASH'
            final_url = data['data']['dash'][0]['url']
            
        if not final_url:
            return None
            
        return {
            'url': final_url,
            'quality': quality
        }
    except Exception:
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

    season_list_api = full_detail_data.get('seasonList', full_detail_data.get('seasons', []))
    seasons_to_scrape = []

    if season_list_api and isinstance(season_list_api, list):
        for s in season_list_api:
            s_num = int(s.get('season', s.get('se', 1)))
            e_list = s.get('episodes', s.get('episodeList', []))
            
            if e_list:
                e_count = len(e_list)
            else:
                e_count = int(s.get('episodeCount', s.get('maxEp', s.get('curEpisode', 0))))
                
            if e_count == 0:
                e_count = int(movie.get('curEpisode', movie.get('episodeCount', 1)))
                
            seasons_to_scrape.append({
                'season': s_num,
                'episodeCount': max(1, e_count)
            })

    if not seasons_to_scrape:
        ep_count = int(full_detail_data.get('episodeCount', 
                       full_detail_data.get('curEpisode', 
                       movie.get('curEpisode', 
                       movie.get('episodeCount', 1)))))
        
        s_count = int(full_detail_data.get('seasonCount', movie.get('season', 1)))
        
        for s in range(1, max(1, s_count) + 1):
            seasons_to_scrape.append({
                'season': s,
                'episodeCount': max(1, ep_count)
            })

    seasons_array = []
    overall_quality = "HD"
    poster = get_safe_poster_url(full_detail_data, movie)

    for s_obj in seasons_to_scrape:
        s_num = s_obj['season']
        e_count = s_obj['episodeCount']
        
        episodes_array = []
        print(f"\n        └─ Season {s_num} (Target: {e_count} Eps): ", end="", flush=True)
        
        for e_num in range(1, e_count + 1):
            stream_info = fetch_stream_url_only(movie_id, s_num, e_num, detail_path, fallback_token)
            
            if stream_info and stream_info.get('url'):
                overall_quality = stream_info['quality']
                
                headers_obj = {
                    "Referer": f"{CONFIG['base_domain']}/",
                    "Origin": "",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                }

                episodes_array.append({
                    "downStatus": "off",
                    "downUrl": stream_info['url'],
                    "duration": "--:--",
                    "episode_title": f"E{e_num}",
                    "headers": headers_obj,
                    "posterUrl": poster,
                    "streamUrl": stream_info['url'],
                    "view": 0
                })
                print(f"E{e_num}✓ ", end="", flush=True)
            else:
                print(f"E{e_num}✗ ", end="", flush=True)
                
            time.sleep(0.15)
            
        # Smart Auto-Probe
        if e_count == 1 and len(episodes_array) == 1:
            probe = 2
            while probe <= 100:
                stream_info = fetch_stream_url_only(movie_id, s_num, probe, detail_path, fallback_token)
                if stream_info and stream_info.get('url'):
                    episodes_array.append({
                        "downStatus": "off",
                        "downUrl": stream_info['url'],
                        "duration": "--:--",
                        "episode_title": f"E{probe}",
                        "headers": {
                            "Referer": f"{CONFIG['base_domain']}/",
                            "Origin": "",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                        },
                        "posterUrl": poster,
                        "streamUrl": stream_info['url'],
                        "view": 0
                    })
                    print(f"E{probe}✓ ", end="", flush=True)
                    probe += 1
                    time.sleep(0.15)
                else:
                    break
                    
        if episodes_array:
            seasons_array.append({
                "season_title": f"Season {s_num}",
                "episodes": episodes_array
            })

    return {
        'fullDetailData': full_detail_data,
        'seasons': seasons_array,
        'quality': overall_quality
    }

def extract_trailer_url(trailer_data):
    if not trailer_data:
        return ""
    if isinstance(trailer_data, str) and trailer_data.startswith('http'):
        return trailer_data
    if isinstance(trailer_data, dict):
        if trailer_data.get('videoAddress', {}).get('url'):
            return trailer_data['videoAddress']['url']
        if trailer_data.get('url'):
            return trailer_data['url']
        if trailer_data.get('videoUrl'):
            return trailer_data['videoUrl']
    return ""

def format_to_desired_json(movie, series_data):
    full_data = {**movie, **series_data.get('fullDetailData', {})}
    
    release_date = str(full_data.get('releaseDate', full_data.get('year', '')))
    year = ""
    yr_matches = re.search(r'(\d{4})', release_date)
    if yr_matches:
        year = yr_matches.group(1)

    raw_title = str(full_data.get('title', full_data.get('name', 'Unknown'))).strip()
    clean_title = re.sub(r'\[.*?\]', '', raw_title).strip()
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    
    title_with_year = clean_title
    if year and f"({year})" not in clean_title:
        title_with_year = f"{clean_title} ({year})"

    genres = ["Unknown"]
    if full_data.get('genre'):
        if isinstance(full_data['genre'], list):
            genres = full_data['genre']
        else:
            genres = [g.strip() for g in full_data['genre'].split(',')]
        genres = [g for g in genres if g]
        if not genres:
            genres = ["Unknown"]

    director = 'N/A'
    if full_data.get('staffList') and isinstance(full_data['staffList'], list):
        directors = [staff['name'] for staff in full_data['staffList'] if str(staff.get('staffType')) == '2']
        if directors:
            director = ', '.join(directors)
        elif full_data['staffList'] and full_data['staffList'][0].get('name'):
            director = full_data['staffList'][0]['name']

    trailer_url = extract_trailer_url(full_data.get('trailer'))
    
    storyline = ""
    if full_data.get('description'):
        storyline = str(full_data['description']).strip()
    elif full_data.get('brief'):
        storyline = str(full_data['brief']).strip()

    poster_url = get_safe_poster_url(series_data.get('fullDetailData', {}), movie)

    return {
        "category": str(CONFIG['filter']['classify']),
        "director": director,
        "genre": genres,
        "imdbRating": float(full_data.get('imdbRatingValue', full_data.get('score', full_data.get('rating', 0.0)))),
        "imdbVotes": int(full_data.get('imdbRatingCount', full_data.get('votes', 0))),
        "language": str(full_data.get('corner', full_data.get('language', 'Unknown'))),
        "posterUrl": poster_url,
        "premium": bool(full_data.get('isVip')),
        "quality": str(series_data.get('quality', 'HD')),
        "releaseDate": release_date,
        "resolution": str(series_data.get('quality', 'HD')),
        "seasons": series_data.get('seasons', []),
        "sliderStatus": "off",
        "sliderUrl": "",
        "status": "on",
        "storyline": storyline,
        "title": title_with_year,
        "triler": trailer_url
    }

def main():
    print("====================================================")
    print("    MovieBox TV Series Auto Scraper (Python Edition)")
    print("====================================================")
    
    # Auto-fetch Token and Setup Cookies before starting
    print("ℹ️  Initializing engine and fetching auth tokens...", flush=True)
    auto_token = fetch_initial_token_and_cookie()
    if auto_token:
        CONFIG['jwt_token'] = auto_token
        print("✅ [SUCCESS] Automatically fetched latest auth token & cookies!", flush=True)
    else:
        print("⚠️ [WARNING] Failed to fetch auto token, continuing with default setup...", flush=True)

    print("ℹ️  Engine ready. Fetching series data...", flush=True)

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
    per_page = CONFIG['per_page']
    pages_scraped_in_batch = 0

    while True:
        print(f"\n[PAGE {page}] Fetching TV series list...", flush=True)

        payload = {
            'channelId': 1, # Added channelId as requested by API standards
            'tabId': CONFIG['filter']['tabId'],
            'classify': CONFIG['filter']['classify'],
            'country': CONFIG['filter']['country'],
            'genre': CONFIG['filter']['genre'],
            'sort': CONFIG['filter']['sort'],
            'year': CONFIG['filter']['year'],
            'page': page,
            'perPage': per_page
        }

        response = request_api(CONFIG['api_url'], payload, CONFIG['jwt_token'], CONFIG['base_domain'])

        if not response:
            print("[STOP] API connection failed.", flush=True)
            break

        items = response.get('data', {}).get('list', response.get('data', {}).get('items', []))
        count = len(items)
        print(f" -> Found: {count} items.", flush=True)

        if count == 0:
            print("🎉 [COMPLETE] No more series left!", flush=True)
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
            
            is_existing = formatted['title'] in series_map
            if is_existing:
                idx = series_map[formatted['title']]
                all_series[idx] = formatted
                print("\n      [Success - Updated]", flush=True)
            else:
                all_series.append(formatted)
                series_map[formatted['title']] = len(all_series) - 1
                print("\n      [Success - Added New Series]", flush=True)
                
        if processed_this_page == 0:
            print("🛑 [LOOP DETECTED] Server repeating data. Terminated.", flush=True)
            break

        # Save to JSON
        with open(CONFIG['output_file'], 'w', encoding='utf-8') as f:
            json.dump(all_series, f, indent=4, ensure_ascii=False)

        pages_scraped_in_batch += 1
        if CONFIG['cooldown_every_pages'] > 0 and (pages_scraped_in_batch % CONFIG['cooldown_every_pages'] == 0):
            print(f"\n☕ [Cooldown] {CONFIG['cooldown_every_pages']} pages done. Waiting {CONFIG['cooldown_seconds']}s...", flush=True)
            time.sleep(CONFIG['cooldown_seconds'])
        else:
            time.sleep(CONFIG['delay_ms'] / 1000.0)
            
        page += 1

    print("\n====================================================")
    print(f"[FINISHED] Total Series Saved: {len(all_series)}")
    print("====================================================", flush=True)

if __name__ == "__main__":
    main()
