"""
医療施設データ処理スクリプト
ソース: 国土数値情報 P04（医療機関）
P04_001: 医療機関分類 (1=病院, 2=一般診療所, 3=歯科診療所)
P04_002: 施設名
P04_003: 所在地
P04_004: 診療科目1
"""

import json
from pathlib import Path

AOBA_BOUNDS = {
    'lat_min': 35.53, 'lat_max': 35.59,
    'lon_min': 139.48, 'lon_max': 139.55
}

TYPE_MAP = {'1': '病院', '2': '診療所', '3': '歯科'}


def process():
    base = Path(__file__).parent.parent
    src = base / 'data' / 'raw' / 'P04_kanagawa' / 'P04-20_14_GML' / 'P04-20_14.geojson'
    dst = base / 'site' / 'data' / 'medical.geojson'

    with open(src, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = []
    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]

        if not (AOBA_BOUNDS['lat_min'] <= lat <= AOBA_BOUNDS['lat_max'] and
                AOBA_BOUNDS['lon_min'] <= lon <= AOBA_BOUNDS['lon_max']):
            continue

        props = feat['properties']
        type_code = str(props.get('P04_001', ''))
        name = props.get('P04_002', '')
        address = props.get('P04_003', '')
        dept = props.get('P04_004', '')

        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {
                'name': name or '不明',
                'type': TYPE_MAP.get(type_code, '不明'),
                'department': dept or '不明',
                'address': address or ''
            }
        })

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'処理完了: {len(features)}件の医療施設を青葉区から抽出')


if __name__ == '__main__':
    process()
