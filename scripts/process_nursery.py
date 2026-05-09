"""
保育所データ処理スクリプト
ソース: 横浜市オープンデータ
ジオコーディング: 国土地理院 住所検索API
"""

import csv
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path


def geocode(address):
    """国土地理院APIで住所→座標を取得"""
    url = 'https://msearch.gsi.go.jp/address-search/AddressSearch?q=' + urllib.parse.quote(address)
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            data = json.loads(res.read())
            if data and len(data) > 0:
                coords = data[0]['geometry']['coordinates']
                return coords[0], coords[1]
    except Exception:
        pass
    return None, None


def process():
    base = Path(__file__).parent.parent
    csv_path = base / 'data' / 'raw' / 'yokohama_nursery.csv'
    dst = base / 'site' / 'data' / 'nursery.geojson'

    features = []
    skipped = 0
    geocoded = 0

    for enc in ['cp932', 'utf-8-sig', 'utf-8']:
        try:
            with open(csv_path, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city = row.get('施設の所在地 市区町村', '')
                    if '青葉区' not in city:
                        continue

                    name = row.get('施設の名称', '')
                    address = row.get('施設の所在地 町名・番地', '')
                    capacity_str = row.get('合計_利用定員数', '0')
                    try:
                        capacity = int(capacity_str) if capacity_str else 0
                    except ValueError:
                        capacity = 0

                    full_address = '横浜市青葉区' + address
                    lon, lat = geocode(full_address)

                    if lon is None:
                        short_address = '横浜市青葉区' + address.split('－')[0] if '－' in address else full_address
                        lon, lat = geocode(short_address)

                    if lon is None:
                        skipped += 1
                        print(f'  スキップ: {name} ({address})')
                        continue

                    geocoded += 1
                    features.append({
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [lon, lat]
                        },
                        'properties': {
                            'name': name,
                            'capacity': capacity,
                            'address': f'横浜市青葉区{address}'
                        }
                    })
                    time.sleep(0.2)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'処理完了: {geocoded}件ジオコーディング成功 (スキップ: {skipped}件)')


if __name__ == '__main__':
    process()
