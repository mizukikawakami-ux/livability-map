"""
地価公示データ処理スクリプト
ソース: 国土数値情報 L01（地価公示）
対象: 神奈川県全域
"""

import json
from pathlib import Path

USE_MAP = {
    '住宅': '住宅地', '宅地': '住宅地', '店舗': '商業地',
    '事務所': '商業地', '工場': '工業地'
}


def process():
    base = Path(__file__).parent.parent
    src = base / 'data' / 'raw' / 'L01_kanagawa' / 'L01-25_14_GML' / 'L01-25_14.geojson'
    dst = base / 'site' / 'data' / 'landprice.geojson'

    with open(src, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = []
    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]

        props = feat['properties']
        price = props.get('L01_008', 0)
        address = props.get('L01_025', '')
        current_use = props.get('L01_028', '')
        area_type = props.get('L01_051', '')

        price_history = []
        for i in range(72, 105):
            key = f'L01_{i:03d}'
            val = props.get(key, 0)
            if val and val != 0 and val != '0':
                price_history.append(int(val))

        change_rate = ''
        if len(price_history) >= 2 and price_history[-2] > 0:
            rate = (price_history[-1] - price_history[-2]) / price_history[-2] * 100
            change_rate = f'{rate:+.1f}%'

        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {
                'price': int(price) if price else 0,
                'address': address,
                'use': current_use,
                'area_type': area_type,
                'change': change_rate
            }
        })

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'処理完了: {len(features)}件の地価データを神奈川県から抽出')


if __name__ == '__main__':
    process()
