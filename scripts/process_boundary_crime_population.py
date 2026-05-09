"""
町丁目境界データ処理スクリプト
- e-Stat境界Shapefileを読み込み
- 犯罪データ（町丁目名ベース）を結合
- 人口データ（Shapefileに含まれる）を結合
- 犯罪コロプレスGeoJSON + 人口GeoJSONを出力
"""

import shapefile
import json
from pathlib import Path


def load_crime_data(crime_geojson_path):
    """犯罪GeoJSON（座標なし）から町丁目→件数のマップを作成"""
    with open(crime_geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    crime_map = {}
    for feat in data['features']:
        town = feat['properties']['town']
        count = feat['properties']['count']
        breakdown = feat['properties'].get('breakdown', '')
        crime_map[town] = {'count': count, 'breakdown': breakdown}

    return crime_map


def normalize_town_name(name):
    """町丁目名を正規化（漢数字→アラビア数字の差異を吸収）"""
    replacements = {
        '一丁目': '１丁目', '二丁目': '２丁目', '三丁目': '３丁目',
        '四丁目': '４丁目', '五丁目': '５丁目', '六丁目': '６丁目',
        '七丁目': '７丁目', '八丁目': '８丁目', '九丁目': '９丁目',
        '十丁目': '１０丁目'
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name


def process():
    base = Path(__file__).parent.parent
    shp_path = base / 'data' / 'raw' / 'aoba_boundary' / 'r2ka14117'
    crime_path = base / 'site' / 'data' / 'crime.geojson'
    crime_out = base / 'site' / 'data' / 'crime_map.geojson'
    pop_out = base / 'site' / 'data' / 'population.geojson'

    crime_data = load_crime_data(crime_path) if crime_path.exists() else {}

    sf = shapefile.Reader(str(shp_path), encoding='cp932')
    fields = [f[0] for f in sf.fields[1:]]

    crime_features = []
    pop_features = []
    matched = 0

    for shape_rec in sf.iterShapeRecords():
        rec = dict(zip(fields, shape_rec.record))
        geom = shape_rec.shape.__geo_interface__

        town_name = rec.get('S_NAME', '')
        population = rec.get('JINKO', 0)
        households = rec.get('SETAI', 0)

        if not town_name:
            continue

        crime_count = 0
        crime_breakdown = ''
        if town_name in crime_data:
            crime_count = crime_data[town_name]['count']
            crime_breakdown = crime_data[town_name]['breakdown']
            matched += 1
        else:
            norm = normalize_town_name(town_name)
            for k, v in crime_data.items():
                if normalize_town_name(k) == norm or k in town_name or town_name in k:
                    crime_count = v['count']
                    crime_breakdown = v['breakdown']
                    matched += 1
                    break

        crime_features.append({
            'type': 'Feature',
            'geometry': geom,
            'properties': {
                'name': f'横浜市青葉区{town_name}',
                'town': town_name,
                'count': crime_count,
                'breakdown': crime_breakdown
            }
        })

        pop_features.append({
            'type': 'Feature',
            'geometry': geom,
            'properties': {
                'name': f'横浜市青葉区{town_name}',
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

    print(f'犯罪マップ: {len(crime_features)}エリア, {matched}件マッチ → {crime_out.name}')
    print(f'人口マップ: {len(pop_features)}エリア → {pop_out.name}')


if __name__ == '__main__':
    process()
