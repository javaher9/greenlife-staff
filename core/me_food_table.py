"""Versioned, server-calculated meal snapshots. Never trust client nutrition totals."""
import json
import math
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name('me_food_catalog.json').read_text(encoding='utf-8'))
FOODS = {f['id']: f for f in CATALOG['foods']}


def food_table(value):
    if not isinstance(value, dict) or set(value) != {'version', 'items'} or value['version'] != CATALOG['version']:
        raise ValueError('نسخهٔ اطلاعات غذاها تغییر کرده؛ صفحه را تازه‌سازی کن.')
    items = value['items']
    if not isinstance(items, list) or not 1 <= len(items) <= len(FOODS):
        raise ValueError('ابتدا غذاهای مصرف‌شده را روی میز بچین.')
    result = []
    seen = set()
    kcal = gl = 0
    missing = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id', 'servings'}:
            raise ValueError('اطلاعات خوراکی معتبر نیست.')
        food_id, q = item['id'], item['servings']
        if not isinstance(food_id, str) or food_id not in FOODS or food_id in seen or type(q) not in (int, float) or not math.isfinite(q) or not .25 <= q <= 4 or q * 4 != int(q * 4):
            raise ValueError('خوراکی یا مقدار آن معتبر نیست.')
        seen.add(food_id)
        f = FOODS[food_id]
        item_gl = 0 if f['totalCarb'] == 0 else None if f['gi'] is None or f['carb'] is None else f['gi'] * f['carb'] * q / 100
        kcal += f['kcal'] * q
        if item_gl is None:
            missing += 1
        else:
            gl += item_gl
        result.append({'id': food_id, 'name': f['name'], 'description': f['description'], 'servings': q, 'grams': round(f['grams'] * q, 2), 'kcal': round(f['kcal'] * q, 2), 'gi': f['gi'], 'gl': None if item_gl is None else round(item_gl, 2), 'source': f['source'], 'giSource': f['giSource']})
    return {'version': CATALOG['version'], 'items': result, 'kcal': round(kcal, 2), 'glKnown': round(gl, 2), 'glMissing': missing, 'estimated': True, 'sources': CATALOG['sources']}
