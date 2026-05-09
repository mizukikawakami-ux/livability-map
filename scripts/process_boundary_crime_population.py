"""
神奈川県全域 町丁目境界データ処理スクリプト
- e-Stat境界Shapefile（r2ka14 = 神奈川県全域）を読み込み
- 犯罪データ（神奈川県警CSV、個別事件形式）を結合
- 人口データ（Shapefileに含まれる）を結合
- 犯罪コロプレスGeoJSON + 人口GeoJSONを出力
"""

import csv
import json
import shapefile
from pathlib import Path


def normalize_town_name(name):
    """町丁目名を正規化（全角数字・漢数字 → 半角数字）"""
    result = ''
    for ch in name:
        cp = ord(ch)
        if 0xFF10 <= cp <= 0xFF19:
            result += chr(cp - 0xFF10 + 0x30)
        else:
            result += ch
    kanji_map = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
                 '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
    for kanji, digit in kanji_map.items():
        result = result.replace(f'{kanji}丁目', f'{digit}丁目')
    return result


def load_crime_from_csv(base):
    """神奈川県警の犯罪CSVから市区町村+町丁目ごとの犯罪件数を集計"""
    crime_dir = base / 'data' / 'raw'
    crime_files = {
        'zitensyatou': '自転車盗',
        'zidousyatou': '自動車盗',
        'ootobaitou': 'オートバイ盗',
        'hittakuri': 'ひったくり',
        'syazyounerai': '車上ねらい',
        'buhinnerai': '部品ねらい',
        'zidouhanbaikinerai': '自動販売機ねらい',
    }

    # key: "市区町村_正規化町丁目" → {count, breakdown}
    crime_map = {}

    for file_key, crime_type in crime_files.items():
        csv_path = crime_dir / f'kanagawa_2024{file_key}.csv'
        if not csv_path.exists():
            continue

        for enc in ['cp932', 'utf-8-sig', 'utf-8']:
            try:
                with open(csv_path, 'r', encoding=enc) as f:
                    reader = csv.reader(f)
                    next(reader)  # skip header
                    for row in reader:
                        if len(row) < 8:
                            continue
                        city = row[6].strip()
                        town_raw = row[7].strip()
                        if not city or not town_raw:
                            continue

                        norm = normalize_town_name(town_raw)
                        key = f'{city}_{norm}'

                        if key not in crime_map:
                            crime_map[key] = {'count': 0, 'breakdown': {}}
                        crime_map[key]['count'] += 1
                        crime_map[key]['breakdown'][crime_type] = \
                            crime_map[key]['breakdown'].get(crime_type, 0) + 1
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

    return crime_map


def process():
    base = Path(__file__).parent.parent
    shp_path = base / 'data' / 'raw' / 'kanagawa_boundary' / 'r2ka14'
    crime_out = base / 'site' / 'data' / 'crime_map.geojson'
    pop_out = base / 'site' / 'data' / 'population.geojson'

    # 犯罪データを生CSVから読み込み
    print('犯罪CSVを読み込み中...')
    crime_data = load_crime_from_csv(base)
    print(f'  {len(crime_data)}町丁目の犯罪データを集計')

    # 境界Shapefileを読み込み
    print('境界Shapefileを読み込み中...')
    sf = shapefile.Reader(str(shp_path), encoding='cp932')
    fields = [f[0] for f in sf.fields[1:]]

    crime_features = []
    pop_features = []
    matched = 0

    for shape_rec in sf.iterShapeRecords():
        rec = dict(zip(fields, shape_rec.record))
        geom = shape_rec.shape.__geo_interface__

        city_name = rec.get('CITY_NAME', '')
        town_name = rec.get('S_NAME', '')
        population = rec.get('JINKO', 0)
        households = rec.get('SETAI', 0)

        if not town_name:
            continue

        # 犯罪データをマッチ
        norm = normalize_town_name(town_name)
        key = f'{city_name}_{norm}'
        display_name = f'{city_name}{town_name}'

        crime_count = 0
        crime_breakdown = ''

        if key in crime_data:
            crime_count = crime_data[key]['count']
            bd = crime_data[key]['breakdown']
            crime_breakdown = ', '.join(f'{k}:{v}' for k, v in bd.items())
            matched += 1

        crime_features.append({
            'type': 'Feature',
            'geometry': geom,
            'properties': {
                'name': display_name,
                'town': town_name,
                'count': crime_count,
                'breakdown': crime_breakdown
            }
        })

        pop_features.append({
            'type': 'Feature',
            'geometry': geom,
            'properties': {
                'name': display_name,
                'town': town_name,
                'population': population or 0,
                'households': households or 0
            }
        })

    crime_out.parent.mkdir(parents=True, exist_ok=True)

    with open(crime_out, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': crime_features},
                  f, ensure_ascii=False)

    with open(pop_out, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': pop_features},
                  f, ensure_ascii=False)

    print(f'犯罪マップ: {len(crime_features)}エリア, {matched}件マッチ -> {crime_out.name}')
    print(f'人口マップ: {len(pop_features)}エリア -> {pop_out.name}')


if __name__ == '__main__':
    process()
