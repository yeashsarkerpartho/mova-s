import requests
import json
import time
import os
import random
import re
import urllib.parse
import urllib3

# SSL Warning হাইড করার জন্য
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# কনফিগারেশন সেটআপ
CONFIG = {
    'base_domain': 'https://themoviebox.xyz',
    'output_file': 'series_output.json',
    'progress_file': 'scraper_progress.txt',
    'start_page': 1,
    'per_page': 28,  # ব্রাউজারে 28 পাঠাচ্ছে
    
    # Delays (মিলিসেকেন্ড)
    'min_delay_ms': 800,
    'max_delay_ms': 1500,
    
    # Anti-ban Cooldown
    'cooldown_every_pages': 5, # প্রতি ৫ পেজ পর ব্রেক
    'cooldown_seconds': 15,    # ১৫ সেকেন্ড ব্রেক
    
    'strict_series_only': True, # শুধু সিরিজ সেভ করবে, মুভি বাতিল করবে
    
    'filter': {
        'channelId': 2, # TV Series এর জন্য channelId 2
        'classify': 'Bengali dub'
    }
}

API_URL = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/filter"
DETAIL_API = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/detail"
PLAY_API = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/play"

# Requests Session - এটি অটোমেটিক কুকি হ্যান্ডেল করবে
session = requests.Session()
jwt_token = ""

def get_stealth_headers(token=""):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
        'Origin': CONFIG['base_domain'],
        'Referer': f"{CONFIG['base_domain']}/",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="127", "Chromium";v="127", "Not.A/Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers

def auto_fetch_token():
    """ 
    অটোমেটিক্যালি টোকেন ও সেশন কুকিজ কালেক্ট করার ফাংশন 
    """
    global jwt_token
    print("ℹ️  Fetching initial session and auth tokens...")
    try:
        # হোমপেজে হিট করে কুকিজ নেওয়া
        session.get(CONFIG['base_domain'], headers=get_stealth_headers(), verify=False, timeout=15)
        # কুকি থেকে mb_token খোঁজা
        token = session.cookies.get('mb_token', '')
        if token:
            jwt_token = token
            print(f"✅ Auto-Token fetched successfully! ({token[:15]}...)")
        else:
            print("ℹ️  No explicit token found. Relying on auto Session cookies.")
    except Exception as e:
        print(f"⚠️  Failed to fetch initial cookies: {e}")

def request_api(url, payload):
    headers = get_stealth_headers(jwt_token)
    headers['Content-Type'] = 'application/json'
    try:
        response = session.post(url, json=payload, headers=headers, timeout=20, verify=False)
        if response.status_code == 200:
            return response.json()
        else:
            print(f" [HTTP Code: {response.status_code}] ", end="", flush=True)
    except Exception as e:
        print(f" [API Error: {e}] ", end="", flush=True)
    return None

def get_safe_poster_url(data, fallback={}):
    cover = data.get('cover') or fallback.get('cover')
    if isinstance(cover, dict):
        return cover.get('url', '')
    elif isinstance(cover, str):
        return cover
    return ''

def fetch_subject_detail(movie_id, detail_path):
    url = f"{DETAIL_API}?subjectId={movie_id}&detailPath={urllib.parse.quote(detail_path)}"
    headers = get_stealth_headers(jwt_token)
    try:
        response = session.get(url, headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data.get('data'), dict):
                return data['data']
    except Exception:
        pass
    return {}

def fetch_stream_url_only(movie_id, se, ep, detail_path):
    url = f"{PLAY_API}?subjectId={movie_id}&se={se}&ep={ep}&detailPath={detail_path}&streamSignType=1&supportCodecs%5Bh264%5D=1"
    detail_page_url = f"{CONFIG['base_domain']}/movies/{detail_path}?id={movie_id}&type=/movie/detail&detailSe={se}&detailEp={ep}&lang=en"
    
    headers = get_stealth_headers(jwt_token)
    headers['Referer'] = detail_page_url
    
    try:
        response = session.get(url, headers=headers, timeout=15, verify=False)
        if response.status_code != 200: return None
        
        data = response.json()
        if 'data' not in data or not data['data']: return None
        
        final_url = ''
        quality = 'HD'
        
        streams = data['data'].get('streams', [])
        if streams:
            mp4_list = {int(st.get('resolutions', 0)): st for st in streams if st.get('url')}
            if mp4_list:
                best_res = max(mp4_list.keys())
                best_mp4 = mp4_list[best_res]
                quality = f"{best_res}p"
                final_url = best_mp4['url']
        elif data['data'].get('dash') and data['data']['dash'][0].get('url'):
            quality = 'DASH'
            final_url = data['data']['dash'][0]['url']
            
        if not final_url: return None
        
        return {'url': final_url, 'quality': quality}
    except Exception:
        return None

def fetch_series_seasons_and_episodes(movie):
    movie_id = str(movie.get('subjectId') or movie.get('id', ''))
    title = movie.get('title') or movie.get('name', 'Unknown')
    detail_path = movie.get('detailPath', '')
    
    if not detail_path:
        detail_path = re.sub(r'[^A-Za-z0-9-]+', '-', title).strip('-').lower()
        if not detail_path: detail_path = "detail"
        
    full_detail_data = fetch_subject_detail(movie_id, detail_path)
    
    # Strict Validation: Check if it's actually a Movie
    if CONFIG['strict_series_only']:
        subject_type = full_detail_data.get('subjectType') or movie.get('subjectType', 2)
        if int(subject_type) == 1:
            return None # 1 means Movie, skip it
            
    seasons_array = []
    overall_quality = "HD"
    poster = get_safe_poster_url(full_detail_data, movie)
    
    s_num = 1
    while s_num <= 50:
        episodes_array = []
        e_num = 1
        consecutive_fails = 0
        
        print(f"\n        └─ Season {s_num}: ", end="", flush=True)
        
        while e_num <= 5000:
            stream_info = None
            attempts = 0
            
            # Retry logic for 3 attempts
            while attempts < 3 and not stream_info:
                stream_info = fetch_stream_url_only(movie_id, s_num, e_num, detail_path)
                if not stream_info:
                    attempts += 1
                    if attempts < 3: time.sleep(0.15)
                    
            # Fallback for S0E0 Movie format
            if not stream_info and s_num == 1 and e_num == 1:
                stream_info = fetch_stream_url_only(movie_id, 0, 0, detail_path)
                if stream_info: e_num = 0
                
            if stream_info and stream_info.get('url'):
                consecutive_fails = 0 # Reset fails on success
                overall_quality = stream_info['quality']
                ep_title = "Full Movie" if e_num == 0 else f"E{e_num}"
                
                episodes_array.append({
                    "downStatus": "off",
                    "downUrl": stream_info['url'],
                    "duration": "--:--",
                    "episode_title": ep_title,
                    "headers": {
                        "Referer": f"{CONFIG['base_domain']}/",
                        "Origin": "",
                        "User-Agent": get_stealth_headers()['User-Agent']
                    },
                    "posterUrl": poster,
                    "streamUrl": stream_info['url'],
                    "view": 0
                })
                print(f"{ep_title}✓ ", end="", flush=True)
                if e_num == 0: break
                e_num += 1
            else:
                consecutive_fails += 1
                print(".", end="", flush=True)
                # Tolerance: Break if 25 consecutive episodes are missing
                if consecutive_fails >= 25:
                    break
                e_num += 1
                
            time.sleep(0.12) # 120ms delay
            
        if episodes_array:
            season_title = "Movie Stream" if (e_num == 0 or (len(episodes_array) == 1 and episodes_array[0]['episode_title'] == 'Full Movie')) else f"Season {s_num}"
            seasons_array.append({
                "season_title": season_title,
                "episodes": episodes_array
            })
            if e_num == 0 or season_title == "Movie Stream": break
            s_num += 1
        else:
            break
            
    return {
        'fullDetailData': full_detail_data,
        'seasons': seasons_array,
        'quality': overall_quality
    }

def extract_trailer_url(trailer_data):
    if not trailer_data: return ''
    if isinstance(trailer_data, str) and trailer_data.startswith('http'): return trailer_data
    if isinstance(trailer_data, dict):
        if trailer_data.get('videoAddress', {}).get('url'): return trailer_data['videoAddress']['url']
        if trailer_data.get('url'): return trailer_data['url']
        if trailer_data.get('videoUrl'): return trailer_data['videoUrl']
    return ''

def format_to_desired_json(movie, series_data):
    full_data = {**movie, **series_data.get('fullDetailData', {})}
    
    release_date = str(full_data.get('releaseDate') or full_data.get('year', ''))
    year = ''
    yr_match = re.search(r'(\d{4})', release_date)
    if yr_match: year = yr_match.group(1)
    
    raw_title = str(full_data.get('title') or full_data.get('name', 'Unknown')).strip()
    clean_title = re.sub(r'\[.*?\]', '', raw_title).strip()
    clean_title = re.sub(r'\s+', ' ', clean_title)
    title_with_year = f"{clean_title} ({year})" if year and f"({year})" not in clean_title else clean_title
    
    genres = full_data.get('genre', ['Unknown'])
    if isinstance(genres, str): genres = [g.strip() for g in genres.split(',')]
    
    director = 'N/A'
    staff_list = full_data.get('staffList', [])
    if staff_list and isinstance(staff_list, list):
        directors = [s['name'] for s in staff_list if str(s.get('staffType')) == '2']
        director = ', '.join(directors) if directors else staff_list[0].get('name', 'N/A')
        
    storyline = str(full_data.get('description') or full_data.get('brief', '')).strip()
    
    return {
        "category": str(CONFIG['filter']['classify']),
        "director": director,
        "genre": genres if genres else ["Unknown"],
        "imdbRating": float(full_data.get('imdbRatingValue') or full_data.get('score') or full_data.get('rating') or 0.0),
        "imdbVotes": int(full_data.get('imdbRatingCount') or full_data.get('votes') or 0),
        "language": str(full_data.get('corner') or full_data.get('language') or 'Unknown'),
        "posterUrl": get_safe_poster_url(series_data.get('fullDetailData', {}), movie),
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
        "triler": extract_trailer_url(full_data.get('trailer'))
    }

def main():
    print("====================================================")
    print("    MovieBox TV Series Auto Scraper (Python Edition)")
    print("====================================================")
    
    # প্রথমে টোকেন ও সেশন কুকিজ নেওয়া
    auto_fetch_token()
    
    all_series = []
    series_map = {}
    seen_in_this_run = set()
    
    # বিদ্যমান ডাটা লোড করা (যাতে ডুপ্লিকেট না হয়)
    if os.path.exists(CONFIG['output_file']):
        try:
            with open(CONFIG['output_file'], 'r', encoding='utf-8') as f:
                existing = json.load(f)
                if isinstance(existing, list):
                    all_series = existing
                    for idx, s in enumerate(all_series):
                        if s.get('title'): series_map[s['title']] = idx
            print(f"[INFO] Previously saved: {len(all_series)} series found in DB.")
        except Exception as e:
            print(f"[WARN] Error reading existing JSON: {e}")
            
    # Resume Logic - প্রগ্রেস ফাইল চেক করা
    page = CONFIG['start_page']
    if os.path.exists(CONFIG['progress_file']):
        try:
            with open(CONFIG['progress_file'], 'r') as f:
                saved_page = int(f.read().strip())
                if saved_page > 0:
                    page = saved_page
                    print(f"[INFO] Resuming from Page: {page}")
        except Exception:
            pass
            
    per_page = CONFIG['per_page']
    pages_scraped = 0
    consecutive_failures = 0
    
    while True:
        print(f"\n[PAGE {page}] Fetching TV series list...")
        
        payload = {
            'page': page,
            'perPage': per_page,
            'channelId': CONFIG['filter']['channelId'],
            'classify': CONFIG['filter']['classify']
        }
        
        response = request_api(API_URL, payload)
        
        if not response:
            consecutive_failures += 1
            print(f" -> API request failed. Attempt {consecutive_failures}/5.")
            if consecutive_failures >= 5:
                print("🛑 [STOP] Too many consecutive API failures. IP might be blocked. Pausing script.")
                break
            time.sleep(10)
            continue
            
        consecutive_failures = 0 # রিকোয়েস্ট সাকসেস হলে ফেইল কাউন্ট জিরো
        
        items = response.get('data', {}).get('list') or response.get('data', {}).get('items', [])
        count = len(items)
        print(f" -> Found: {count} items.")
        
        if count == 0:
            print("🎉 [COMPLETE] No more series left! Reached the end.")
            if os.path.exists(CONFIG['progress_file']):
                os.remove(CONFIG['progress_file']) # কাজ শেষ, তাই প্রগ্রেস ডিলিট
            break
            
        processed_this_page = 0
        
        for movie in items:
            mid = str(movie.get('subjectId') or movie.get('id', ''))
            title = movie.get('title') or movie.get('name', 'Unknown')
            
            if not mid or mid in seen_in_this_run: continue
            seen_in_this_run.add(mid)
            
            # Strict Validation (লিস্ট থেকে মুভি বাদ দেওয়া)
            if CONFIG['strict_series_only']:
                if int(movie.get('subjectType', 2)) == 1:
                    print(f"   ▶ {title} [Skipped - Identified as Movie]")
                    continue
                    
            processed_this_page += 1
            print(f"   ▶ {title} [Fetching]... ", end="", flush=True)
            
            series_data = fetch_series_seasons_and_episodes(movie)
            
            if not series_data:
                print("\n      [Skipped - Validated as Movie]")
                continue
            if not series_data.get('seasons'):
                print("\n      [No stream link - Skipped]")
                continue
                
            formatted = format_to_desired_json(movie, series_data)
            
            if formatted['title'] in series_map:
                idx = series_map[formatted['title']]
                all_series[idx] = formatted
                print("\n      [Success - Updated]")
            else:
                all_series.append(formatted)
                series_map[formatted['title']] = len(all_series) - 1
                print("\n      [Success - Added New Series]")
                
            # ডাটা সেভ করা
            with open(CONFIG['output_file'], 'w', encoding='utf-8') as f:
                json.dump(all_series, f, indent=4, ensure_ascii=False)
                
        if processed_this_page == 0 and count > 0:
            print("🛑 [NOTICE] All items on this page were skipped (Movies detected).")
            
        # পেজ সেভ করা
        with open(CONFIG['progress_file'], 'w') as f:
            f.write(str(page + 1))
            
        pages_scraped += 1
        
        if CONFIG['cooldown_every_pages'] > 0 and (pages_scraped % CONFIG['cooldown_every_pages'] == 0):
            print(f"\n☕ [Cooldown] {CONFIG['cooldown_every_pages']} pages done. Taking a break for {CONFIG['cooldown_seconds']}s...")
            time.sleep(CONFIG['cooldown_seconds'])
        else:
            delay = random.uniform(CONFIG['min_delay_ms'], CONFIG['max_delay_ms']) / 1000.0
            time.sleep(delay)
            
        page += 1
        
    print("\n====================================================")
    print(f"[FINISHED] Total Series Saved: {len(all_series)}")
    print("====================================================")

if __name__ == "__main__":
    main()
