# Complete, well-commented, runnable code for this single file
import requests
import json
import time
import re
import os
import sys

# Disable warnings for unverified HTTPS requests
requests.packages.urllib3.disable_warnings()

CONFIG = {
    'base_domain': 'https://themoviebox.xyz',
    'jwt_token': '', 
    
    'output_file': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'series_output.json'),
    'start_page': 1,
    'per_page': 24,       
    'delay_ms': 800,      
    
    'cooldown_every_pages': 10,
    'cooldown_seconds': 8, 
    'delay_between_episodes_ms': 120, # From PHP
    
    'filter': {
        'tabId': 1, # Kept exactly as PHP
        'classify': 'Bengali dub',
        'country': 'All',
        'genre': 'All',
        'sort': 'ForYou', 
        'year': 'All'
    },
    'category_name': 'Bengali Collection'
}

CONFIG['api_url'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/filter"
CONFIG['detail_api'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/detail"
CONFIG['play_api'] = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/play"

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
    url = f"{CONFIG['base_domain']}/"
    headers = get_stealth_headers(base_domain=CONFIG['base_domain'])
    
    try:
        response = session.get(url, headers=headers, timeout=15, verify=False)
        token = ""
        
        # Check NEXT_DATA
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', response.text, re.DOTALL)
        if match:
            t_match = re.search(r'"token"\s*:\s*"([a-zA-Z0-9\.\-_]+)"', match.group(1), re.IGNORECASE)
            if t_match:
                token = t_match.group(1)
                
        # Generic fallback
        if not token:
            t_match = re.search(r'"(?:accessToken|jwtToken|token)"\s*:\s*"([a-zA-Z0-9\.\-_]{20,})"', response.text, re.IGNORECASE)
            if t_match:
                token = t_match.group(1)
                
        # Direct cookie
        if not token:
            token = session.cookies.get('mb_auth_token') or session.cookies.get('mb_token') or ""
            
        return token
    except Exception as e:
        print(f"Error fetching initial token: {e}")
        return ""

def request_api(url, payload, token, base_domain):
    headers = get_stealth_headers(token, base_domain)
    headers['Content-Type'] = 'application/json'
    
    try:
        response = session.post(url, json=payload, headers=headers, timeout=20, verify=False)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def get_safe_poster_url(data, fallback={}):
    possible_keys = ['cover', 'verticalCover', 'horizontalCover', 'poster', 'thumb', 'image', 'pic']
    
    for k in possible_keys:
        val = data.get(k)
        if val:
            if isinstance(val, dict) and val.get('url'): return val['url']
            if isinstance(val, str): return val
            
    for k in possible_keys:
        val = fallback.get(k)
        if val:
            if isinstance(val, dict) and val.get('url'): return val['url']
            if isinstance(val, str): return val
            
    return ""

def fetch_subject_detail(movie_id, detail_path, token):
    detail_url = f"{CONFIG['detail_api']}?subjectId={movie_id}&detailPath={detail_path}"
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

    # Specific stealth headers exactly like PHP
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

    if token:
        api_headers['authorization'] = f"Bearer {token}"

    try:
        res = session.get(play_api_url, headers=api_headers, timeout=15, verify=False)
        if res.status_code != 200: return None
        
        data = res.json()
        if 'data' not in data: return None
        
        final_url = ""
        quality = "HD"
        
        if data['data'].get('streams'):
            mp4_list = {int(st.get('resolutions', 0)): st for st in data['data']['streams'] if st.get('url')}
            if mp4_list:
                best_res = sorted(mp4_list.keys(), reverse=True)[0]
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
    movie_id = str(movie.get('subjectId') or movie.get('id') or '')
    title = movie.get('title') or movie.get('name') or 'Unknown'
    detail_path = movie.get('detailPath', '')

    if not detail_path:
        detail_path = re.sub(r'[^A-Za-z0-9-]+', '-', title).strip('-').lower()
        if not detail_path: detail_path = "detail"

    full_detail_data = fetch_subject_detail(movie_id, detail_path, fallback_token)
    
    # PHP Logic: Gather target seasons and episode counts
    season_list_api = full_detail_data.get('seasonList') or full_detail_data.get('seasons') or []
    seasons_to_scrape = []
    
    if isinstance(season_list_api, list) and season_list_api:
        for s in season_list_api:
            s_num = int(s.get('season') or s.get('se') or 1)
            e_list = s.get('episodes') or s.get('episodeList') or []
            e_count = len(e_list) if e_list else int(s.get('episodeCount') or s.get('maxEp') or s.get('curEpisode') or 0)
            if e_count == 0:
                e_count = int(movie.get('curEpisode') or movie.get('episodeCount') or 1)
            seasons_to_scrape.append({'season': s_num, 'episodeCount': max(1, e_count)})
            
    if not seasons_to_scrape:
        ep_count = int(full_detail_data.get('episodeCount') or full_detail_data.get('curEpisode') or movie.get('curEpisode') or movie.get('episodeCount') or 1)
        s_count = int(full_detail_data.get('seasonCount') or movie.get('season') or 1)
        for s in range(1, max(1, s_count) + 1):
            seasons_to_scrape.append({'season': s, 'episodeCount': max(1, ep_count)})

    seasons_array = []
    overall_quality = "HD"
    poster = get_safe_poster_url(full_detail_data, movie)
    
    # Exact PHP Logic for fetching
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
                
            time.sleep(150000 / 1000000.0) # 150ms exact as PHP usleep(150000)

        # Smart Auto-Probe (Exactly as PHP)
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
                    time.sleep(150000 / 1000000.0)
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

def format_to_desired_json(movie, series_data, config):
    movie_copy = movie.copy()
    if series_data and series_data.get('fullDetailData'):
        movie_copy.update(series_data['fullDetailData'])
        
    release_date = str(movie_copy.get('releaseDate') or movie_copy.get('year') or '')
    
    year_match = re.search(r'(\d{4})', release_date)
    year = year_match.group(1) if year_match else ''
    
    raw_title = str(movie_copy.get('title') or movie_copy.get('name') or 'Unknown')
    clean_title = re.sub(r'\[.*?\]', '', raw_title).strip()
    clean_title = re.sub(r'\s+', ' ', clean_title)
    
    title_with_year = f"{clean_title} ({year})" if year and f"({year})" not in clean_title else clean_title

    genres = ["Unknown"]
    if movie_copy.get('genre'):
        g = movie_copy['genre']
        genres = g if isinstance(g, list) else [x.strip() for x in g.split(',')]
        
    director = 'N/A'
    staff_list = movie_copy.get('staffList', [])
    if isinstance(staff_list, list) and staff_list:
        directors = [s['name'] for s in staff_list if str(s.get('staffType')) == '2' and s.get('name')]
        director = ', '.join(directors) if directors else staff_list[0].get('name', 'N/A')

    trailer_data = movie_copy.get('trailer')
    trailer_url = ""
    if trailer_data:
        if isinstance(trailer_data, str) and trailer_data.startswith('http'): trailer_url = trailer_data
        elif isinstance(trailer_data, dict):
            if trailer_data.get('videoAddress', {}).get('url'): trailer_url = trailer_data['videoAddress']['url']
            elif trailer_data.get('url'): trailer_url = trailer_data['url']
            elif trailer_data.get('videoUrl'): trailer_url = trailer_data['videoUrl']

    storyline = str(movie_copy.get('description') or movie_copy.get('brief') or '').strip()
    poster_url = get_safe_poster_url(series_data.get('fullDetailData', {}), movie)

    return {
        "category": str(config['filter'].get('classify', 'Unknown')),
        "director": str(director),
        "genre": [g for g in genres if g],
        "imdbRating": float(movie_copy.get('imdbRatingValue') or movie_copy.get('score') or movie_copy.get('rating') or 0.0),
        "imdbVotes": int(movie_copy.get('imdbRatingCount') or movie_copy.get('votes') or 0),
        "language": str(movie_copy.get('corner') or movie_copy.get('language') or 'Unknown'),
        "posterUrl": str(poster_url),
        "premium": bool(movie_copy.get('isVip')),
        "quality": str(series_data.get('quality', 'HD')),
        "releaseDate": str(release_date),
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
    print("    MovieBox TV Series Auto Scraper (JSON Format)")
    print("====================================================")
    
    print("ℹ️  Initializing engine and fetching auth tokens...", flush=True)
    auto_token = fetch_initial_token_and_cookie()
    if auto_token:
        CONFIG['jwt_token'] = auto_token
        print("✅ [SUCCESS] Automatically fetched latest auth token!", flush=True)
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
        except Exception:
            pass

    page = CONFIG['start_page']
    pages_scraped_in_batch = 0

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
            print("[STOP] API connection failed.", flush=True)
            break

        items = response.get('data', {}).get('list') or response.get('data', {}).get('items') or []
        count = len(items)
        print(f" -> Found: {count} items.", flush=True)

        if count == 0:
            print("🎉 [COMPLETE] No more series left!", flush=True)
            break

        processed_this_page = 0

        for movie in items:
            mid = str(movie.get('subjectId') or movie.get('id') or '')
            title = movie.get('title') or movie.get('name') or 'Unknown'
            
            # PHP logic to completely skip movies without streams
            if not mid: continue
            
            # Additional Check to skip strictly non-series items if they leak through
            # subjectType 1 is usually Movie, 2 is TV Show in MovieBox
            sub_type = str(movie.get('subjectType', ''))
            if sub_type == '1':
                print(f"   ⏭ {title} [Skipping Movie]", flush=True)
                continue

            if mid in seen_in_this_run: continue
            seen_in_this_run.add(mid)
            processed_this_page += 1

            print(f"   ▶ {title} [Fetching]... ", end="", flush=True)

            series_data = fetch_series_seasons_and_episodes(movie, CONFIG['jwt_token'])

            if not series_data or not series_data.get('seasons'):
                print("\n      [No stream link - Skipped]", flush=True)
                continue

            formatted = format_to_desired_json(movie, series_data, CONFIG)
            
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
    print("====================================================")

if __name__ == "__main__":
    main()
