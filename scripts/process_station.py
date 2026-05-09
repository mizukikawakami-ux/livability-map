"""
駅データ処理スクリプト
ソース: 国土数値情報 S12（駅別乗降客数）
全国データから神奈川県＋近隣エリアの駅を抽出し、GeoJSONとして出力
"""

import json
import shapefile
from pathlib import Path

BASE = Path(__file__).parent.parent

# 神奈川県＋通勤圏の駅を含む範囲（少し広めに取る）
BOUNDS = {
    'lon_min': 138.9,
    'lon_max': 139.85,
    'lat_min': 35.05,
    'lat_max': 35.75,
}


def process():
    src = BASE / 'data' / 'raw' / 'S12_station' / 'S12-20_GML' / 'S12-20_NumberOfPassengers'
    dst = BASE / 'site' / 'data' / 'station.geojson'

    sf = shapefile.Reader(str(src), encoding='cp932')
    fields = sf.fields[1:]

    # S12 は POLYLINE（路線区間）で、始点が当該駅の位置
    # 同一駅名でも路線ごとに異なるレコードが存在するため、
    # 駅名＋座標でユニーク化する
    stations = {}
    total = 0

    for rec, shp in zip(sf.iterRecords(), sf.iterShapes()):
        pts = shp.points
        if not pts:
            continue

        lon, lat = pts[0]
        if not (BOUNDS['lon_min'] <= lon <= BOUNDS['lon_max'] and
                BOUNDS['lat_min'] <= lat <= BOUNDS['lat_max']):
            continue

        name = rec[0]       # S12_001: 駅名
        company = rec[1]    # S12_002: 運営会社
        line = rec[2]       # S12_003: 路線名

        # 乗降客数: 4フィールドごとのグループ、最後のグループが最新年
        # S12_004以降: [年度コード, 乗車人員, 降車/種別, 備考] × n年
        # 最新の乗降客数を取得（最後の数値グループ）
        passengers = 0
        for i in range(len(fields) - 1, 3, -1):
            val = rec[i]
            if isinstance(val, (int, float)) and val > 100:
                passengers = int(val)
                break

        # 同一駅名＋会社で重複排除（路線は併記）
        key = f'{name}_{company}'
        rkey = f'{round(lon, 3)}_{round(lat, 3)}'
        station_key = f'{key}_{rkey}'

        if station_key not in stations:
            stations[station_key] = {
                'name': name,
                'company': company,
                'line': line,
                'passengers': passengers,
                'lon': lon,
                'lat': lat,
            }
        else:
            # 同一駅の別路線 → 路線名を追記、乗降客数は大きい方
            existing = stations[station_key]
            if line not in existing['line']:
                existing['line'] += f'・{line}'
            if passengers > existing['passengers']:
                existing['passengers'] = passengers

        total += 1

    # GeoJSON出力
    features = []
    for s in stations.values():
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [s['lon'], s['lat']]
            },
            'properties': {
                'name': s['name'],
                'company': s['company'],
                'line': s['line'],
                'passengers': s['passengers'],
            }
        })

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'処理完了: {len(features)}駅を抽出 (元データ: {total}レコード)')


if __name__ == '__main__':
    process()
