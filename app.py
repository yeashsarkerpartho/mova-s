import requests
import json
import time
import os
import random
import re
import urllib.parse
import urllib3
import base64
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _d(s):
    return base64.b64decode(s).decode('utf-8')

CONFIG = {
    'base_domain': _d('aHR0cHM6Ly90aGVtb3ZpZWJveC54eXo='),
    'output_file': 'series_output.json',
    'progress_file': 'scraper_progress.txt',
    'start_page': 1,
    'per_page': 28,
    'min_delay_ms': 800,
    'max_delay_ms': 1500,
    'cooldown_every_pages': 5,
    'cooldown_seconds': 15,
    'max_threads': 5,
    'max_episodes_limit': 300,
    'always_start_from_page_1': True,
    'strict_series_only': True,
    'filter': {
        'channelId': 2,
        'classify': 'Bengali dub'
    }
}

API_URL = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/filter"
DETAIL_API = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/detail"
PLAY_API = f"{CONFIG['base_domain']}/wefeed-h5api-bff/subject/play"

session = requests.Session()

retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry_strategy)
session.mount('http://', adapter)
session.mount('https://', adapter)

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
    global jwt_token
    try:
        session.get(CONFIG['base_domain'], headers=get_stealth_headers(), verify=False, timeout=15)
        token = session.cookies.get(_d('bWJfdG9rZW4='), '')
        if token:
            jwt_token = token
    except Exception:
        pass

def request_api(url, payload):
    headers = get_stealth_headers(jwt_token)
    headers['Content-Type'] = 'application/json'
    try:
        response = session.post(url, json=payload, headers=headers, timeout=20, verify=False)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
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

def format_episode_dict(e_num, stream_info, poster):
    return {
        "downStatus": "off",
        "downUrl": stream_info['url'],
        "duration": "--:--",
        "episode_title": f"E{e_num}",
        "headers": {
            "Referer": f"{CONFIG['base_domain']}/",
            "Origin": "",
            "User-Agent": get_stealth_headers()['User-Agent']
        },
        "posterUrl": poster,
        "streamUrl": stream_info['url'],
        "view": 0
    }

def fetch_episode_worker(movie_id, se, e_num, detail_path, poster):
    time.sleep(random.uniform(0.1, 0.4))
    stream_info = None
    attempts = 0
    while attempts < 3 and not stream_info:
        stream_info = fetch_stream_url_only(movie_id, se, e_num, detail_path)
        if not stream_info:
            attempts += 1
            if attempts < 3: time.sleep(0.15)
    if not stream_info and se == 1 and e_num == 1:
        stream_info = fetch_stream_url_only(movie_id, 0, 0, detail_path)
    if stream_info and stream_info.get('url'):
        print(f"E{e_num}✓ ", end="", flush=True)
        return e_num, stream_info
    else:
        print(f"E{e_num}✗ ", end="", flush=True)
        return e_num, None

def fetch_series_seasons_and_episodes(movie):
    movie_id = str(movie.get('subjectId') or movie.get('id', ''))
    title = movie.get('title') or movie.get('name', 'Unknown')
    detail_path = movie.get('detailPath', '')
    if not detail_path:
        d_url = movie.get('detailUrl', '')
        if d_url and '/movies/' in d_url:
            detail_path = d_url.split('/movies/')[-1].split('?')[0]
        else:
            detail_path = re.sub(r'[^A-Za-z0-9-]+', '-', title).strip('-').lower()
            if not detail_path: detail_path = "detail"
    full_detail_data = fetch_subject_detail(movie_id, detail_path)
    if CONFIG['strict_series_only']:
        subject_type = full_detail_data.get('subjectType') or movie.get('subjectType', 2)
        if int(subject_type) == 1:
            return None
    season_list_api = full_detail_data.get('seasonList') or full_detail_data.get('seasons') or []
    seasons_to_scrape = []
    if season_list_api and isinstance(season_list_api, list):
        for s in season_list_api:
            s_n = s.get('season')
            if s_n is None: s_n = s.get('se')
            if s_n is None: s_n = s.get('seasonNo')
            s_num = int(s_n) if (s_n is not None and str(s_n).isdigit()) else 1
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

    all_generated_series = []
    chunk_size = CONFIG['max_episodes_limit']
    base_seasons_array = []
    overall_quality = "HD"
    poster = get_safe_poster_url(full_detail_data, movie)
    known_seasons_map = {s['season']: s['episodeCount'] for s in seasons_to_scrape}
    seasons_to_process = set(known_seasons_map.keys())
    seasons_to_process.update([1, 2, 3, 4, 5])
    if seasons_to_process:
        max_s = max(seasons_to_process)
        seasons_to_process.update([max_s + 1, max_s + 2])
    sorted_seasons = sorted(list(seasons_to_process))

    for s_num in sorted_seasons:
        e_count = known_seasons_map.get(s_num, 1)
        if e_count > chunk_size:
            print(f"\n        └─ Season {s_num}: ", flush=True)
            chunks = []
            for start in range(1, e_count + 1, chunk_size):
                end = min(start + chunk_size - 1, e_count)
                chunks.append((start, end))
            for start_ep, end_ep in chunks:
                print(f"\n           ├─ Ep {start_ep}-{end_ep}: ", end="", flush=True)
                episodes_data_map = {}
                episodes_to_fetch = list(range(start_ep, end_ep + 1))
                with ThreadPoolExecutor(max_workers=CONFIG['max_threads']) as executor:
                    futures = {executor.submit(fetch_episode_worker, movie_id, s_num, ep, detail_path, poster): ep for ep in episodes_to_fetch}
                    for future in as_completed(futures):
                        ep_num, stream_info = future.result()
                        if stream_info:
                            overall_quality = stream_info['quality']
                            episodes_data_map[ep_num] = format_episode_dict(ep_num, stream_info, poster)
                if end_ep == e_count:
                    found_any = len(episodes_data_map) > 0
                    max_fails = 6 if found_any else 3
                    probe_start = end_ep + 1
                    consecutive_fails = 0
                    while probe_start <= e_count + 4000 and consecutive_fails < max_fails:
                        batch_end = min(probe_start + 3, e_count + 4001)
                        probe_batch = list(range(probe_start, batch_end))
                        batch_success = False
                        with ThreadPoolExecutor(max_workers=min(len(probe_batch), 3)) as executor:
                            futures = {executor.submit(fetch_episode_worker, movie_id, s_num, ep, detail_path, poster): ep for ep in probe_batch}
                            for future in as_completed(futures):
                                ep_num, stream_info = future.result()
                                if stream_info:
                                    episodes_data_map[ep_num] = format_episode_dict(ep_num, stream_info, poster)
                                    batch_success = True
                                    overall_quality = stream_info['quality']
                        if not batch_success:
                            consecutive_fails += len(probe_batch)
                        else:
                            consecutive_fails = 0
                            max_fails = 6
                        probe_start += len(probe_batch)
                        if consecutive_fails < max_fails:
                            time.sleep(0.3)
                if episodes_data_map:
                    sorted_eps = [episodes_data_map[k] for k in sorted(episodes_data_map.keys())]
                    if len(sorted_eps) > chunk_size and end_ep == e_count:
                        sub_chunks = [sorted_eps[i:i + chunk_size] for i in range(0, len(sorted_eps), chunk_size)]
                        for chnk in sub_chunks:
                            s_ep = chnk[0]['episode_title'].replace('E', '')
                            e_ep = chnk[-1]['episode_title'].replace('E', '')
                            chunked_series_data = {
                                'fullDetailData': full_detail_data,
                                'seasons': [{"season_title": f"Season {s_num}", "episodes": chnk}],
                                'quality': overall_quality
                            }
                            formatted_chunk = format_to_desired_json(movie, chunked_series_data)
                            formatted_chunk['title'] = f"{formatted_chunk['title']} Ep {s_ep}-{e_ep}"
                            all_generated_series.append(formatted_chunk)
                    else:
                        actual_start = sorted_eps[0]['episode_title'].replace('E', '')
                        actual_end = sorted_eps[-1]['episode_title'].replace('E', '')
                        chunked_series_data = {
                            'fullDetailData': full_detail_data,
                            'seasons': [{"season_title": f"Season {s_num}", "episodes": sorted_eps}],
                            'quality': overall_quality
                        }
                        formatted_chunk = format_to_desired_json(movie, chunked_series_data)
                        formatted_chunk['title'] = f"{formatted_chunk['title']} Ep {actual_start}-{actual_end}"
                        all_generated_series.append(formatted_chunk)
                else:
                    print(" []", end="")
        else:
            print(f"\n        └─ Season {s_num}: ", end="", flush=True)
            episodes_data_map = {}
            episodes_to_fetch = list(range(1, e_count + 1))
            with ThreadPoolExecutor(max_workers=CONFIG['max_threads']) as executor:
                futures = {executor.submit(fetch_episode_worker, movie_id, s_num, ep, detail_path, poster): ep for ep in episodes_to_fetch}
                for future in as_completed(futures):
                    ep_num, stream_info = future.result()
                    if stream_info:
                        overall_quality = stream_info['quality']
                        episodes_data_map[ep_num] = format_episode_dict(ep_num, stream_info, poster)
            found_any = len(episodes_data_map) > 0
            max_fails = 6 if found_any else 3
            probe_start = max(1, e_count) + 1
            consecutive_fails = 0
            while probe_start <= e_count + 4000 and consecutive_fails < max_fails:
                batch_end = probe_start + 3
                probe_batch = list(range(probe_start, batch_end))
                batch_success = False
                with ThreadPoolExecutor(max_workers=min(len(probe_batch), 3)) as executor:
                    futures = {executor.submit(fetch_episode_worker, movie_id, s_num, ep, detail_path, poster): ep for ep in probe_batch}
                    for future in as_completed(futures):
                        ep_num, stream_info = future.result()
                        if stream_info:
                            episodes_data_map[ep_num] = format_episode_dict(ep_num, stream_info, poster)
                            batch_success = True
                            overall_quality = stream_info['quality']
                if not batch_success:
                    consecutive_fails += len(probe_batch)
                else:
                    consecutive_fails = 0
                    max_fails = 6
                probe_start += len(probe_batch)
                if consecutive_fails < max_fails:
                    time.sleep(0.3)
            if episodes_data_map:
                sorted_eps = [episodes_data_map[k] for k in sorted(episodes_data_map.keys())]
                if len(sorted_eps) > chunk_size:
                    sub_chunks = [sorted_eps[i:i + chunk_size] for i in range(0, len(sorted_eps), chunk_size)]
                    for chnk in sub_chunks:
                        s_ep = chnk[0]['episode_title'].replace('E', '')
                        e_ep = chnk[-1]['episode_title'].replace('E', '')
                        chunked_series_data = {
                            'fullDetailData': full_detail_data,
                            'seasons': [{"season_title": f"Season {s_num}", "episodes": chnk}],
                            'quality': overall_quality
                        }
                        formatted_chunk = format_to_desired_json(movie, chunked_series_data)
                        formatted_chunk['title'] = f"{formatted_chunk['title']} Ep {s_ep}-{e_ep}"
                        all_generated_series.append(formatted_chunk)
                else:
                    base_seasons_array.append({
                        "season_title": f"Season {s_num}",
                        "episodes": sorted_eps
                    })
            else:
                print(" []", end="")

    if base_seasons_array:
        base_series_data = {
            'fullDetailData': full_detail_data,
            'seasons': base_seasons_array,
            'quality': overall_quality
        }
        formatted_base = format_to_desired_json(movie, base_series_data)
        all_generated_series.append(formatted_base)

    return all_generated_series

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
    print("="*50)
    print(f"    {_d('TW92aWVCb3g=')} TV Series Auto Scraper")
    print("="*50)
    auto_fetch_token()
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
                        if s.get('title'): series_map[s['title']] = idx
        except Exception:
            pass
    page = CONFIG['start_page']
    if CONFIG.get('always_start_from_page_1', True):
        if os.path.exists(CONFIG['progress_file']):
            os.remove(CONFIG['progress_file'])
    else:
        if os.path.exists(CONFIG['progress_file']):
            try:
                with open(CONFIG['progress_file'], 'r') as f:
                    saved_page = int(f.read().strip())
                    if saved_page > 0:
                        page = saved_page
            except Exception:
                pass
    per_page = CONFIG['per_page']
    pages_scraped = 0
    consecutive_failures = 0

    while True:
        print(f"\n[PAGE {page}] Fetching...")
        payload = {
            'page': page,
            'perPage': per_page,
            'channelId': CONFIG['filter']['channelId'],
            'classify': CONFIG['filter']['classify']
        }
        response = request_api(API_URL, payload)
        if not response:
            consecutive_failures += 1
            if consecutive_failures == 2:
                auto_fetch_token()
            if consecutive_failures >= 5:
                if page > 100:
                    if os.path.exists(CONFIG['progress_file']):
                        os.remove(CONFIG['progress_file'])
                break
            time.sleep(10)
            continue
        consecutive_failures = 0
        items = response.get('data', {}).get('list') or response.get('data', {}).get('items', [])
        count = len(items)
        if count == 0:
            if os.path.exists(CONFIG['progress_file']):
                os.remove(CONFIG['progress_file'])
            break
        processed_this_page = 0
        for movie in items:
            mid = str(movie.get('subjectId') or movie.get('id', ''))
            title = movie.get('title') or movie.get('name', 'Unknown')
            if not mid or mid in seen_in_this_run: continue
            seen_in_this_run.add(mid)
            if CONFIG['strict_series_only']:
                if int(movie.get('subjectType', 2)) == 1:
                    continue
            processed_this_page += 1
            print(f"   ▶ {title} ... ", end="", flush=True)
            generated_series_list = fetch_series_seasons_and_episodes(movie)
            if generated_series_list is None:
                continue
            if not generated_series_list:
                continue
            for formatted in generated_series_list:
                formatted_title = formatted['title']
                if formatted_title in series_map:
                    idx = series_map[formatted_title]
                    all_series[idx] = formatted
                else:
                    all_series.append(formatted)
                    series_map[formatted_title] = len(all_series) - 1
            with open(CONFIG['output_file'], 'w', encoding='utf-8') as f:
                json.dump(all_series, f, indent=4, ensure_ascii=False)
        with open(CONFIG['progress_file'], 'w') as f:
            f.write(str(page + 1))
        pages_scraped += 1
        if CONFIG['cooldown_every_pages'] > 0 and (pages_scraped % CONFIG['cooldown_every_pages'] == 0):
            time.sleep(CONFIG['cooldown_seconds'])
        else:
            delay = random.uniform(CONFIG['min_delay_ms'], CONFIG['max_delay_ms']) / 1000.0
            time.sleep(delay)
        page += 1

    print("\n" + "="*50)
    print(f"Total: {len(all_series)}")
    print("="*50)

if __name__ == "__main__":
    main()
