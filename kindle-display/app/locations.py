"""Bounded place lookup, Chinese aliases, and city-first presentation."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
import unicodedata
import urllib.parse
import urllib.request
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from opencc import OpenCC
from pypinyin import lazy_pinyin

SIMPLIFIED = OpenCC('t2s')
TRADITIONAL = OpenCC('s2t')
HAN = re.compile(r'^[\u3400-\u9fff]+$')


def normalize(query):
    return ' '.join(SIMPLIFIED.convert(unicodedata.normalize('NFKC', query)).split())


def stem(name):
    return name[:-1] if len(name) > 2 and name.endswith(('市', '县', '区')) else name


def key(name):
    return ''.join(c for c in unicodedata.normalize('NFKD', stem(normalize(name))).casefold() if c.isalnum())


def variants(query):
    place, comma, qualifier = query.partition(',')
    place = place.strip()
    if not HAN.fullmatch(place):
        return []
    base = stem(place)
    names = [TRADITIONAL.convert(place)] + [base + suffix for suffix in ('市', '县', '区')]
    if base != place:
        names.insert(0, base)
    names.append(''.join(lazy_pinyin(base)))
    return list(dict.fromkeys(n + (', ' + qualifier.strip() if comma else '') for n in names if n != place))[:5]


def fetch(query):
    url = 'https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode(
        {'name': query, 'count': 40, 'language': 'zh', 'format': 'json'})
    with urllib.request.urlopen(url, timeout=6) as response:
        value = json.loads(response.read(1000000))
    if not isinstance(value, dict) or value.get('error'):
        raise ValueError('Invalid geocoding response')
    rows = value.get('results', [])
    if not isinstance(rows, list):
        raise ValueError('Invalid geocoding results')
    return rows


def clean_label(value):
    # Some upstream translations concatenate two spellings in a single field.
    return normalize(str(value or '').split(' or ')[0])


def candidate(row):
    if not isinstance(row, dict):
        return None
    try:
        name = clean_label(row['name'])
        latitude, longitude = row['latitude'], row['longitude']
        if not name or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit
                           for v, limit in ((latitude, 90), (longitude, 180))):
            return None
        ZoneInfo(row['timezone'])
        feature = row.get('feature_code') or ''
        if not isinstance(feature, str):
            return None
        major = feature == 'PPLC' or feature.startswith('PPLA') or feature in {'ADM1', 'ADM2', 'ADM3', 'ADM4'}
        parts = []
        for part in (name, row.get('admin2'), row.get('admin1'), row.get('country')):
            label = clean_label(part)
            label_key = lambda text: key(text.removesuffix('省'))
            if label and label_key(label) not in {label_key(p) for p in parts}:
                parts.append(label)
        return {'id': str(row['id']), 'name': name, 'label': ' · '.join(parts),
                'latitude': latitude, 'longitude': longitude, 'timezone': row['timezone'],
                'kind': 'city' if major else 'locality',
                '_population': row.get('population') if type(row.get('population')) in (int, float) else 0}
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return None


def affinity(item, query):
    term = key(query.partition(',')[0])
    names = {key(item['name']), key(''.join(lazy_pinyin(stem(item['name']))))}
    return 0 if term in names else 1 if any(n.startswith(term) for n in names) else 2


def search(query):
    query = normalize(query)
    rows, failed = [], False
    try:
        rows = fetch(query)
    except (OSError, ValueError):
        failed = True
    first = [c for row in rows if (c := candidate(row))]
    # Two-character Chinese queries require exact upstream indexed names.
    # Try suffixed names and pronunciation only when no exact city was found.
    fallback = variants(query) if not any(c['kind'] == 'city' and affinity(c, query) == 0 for c in first) else []
    if fallback:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch, name) for name in fallback]
            for future in futures:
                try:
                    rows.extend(future.result())
                except (OSError, ValueError):
                    failed = True
    by_id = {}
    for row in rows:
        item = candidate(row)
        if item:
            by_id.setdefault(item['id'], item)
    ranked = sorted(by_id.values(), key=lambda c: (c['kind'] != 'city', affinity(c, query), -c['_population'], c['label'], c['id']))
    if not ranked and failed:
        raise OSError('Location search temporarily unavailable')
    exact_city = any(c['kind'] == 'city' and affinity(c, query) == 0 for c in ranked)
    cities = [c for c in ranked if c['kind'] == 'city' and (not exact_city or affinity(c, query) == 0)]
    primary_ids = {c['id'] for c in cities}
    others = [c for c in ranked if c['id'] not in primary_ids]
    primary, more = cities[:8], cities[8:] + others
    for item in ranked:
        item.pop('_population')
    return {'results': primary, 'more_results': more[:32], 'partial': failed}
