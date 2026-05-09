"""
交通事故データ処理スクリプト
ソース: 警察庁オープンデータ (https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html)

警察庁CSVの緯度経度は度分秒ミリ秒形式（例: 354081234 = 35度40分81.234秒ではなく、35度40分8秒1234）
正確には: 上2-3桁=度, 次2桁=分, 次2桁=秒, 残り=小数点以下
緯度: 9桁固定 (DD MM SS mmm) → 2桁度 + 2桁分 + 2桁秒 + 3桁ミリ秒
経度: 10桁固定 (DDD MM SS mmm) → 3桁度 + 2桁分 + 2桁秒 + 3桁ミリ秒
"""

import csv
import json
import sys
import os
from pathlib import Path

AOBA_KU_BOUNDS = {
    'lat_min': 35.53,
    'lat_max': 35.59,
    'lon_min': 139.48,
    'lon_max': 139.55
}

WEATHER_MAP = {
    '1': '晴', '2': '曇', '3': '雨', '4': '霧', '5': '雪'
}

ACCIDENT_TYPE_MAP = {
    '01': '人対車両', '21': '車両相互', '41': '車両単独', '61': '列車'
}

SEVERITY_MAP = {
    '1': '死亡', '2': '負傷'
}


def parse_lat(raw):
    """9桁固定の緯度文字列を10進数に変換"""
    if not raw or len(raw) < 7:
        return None
    raw = raw.strip().zfill(9)
    degrees = int(raw[0:2])
    minutes = int(raw[2:4])
    seconds = int(raw[4:6])
    milliseconds = int(raw[6:9])
    return degrees + minutes / 60 + (seconds + milliseconds / 1000) / 3600


def parse_lon(raw):
    """10桁固定の経度文字列を10進数に変換"""
    if not raw or len(raw) < 8:
        return None
    raw = raw.strip().zfill(10)
    degrees = int(raw[0:3])
    minutes = int(raw[3:5])
    seconds = int(raw[5:7])
    milliseconds = int(raw[7:10])
    return degrees + minutes / 60 + (seconds + milliseconds / 1000) / 3600


def is_in_aoba(lat, lon):
    """青葉区の範囲内かチェック"""
    return (AOBA_KU_BOUNDS['lat_min'] <= lat <= AOBA_KU_BOUNDS['lat_max'] and
            AOBA_KU_BOUNDS['lon_min'] <= lon <= AOBA_KU_BOUNDS['lon_max'])


def process_accident_csv(input_path, output_path):
    """警察庁交通事故CSVをGeoJSONに変換（青葉区のみ抽出）"""
    features = []

    encodings = ['cp932', 'utf-8-sig', 'utf-8', 'shift_jis']

    for encoding in encodings:
        try:
            with open(input_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                print(f"Encoding: {encoding}")
                print(f"Columns: {fieldnames[:10]}")

                for row in reader:
                    pref_code = row.get('都道府県コード', '')
                    if pref_code.strip() != '45':
                        continue

                    lat_raw = row.get('地点　緯度（北緯）', '')
                    lon_raw = row.get('地点　経度（東経）', '')

                    lat = parse_lat(lat_raw)
                    lon = parse_lon(lon_raw)

                    if lat is None or lon is None:
                        continue

                    if not is_in_aoba(lat, lon):
                        continue

                    year = row.get('発生日時　　年', '')
                    month = row.get('発生日時　　月', '')
                    day = row.get('発生日時　　日', '')
                    date_str = f"{year}/{month}/{day}" if year else '不明'

                    weather_code = row.get('天候', '')
                    weather = WEATHER_MAP.get(weather_code.strip(), '不明')

                    type_code = row.get('事故類型', '').strip()
                    accident_type = ACCIDENT_TYPE_MAP.get(type_code, '不明')

                    severity_code = row.get('事故内容', '').strip()
                    severity = SEVERITY_MAP.get(severity_code, '')

                    feature = {
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [lon, lat]
                        },
                        'properties': {
                            'date': date_str,
                            'weather': weather,
                            'type': accident_type,
                            'severity': severity
                        }
                    }
                    features.append(feature)

                break
        except (UnicodeDecodeError, UnicodeError):
            continue

    geojson = {
        'type': 'FeatureCollection',
        'features': features
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"処理完了: {len(features)}件の事故データを青葉区から抽出")
    return len(features)


if __name__ == '__main__':
    base_dir = Path(__file__).parent.parent
    raw_dir = base_dir / 'data' / 'raw'
    output_path = base_dir / 'site' / 'data' / 'accidents.geojson'

    csv_files = list(raw_dir.glob('*honhyo*.csv')) + list(raw_dir.glob('*accident*.csv'))

    if not csv_files:
        print("交通事故CSVファイルが見つかりません。")
        print(f"以下のディレクトリにCSVを配置してください: {raw_dir}")
        print()
        print("ダウンロード元:")
        print("https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html")
        print()
        print("「本票」のCSVファイルをダウンロードしてください。")
        sys.exit(1)

    total = 0
    for csv_file in csv_files:
        print(f"処理中: {csv_file.name}")
        total += process_accident_csv(str(csv_file), str(output_path))

    print(f"\n合計: {total}件 → {output_path}")
