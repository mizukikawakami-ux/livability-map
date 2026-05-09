"""
都市公園データ処理スクリプト
ソース: 国土数値情報 P13（都市公園）
神奈川県のShapefileからGeoJSONに変換
"""

import json
import shapefile
from pathlib import Path

BASE = Path(__file__).parent.parent

# 公園種別コード（P13_004）
PARK_TYPE_MAP = {
    1: '街区公園',
    2: '近隣公園',
    3: '地区公園',
    4: '総合公園',
    5: '運動公園',
    6: '広域公園',
    7: 'レクリエーション都市',
    8: '国営公園',
    9: '緩衝緑地',
    10: '都市緑地',
    11: '緑道',
    12: '都市林',
    13: '広場公園',
    14: '特殊公園',  # 風致公園・動植物公園等
}


def process():
    src = BASE / 'data' / 'raw' / 'P13_park' / 'P13-11_14'
    dst = BASE / 'site' / 'data' / 'park.geojson'

    sf = shapefile.Reader(str(src), encoding='cp932')

    features = []
    for rec, shp in zip(sf.iterRecords(), sf.iterShapes()):
        lon, lat = shp.points[0]

        name = rec[2]        # P13_003: 公園名
        park_type = rec[3]   # P13_004: 公園種別
        city = rec[5]        # P13_006: 所在市区町村
        year = rec[6]        # P13_007: 供用開始年
        area = rec[7]        # P13_008: 供用面積(m²)

        type_name = PARK_TYPE_MAP.get(park_type, f'その他({park_type})')

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [lon, lat]
            },
            'properties': {
                'name': name,
                'type': type_name,
                'type_code': park_type,
                'city': city,
                'year': year,
                'area_m2': area,
            }
        })

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # サマリー表示
    type_counts = {}
    total_area = 0
    for f_item in features:
        t = f_item['properties']['type']
        type_counts[t] = type_counts.get(t, 0) + 1
        total_area += f_item['properties']['area_m2'] or 0

    print(f'処理完了: {len(features)}公園')
    print(f'総面積: {total_area:,.0f} m2')
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f'  {t}: {c}件')


if __name__ == '__main__':
    process()
