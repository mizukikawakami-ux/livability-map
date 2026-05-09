"""
犯罪統計データ処理スクリプト
ソース: 神奈川県警オープンデータ
町丁目ごとに犯罪件数を集計し、GeoJSONとして出力
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

CRIME_FILES = [
    'kanagawa_2024zitensyatou.csv',
    'kanagawa_2024hittakuri.csv',
    'kanagawa_2024syazyounerai.csv',
    'kanagawa_2024buhinnerai.csv',
    'kanagawa_2024zidouhanbaikinerai.csv',
    'kanagawa_2024zidousyatou.csv',
    'kanagawa_2024ootobaitou.csv',
]


def process():
    base = Path(__file__).parent.parent
    raw_dir = base / 'data' / 'raw'
    dst = base / 'site' / 'data' / 'crime.geojson'

    town_counts = defaultdict(lambda: defaultdict(int))

    for filename in CRIME_FILES:
        filepath = raw_dir / filename
        if not filepath.exists():
            print(f'スキップ: {filename} (ファイルなし)')
            continue

        for encoding in ['utf-8-sig', 'utf-8', 'cp932']:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        city = row.get('市区町村（発生地）', '')
                        if '青葉区' not in city:
                            continue
                        town = row.get('町丁目（発生地）', '')
                        crime_type = row.get('手口', row.get('罪名', ''))
                        if town:
                            town_counts[town]['total'] += 1
                            town_counts[town][crime_type] += 1
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

    features = []
    for town, counts in sorted(town_counts.items()):
        breakdown = {k: v for k, v in counts.items() if k != 'total'}
        breakdown_str = ', '.join(f'{k}:{v}' for k, v in breakdown.items())

        features.append({
            'type': 'Feature',
            'geometry': None,
            'properties': {
                'name': f'横浜市青葉区{town}',
                'town': town,
                'count': counts['total'],
                'breakdown': breakdown_str
            }
        })

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total_crimes = sum(c['total'] for c in town_counts.values())
    print(f'処理完了: 青葉区 {len(town_counts)}町丁目, 合計{total_crimes}件')

    top5 = sorted(town_counts.items(), key=lambda x: x[1]['total'], reverse=True)[:5]
    for town, counts in top5:
        print(f'  {town}: {counts["total"]}件')


if __name__ == '__main__':
    process()
