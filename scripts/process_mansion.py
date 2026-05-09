"""
建設中・建設予定マンション情報
ソース: PRTIMESプレスリリース、デベロッパー公式サイト、横浜市開発届出
ジオコーディング: 国土地理院 住所検索API
"""

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

MANSION_DATA = [
    {
        "name": "プロミライズ青葉台",
        "address": "横浜市青葉区桜台25-1",
        "developer": "横浜市住宅供給公社",
        "units": 761,
        "floors": "複数棟（5棟構成）",
        "status": "建設中（一部竣工済み）",
        "completion": "2025年9月～2026年5月",
    },
    {
        "name": "ドレッセたまプラーザ プレイス",
        "address": "横浜市青葉区美しが丘5-1",
        "developer": "東急",
        "units": 67,
        "floors": "地上6階",
        "status": "建設中",
        "completion": "2026年2月",
    },
    {
        "name": "シエリアあざみ野",
        "address": "横浜市青葉区新石川1-14",
        "developer": "関電不動産開発・日鉄興和不動産",
        "units": 145,
        "floors": "地上8階",
        "status": "建設中",
        "completion": "2026年7月",
    },
    {
        "name": "プラウド美しが丘ヒルサイド",
        "address": "横浜市青葉区美しが丘5-29",
        "developer": "野村不動産",
        "units": 37,
        "floors": "地上4階・地下1階",
        "status": "竣工済み（販売中）",
        "completion": "2025年10月",
    },
    {
        "name": "ブリシア青葉台テラス",
        "address": "横浜市青葉区しらとり台3",
        "developer": "国際総合計画・ブリス",
        "units": 68,
        "floors": "地上5階・地下1階",
        "status": "建設中",
        "completion": "2026年4月",
    },
    {
        "name": "デュオセーヌ横浜青葉台",
        "address": "横浜市青葉区たちばな台1-14",
        "developer": "（シニア向け分譲）",
        "units": 71,
        "floors": "地上5階",
        "status": "建設中",
        "completion": "2026年1月",
    },
    {
        "name": "ドルフィーノ青葉藤が丘",
        "address": "横浜市青葉区藤が丘2-36",
        "developer": "タクトホーム",
        "units": 24,
        "floors": "地上5階",
        "status": "建設中",
        "completion": "2025年9月",
    },
    {
        "name": "ヴァースクレイシアIDZたまプラーザ",
        "address": "横浜市青葉区新石川3-4",
        "developer": "プロパティエージェント",
        "units": 28,
        "floors": "地上7階",
        "status": "建設中",
        "completion": "2025年8月",
    },
    {
        "name": "ドレッセたまプラーザ ラベニュー",
        "address": "横浜市青葉区新石川4",
        "developer": "東急",
        "units": 34,
        "floors": "不明",
        "status": "建設予定",
        "completion": "2027年3月",
    },
    {
        "name": "パークホームズ市が尾 ブライトアベニュー",
        "address": "横浜市青葉区荏田西4-3",
        "developer": "三井不動産レジデンシャル",
        "units": 148,
        "floors": "地上5階",
        "status": "建設予定",
        "completion": "2027年1月",
    },
    {
        "name": "パレステージ横浜田奈",
        "address": "横浜市青葉区田奈町43",
        "developer": "日神不動産",
        "units": 59,
        "floors": "地上6階",
        "status": "建設中",
        "completion": "2027年3月",
    },
]


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
    dst = base / 'site' / 'data' / 'mansion.geojson'

    features = []

    for m in MANSION_DATA:
        lon, lat = geocode(m['address'])
        if lon is None:
            parts = m['address'].rsplit('-', 1)
            if len(parts) > 1:
                lon, lat = geocode(parts[0])

        if lon is None:
            print(f'座標が見つかりません: {m["name"]} ({m["address"]})')
            continue

        print(f'  {m["name"]}: [{lon}, {lat}]')

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [lon, lat]
            },
            'properties': {
                'name': m['name'],
                'status': m['status'],
                'completion': m['completion'],
                'scale': f'{m["units"]}戸 / {m["floors"]}',
                'developer': m['developer']
            }
        })
        time.sleep(0.2)

    out = {'type': 'FeatureCollection', 'features': features}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'処理完了: {len(features)}件のマンション情報')


if __name__ == '__main__':
    process()
