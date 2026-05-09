"""
神奈川県全域 住みやすさデータ統合・ページ生成パイプライン

1. 境界データ（e-Stat小地域）を読み込み
2. 各データレイヤーを空間結合（ポイントinポリゴン）
3. パーセンタイルベース7軸スコアリング
4. 階層的ページ生成（県 → 市区町村 → 町丁目）
"""

import json
import math
import re
import csv
import shapefile
from pathlib import Path
from html import escape
from collections import Counter

BASE = Path(__file__).parent.parent
SITE = BASE / 'site'
DATA = SITE / 'data'

# ====== 1. 境界データ読み込み ======

def load_boundaries():
    """e-Stat小地域境界データを読み込み、町丁目ごとの情報を返す"""
    src = BASE / 'data' / 'raw' / 'kanagawa_boundary' / 'r2ka14'
    sf = shapefile.Reader(str(src), encoding='cp932')

    towns = {}
    for rec, shp in zip(sf.iterRecords(), sf.iterShapes()):
        key_code = rec[0]     # KEY_CODE
        if len(key_code) < 5:
            continue  # 県レベルをスキップ

        muni_code = key_code[:5]
        pref_name = rec[4]    # PREF_NAME
        city_name = rec[5]    # CITY_NAME
        town_name = rec[6]    # S_NAME
        population = rec[24]  # JINKO
        households = rec[25]  # SETAI

        if not town_name or town_name.strip() == '':
            continue

        # ユニークキー: 市区町村コード + 小地域コード
        s_area = rec[3]  # S_AREA
        town_key = f'{muni_code}_{s_area}'

        # ポリゴン座標を抽出
        geom_type = 'Polygon'
        if shp.shapeTypeName == 'POLYGON':
            coords = [list(shp.points)]
            if hasattr(shp, 'parts') and len(shp.parts) > 1:
                geom_type = 'MultiPolygon'
                parts = list(shp.parts) + [len(shp.points)]
                coords = [[list(shp.points[parts[i]:parts[i+1]])] for i in range(len(parts)-1)]
        else:
            coords = [list(shp.points)]

        # バウンディングボックス（高速フィルタ用）
        lons = [p[0] for p in shp.points]
        lats = [p[1] for p in shp.points]
        bbox = (min(lons), min(lats), max(lons), max(lats))

        if town_key in towns:
            # 同一コードで複数ポリゴン → MultiPolygonにマージ
            existing = towns[town_key]
            if existing['geom_type'] == 'Polygon':
                existing['geom_type'] = 'MultiPolygon'
                existing['coords'] = [existing['coords']]
            existing['coords'].append(coords if geom_type == 'Polygon' else coords[0])
            existing['bbox'] = (
                min(existing['bbox'][0], bbox[0]),
                min(existing['bbox'][1], bbox[1]),
                max(existing['bbox'][2], bbox[2]),
                max(existing['bbox'][3], bbox[3]),
            )
            existing['population'] += population or 0
            existing['households'] += households or 0
        else:
            towns[town_key] = {
                'key': town_key,
                'muni_code': muni_code,
                'city_name': city_name,
                'town_name': town_name,
                'display_name': f'{city_name}{town_name}',
                'population': population or 0,
                'households': households or 0,
                'geom_type': geom_type,
                'coords': coords,
                'bbox': bbox,
                # データ集約用
                'crime_count': 0,
                'crime_breakdown': {},
                'accident_count': 0,
                'landprices': [],
                'medical': [],
                'nurseries': [],
                'stations': [],
                'parks': [],
                'mansions': [],
            }

    return towns


# ====== 2. ポイントinポリゴン（空間結合） ======

def point_in_polygon(px, py, polygon):
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_town(lon, lat, town):
    bbox = town['bbox']
    if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
        return False

    if town['geom_type'] == 'Polygon':
        return point_in_polygon(lon, lat, town['coords'][0])
    else:  # MultiPolygon
        for poly in town['coords']:
            ring = poly[0] if isinstance(poly[0][0], (list, tuple)) else poly
            if point_in_polygon(lon, lat, ring):
                return True
    return False


class SpatialIndex:
    """グリッドベースの空間インデックス（高速化用）"""
    def __init__(self, towns, cell_size=0.01):
        self.cell_size = cell_size
        self.grid = {}
        for town in towns.values():
            bbox = town['bbox']
            x0 = int(bbox[0] / cell_size)
            y0 = int(bbox[1] / cell_size)
            x1 = int(bbox[2] / cell_size) + 1
            y1 = int(bbox[3] / cell_size) + 1
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    key = (x, y)
                    if key not in self.grid:
                        self.grid[key] = []
                    self.grid[key].append(town)

    def find(self, lon, lat):
        key = (int(lon / self.cell_size), int(lat / self.cell_size))
        candidates = self.grid.get(key, [])
        for town in candidates:
            if point_in_town(lon, lat, town):
                return town
        return None


_spatial_index = None

def get_spatial_index(towns):
    global _spatial_index
    if _spatial_index is None:
        _spatial_index = SpatialIndex(towns)
    return _spatial_index


def spatial_join_points(towns, geojson_path, extract_fn):
    """GeoJSONのポイントデータを町丁目に空間結合（グリッドインデックス利用）"""
    if not geojson_path.exists():
        print(f'  スキップ: {geojson_path.name} が見つかりません')
        return 0

    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    idx = get_spatial_index(towns)
    matched = 0

    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        town = idx.find(lon, lat)
        if town:
            extract_fn(town, feat)
            matched += 1

    return matched


# ====== 3. 犯罪データ ======

def normalize_town_name(name):
    """町丁目名を正規化（全角数字・漢数字 → 半角数字）"""
    # 全角数字 → 半角数字
    result = ''
    for ch in name:
        cp = ord(ch)
        if 0xFF10 <= cp <= 0xFF19:
            result += chr(cp - 0xFF10 + 0x30)
        else:
            result += ch
    # 漢数字丁目 → 数字
    kanji_map = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
                 '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
    for kanji, digit in kanji_map.items():
        result = result.replace(f'{kanji}丁目', f'{digit}丁目')
    return result


def load_crime_data(towns):
    """神奈川県警の犯罪CSVを読み込み（個別事件形式）"""
    crime_dir = BASE / 'data' / 'raw'
    crime_files = {
        'zitensyatou': '自転車盗',
        'zidousyatou': '自動車盗',
        'ootobaitou': 'オートバイ盗',
        'hittakuri': 'ひったくり',
        'syazyounerai': '車上ねらい',
        'buhinnerai': '部品ねらい',
        'zidouhanbaikinerai': '自動販売機ねらい',
    }

    # 正規化した町名でルックアップテーブルを構築
    town_by_name = {}
    for key, town in towns.items():
        norm = normalize_town_name(town['town_name'])
        name_key = f'{town["city_name"]}_{norm}'
        if name_key not in town_by_name:
            town_by_name[name_key] = town

    total_matched = 0
    total_unmatched = 0

    for file_key, crime_type in crime_files.items():
        csv_path = crime_dir / f'kanagawa_2024{file_key}.csv'
        if not csv_path.exists():
            continue

        file_matched = 0
        for enc in ['cp932', 'utf-8-sig', 'utf-8']:
            try:
                with open(csv_path, 'r', encoding=enc) as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    # CSV形式: 各行が1件の犯罪事件
                    # col[6] = 市区町村（発生地）, col[7] = 町丁目（発生地）
                    for row in reader:
                        if len(row) < 8:
                            continue
                        city = row[6].strip()
                        town_name_raw = row[7].strip()

                        if not city or not town_name_raw:
                            continue

                        norm = normalize_town_name(town_name_raw)
                        name_key = f'{city}_{norm}'

                        if name_key in town_by_name:
                            t = town_by_name[name_key]
                            t['crime_count'] += 1
                            t['crime_breakdown'][crime_type] = t['crime_breakdown'].get(crime_type, 0) + 1
                            file_matched += 1
                        else:
                            total_unmatched += 1
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        total_matched += file_matched

    if total_unmatched > 0:
        print(f'  (未マッチ: {total_unmatched}件)')
    return total_matched


# ====== 4. 交通事故データ ======

def load_accident_data(towns):
    """警察庁の交通事故CSVを読み込み、座標ベースで結合"""
    csv_path = BASE / 'data' / 'raw' / 'honhyo_2024.csv'
    if not csv_path.exists():
        print('  交通事故CSVが見つかりません')
        return 0

    PREF_CODE = '45'  # 神奈川県の警察庁コード（JISコード14とは異なる）
    # CSV列: [0]資料区分, [1]都道府県コード, ..., [60]緯度, [61]経度

    def parse_coord(val, is_lon=False):
        s = str(val).strip()
        if not s or s == '':
            return None
        try:
            if is_lon:
                d = int(s[:3])
                m = int(s[3:5])
                sec = int(s[5:7])
                ms = int(s[7:10]) if len(s) >= 10 else 0
                return d + m/60 + (sec + ms/1000)/3600
            else:
                d = int(s[:2])
                m = int(s[2:4])
                sec = int(s[4:6])
                ms = int(s[6:9]) if len(s) >= 9 else 0
                return d + m/60 + (sec + ms/1000)/3600
        except (ValueError, IndexError):
            return None

    idx = get_spatial_index(towns)
    total = 0
    skipped = 0

    for enc in ['cp932', 'utf-8-sig', 'utf-8']:
        try:
            with open(csv_path, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                header = next(reader)
                for row in reader:
                    if len(row) < 62:
                        continue
                    if row[1].strip() != PREF_CODE:
                        continue

                    lat = parse_coord(row[60], is_lon=False)
                    lon = parse_coord(row[61], is_lon=True)
                    if lat is None or lon is None:
                        skipped += 1
                        continue

                    town = idx.find(lon, lat)
                    if town:
                        town['accident_count'] += 1
                        total += 1
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if skipped > 0:
        print(f'  (座標なしスキップ: {skipped}件)')
    return total


# ====== 5. 最短駅距離の計算 ======

def haversine(lon1, lat1, lon2, lat2):
    """2点間の距離をkm単位で計算"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def calc_nearest_station(towns):
    """各町丁目の重心から最寄り駅までの距離を計算"""
    stations_path = DATA / 'station.geojson'
    if not stations_path.exists():
        return

    with open(stations_path, 'r', encoding='utf-8') as f:
        station_data = json.load(f)

    station_points = []
    for feat in station_data['features']:
        coords = feat['geometry']['coordinates']
        station_points.append({
            'lon': coords[0],
            'lat': coords[1],
            'name': feat['properties']['name'],
            'passengers': feat['properties'].get('passengers', 0),
        })

    for town in towns.values():
        # 重心を計算
        bbox = town['bbox']
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2

        min_dist = float('inf')
        nearest = None
        for s in station_points:
            d = haversine(cx, cy, s['lon'], s['lat'])
            if d < min_dist:
                min_dist = d
                nearest = s

        town['nearest_station_dist'] = round(min_dist, 2)
        town['nearest_station_name'] = nearest['name'] if nearest else ''


# ====== 6. 公園面積集計 ======

def calc_park_area(towns):
    """各町丁目内の公園面積を集計"""
    parks_path = DATA / 'park.geojson'
    if not parks_path.exists():
        return

    def extract(town, feat):
        town['parks'].append(feat['properties'])

    matched = spatial_join_points(towns, parks_path, extract)
    print(f'  公園: {matched}件マッチ')


# ====== 7. パーセンタイルベーススコアリング ======

def percentile_rank(values):
    """値リストに対してパーセンタイル順位（0-100）を付与"""
    if not values:
        return []
    sorted_vals = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0] * len(values)
    n = len(values)
    for rank_idx, (orig_idx, _) in enumerate(sorted_vals):
        ranks[orig_idx] = rank_idx / max(1, n - 1) * 100
    return ranks


def calculate_scores(towns):
    """7軸パーセンタイルスコアリング"""
    town_list = [t for t in towns.values() if t['population'] > 0]
    if not town_list:
        return

    # 各軸の生データを収集
    raw = {
        'safety': [],      # 犯罪率（1000人あたり）→ 低いほど良い
        'traffic': [],     # 事故率（1000人あたり）→ 低いほど良い
        'medical': [],     # 医療施設密度（1000人あたり）→ 高いほど良い
        'childcare': [],   # 保育施設密度（1000人あたり）→ 高いほど良い
        'cost': [],        # 地価（円/m2）→ 低いほど良い
        'transit': [],     # 最寄り駅距離（km）→ 近いほど良い
        'green': [],       # 公園面積率（m2/人）→ 高いほど良い
    }

    for t in town_list:
        pop = max(t['population'], 1)
        raw['safety'].append(t['crime_count'] / pop * 1000)
        raw['traffic'].append(t['accident_count'] / pop * 1000)
        raw['medical'].append(len(t['medical']) / pop * 1000)
        raw['childcare'].append(len(t['nurseries']) / pop * 1000)

        prices = [lp.get('price', 0) for lp in t['landprices'] if lp.get('price')]
        raw['cost'].append(sum(prices) / len(prices) if prices else 0)

        raw['transit'].append(t.get('nearest_station_dist', 99))

        park_area = sum(p.get('area_m2', 0) for p in t['parks'])
        raw['green'].append(park_area / pop)

    # パーセンタイル順位を計算
    percentiles = {}
    for axis, values in raw.items():
        percentiles[axis] = percentile_rank(values)

    # スコア変換（各軸0-100の14点ずつ → 合計100点）
    # 反転軸: safety, traffic, cost, transit（低い値ほど高スコア）
    inverted = {'safety', 'traffic', 'cost', 'transit'}

    for i, t in enumerate(town_list):
        t['scores'] = {}
        t['raw_scores'] = {}
        for axis in raw:
            pct = percentiles[axis][i]
            if axis in inverted:
                pct = 100 - pct  # 反転
            # 0-100パーセンタイルを0-14点に変換（7軸×14≒100点）
            score = round(pct / 100 * 14, 1)
            t['scores'][axis] = score
            t['raw_scores'][axis] = raw[axis][i]

        t['total_score'] = round(sum(t['scores'].values()), 1)


# ====== 8. 市区町村レベル集約 ======

def aggregate_municipalities(towns):
    """町丁目データを市区町村レベルで集約"""
    munis = {}
    for t in towns.values():
        code = t['muni_code']
        if code not in munis:
            munis[code] = {
                'code': code,
                'name': t['city_name'],
                'population': 0,
                'households': 0,
                'crime_count': 0,
                'accident_count': 0,
                'medical_count': 0,
                'nursery_count': 0,
                'station_count': 0,
                'park_count': 0,
                'park_area': 0,
                'town_scores': [],
                'towns': [],
            }
        m = munis[code]
        m['population'] += t['population']
        m['households'] += t['households']
        m['crime_count'] += t['crime_count']
        m['accident_count'] += t['accident_count']
        m['medical_count'] += len(t['medical'])
        m['nursery_count'] += len(t['nurseries'])
        m['park_count'] += len(t['parks'])
        m['park_area'] += sum(p.get('area_m2', 0) for p in t['parks'])
        if t.get('total_score') is not None:
            m['town_scores'].append(t['total_score'])
        m['towns'].append(t)

    # 市区町村の平均スコア
    for m in munis.values():
        scores = m['town_scores']
        m['avg_score'] = round(sum(scores) / len(scores), 1) if scores else 0
        m['max_score'] = round(max(scores), 1) if scores else 0
        m['min_score'] = round(min(scores), 1) if scores else 0

    return munis


# ====== 9. ページ生成 ======

SCORE_LABELS = {
    'safety': '治安',
    'traffic': '交通安全',
    'medical': '医療充実度',
    'childcare': '子育て環境',
    'cost': 'コスト',
    'transit': '交通利便性',
    'green': '公園・自然',
}


def town_slug(display_name):
    """表示名からURLスラグを生成"""
    slug = display_name
    # 市区町村名を除去（最後の区・市・町・村以降を保持）
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'[０-９]', lambda m: str(ord(m.group()) - 0xFF10), slug)
    slug = re.sub(r'[一二三四五六七八九十]丁目', lambda m: {
        '一丁目': '1', '二丁目': '2', '三丁目': '3', '四丁目': '4',
        '五丁目': '5', '六丁目': '6', '七丁目': '7', '八丁目': '8',
        '九丁目': '9', '十丁目': '10'
    }.get(m.group(), m.group()), slug)
    return slug


def muni_slug(name):
    """市区町村名からスラグを生成"""
    return name.replace('横浜市', 'yokohama-').replace('川崎市', 'kawasaki-').replace('相模原市', 'sagamihara-')


def score_color(score, max_score=14):
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.7:
        return '#2ecc71'
    elif pct >= 0.4:
        return '#f39c12'
    else:
        return '#e74c3c'


def generate_description(town):
    """町丁目のデータに基づく解説文"""
    name = town['display_name']
    pop = town['population']
    hh = town['households']
    crime = town['crime_count']
    acc = town['accident_count']
    med = len(town['medical'])
    nur = len(town['nurseries'])
    parks = town['parks']

    lines = []
    lines.append(f'{name}は、人口{pop:,}人・{hh:,}世帯が暮らすエリアです。')

    if crime == 0:
        lines.append('2024年の犯罪統計では犯罪の報告がなく、治安の良いエリアといえます。')
    elif crime <= 3:
        lines.append(f'2024年の犯罪件数は{crime}件と少なく、比較的安全なエリアです。')
    elif crime <= 10:
        lines.append(f'2024年の犯罪件数は{crime}件です。')
    else:
        lines.append(f'2024年の犯罪件数は{crime}件とやや多めです。')

    if acc == 0:
        lines.append('交通事故の報告はありません。')
    elif acc <= 5:
        lines.append(f'交通事故は{acc}件と少なめです。')
    else:
        lines.append(f'交通事故は{acc}件発生しています。')

    if med > 0:
        lines.append(f'医療施設は{med}件あります。')

    if nur > 0:
        lines.append(f'保育施設は{nur}か所あり、子育て環境が整っています。')

    dist = town.get('nearest_station_dist', None)
    stn = town.get('nearest_station_name', '')
    if dist is not None and stn:
        if dist < 0.5:
            lines.append(f'最寄りの{stn}駅まで約{int(dist*1000)}mと駅近エリアです。')
        elif dist < 1.0:
            lines.append(f'最寄りの{stn}駅まで約{dist:.1f}kmです。')
        else:
            lines.append(f'最寄りの{stn}駅まで約{dist:.1f}kmです。')

    if parks:
        total_area = sum(p.get('area_m2', 0) for p in parks)
        lines.append(f'公園は{len(parks)}か所（総面積{total_area:,.0f}m2）あります。')

    prices = [lp.get('price', 0) for lp in town['landprices'] if lp.get('price')]
    if prices:
        avg = int(sum(prices) / len(prices))
        lines.append(f'地価公示の平均価格は{avg:,}円/m2です。')

    return '\n'.join(lines)


def render_town_page(town, muni, all_towns_in_muni):
    """町丁目の個別ページHTML"""
    name = escape(town['display_name'])
    muni_name = escape(muni['name'])
    total = town.get('total_score', 0)
    scores = town.get('scores', {})
    description = generate_description(town)

    score_bar_html = ''
    for key, label in SCORE_LABELS.items():
        val = scores.get(key, 0)
        pct = val / 14 * 100
        color = score_color(val)
        score_bar_html += f'''
            <div class="score-row">
                <span class="score-label">{label}</span>
                <div class="score-bar-bg"><div class="score-bar-fill" style="width:{pct}%;background:{color}"></div></div>
                <span class="score-value">{val:.1f}/14</span>
            </div>'''

    facilities_html = ''
    if town['medical']:
        facilities_html += '<h3>医療施設</h3><ul>'
        for m in town['medical'][:10]:
            facilities_html += f'<li>{escape(str(m.get("name", "")))}<span class="facility-type">{escape(str(m.get("type", "")))}</span></li>'
        if len(town['medical']) > 10:
            facilities_html += f'<li>...他{len(town["medical"]) - 10}件</li>'
        facilities_html += '</ul>'

    if town['nurseries']:
        facilities_html += '<h3>保育施設</h3><ul>'
        for n in town['nurseries'][:10]:
            cap = n.get('capacity', 0)
            facilities_html += f'<li>{escape(str(n.get("name", "")))}<span class="facility-type">定員{cap}人</span></li>'
        facilities_html += '</ul>'

    if town['parks']:
        facilities_html += '<h3>公園</h3><ul>'
        for p in sorted(town['parks'], key=lambda x: -(x.get('area_m2', 0)))[:10]:
            area = p.get('area_m2', 0)
            facilities_html += f'<li>{escape(str(p.get("name", "")))}<span class="facility-type">{area:,.0f}m2</span></li>'
        if len(town['parks']) > 10:
            facilities_html += f'<li>...他{len(town["parks"]) - 10}件</li>'
        facilities_html += '</ul>'

    # 同じ市区町村の他エリアリンク
    neighbor_links = []
    for t in sorted(all_towns_in_muni, key=lambda x: x['display_name']):
        if t['key'] != town['key'] and t['population'] > 0:
            tslug = town_slug(t['town_name'])
            short = escape(t['town_name'])
            neighbor_links.append(f'<a href="../{tslug}/">{short}</a>')

    nearby_html = ' / '.join(neighbor_links[:30])
    if len(neighbor_links) > 30:
        nearby_html += f' <a href="../">...全{len(neighbor_links)}エリア</a>'

    muni_s = muni_slug(muni['name'])

    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Place",
        "name": town['display_name'],
        "address": {
            "@type": "PostalAddress",
            "addressLocality": muni['name'],
            "addressRegion": "神奈川県",
            "addressCountry": "JP"
        },
        "description": description[:200]
    }, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}の住みやすさ - 神奈川県住みやすさマップ</title>
<meta name="description" content="{escape(description[:160])}">
<script type="application/ld+json">{jsonld}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;background:#f8f9fa;color:#333;line-height:1.7}}
.header{{background:#1a1a2e;color:#fff;padding:16px 24px}}
.header h1{{font-size:1.1rem}}.header a{{color:#8ab4f8;text-decoration:none}}
.container{{max-width:800px;margin:0 auto;padding:24px 16px}}
.breadcrumb{{font-size:.8rem;color:#666;margin-bottom:16px}}.breadcrumb a{{color:#1a73e8;text-decoration:none}}
h2{{font-size:1.5rem;margin-bottom:8px;color:#1a1a2e}}
.total-score{{font-size:2.5rem;font-weight:700;color:#1a1a2e;margin:16px 0}}.total-score span{{font-size:1rem;color:#666;font-weight:400}}
.description{{background:#fff;border-radius:8px;padding:20px;margin:20px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.description p{{margin-bottom:8px}}
.scores{{background:#fff;border-radius:8px;padding:20px;margin:20px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.score-row{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.score-label{{width:90px;font-size:.85rem;font-weight:600;color:#555}}
.score-bar-bg{{flex:1;height:20px;background:#eee;border-radius:10px;overflow:hidden}}
.score-bar-fill{{height:100%;border-radius:10px;transition:width .5s}}
.score-value{{width:60px;text-align:right;font-size:.85rem;font-weight:600}}
.data-section{{background:#fff;border-radius:8px;padding:20px;margin:20px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.data-section h3{{font-size:1rem;margin-bottom:12px;color:#1a1a2e;border-bottom:2px solid #e0e0e0;padding-bottom:6px}}
.data-section ul{{list-style:none}}.data-section li{{padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:.9rem}}
.facility-type{{color:#888;font-size:.8rem;margin-left:8px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:20px 0}}
.stat-card{{background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.stat-card .value{{font-size:1.5rem;font-weight:700;color:#1a1a2e}}.stat-card .label{{font-size:.75rem;color:#888;margin-top:4px}}
.nearby{{margin:20px 0;font-size:.8rem;color:#666;line-height:2}}.nearby a{{color:#1a73e8;text-decoration:none;margin:0 4px}}.nearby a:hover{{text-decoration:underline}}
.footer{{background:#1a1a2e;color:#aaa;padding:16px 24px;font-size:.72rem;margin-top:40px;text-align:center}}.footer a{{color:#8ab4f8;text-decoration:none}}
</style>
<script>window.va = window.va || function () {{ (window.vaq = window.vaq || []).push(arguments); }};</script>
<script defer src="/_vercel/insights/script.js"></script>
</head>
<body>
<div class="header"><h1><a href="../../../">神奈川県 住みやすさマップ</a></h1></div>
<div class="container">
<div class="breadcrumb">
<a href="../../../">トップ</a> &gt; <a href="../../">エリア一覧</a> &gt; <a href="../">{muni_name}</a> &gt; {escape(town['town_name'])}
</div>
<h2>{name}の住みやすさ</h2>
<div class="total-score">{total:.1f}<span> / 98点</span></div>
<div class="stats">
<div class="stat-card"><div class="value">{town['population']:,}</div><div class="label">人口</div></div>
<div class="stat-card"><div class="value">{town['households']:,}</div><div class="label">世帯数</div></div>
<div class="stat-card"><div class="value">{town['crime_count']}</div><div class="label">犯罪件数</div></div>
<div class="stat-card"><div class="value">{town['accident_count']}</div><div class="label">交通事故</div></div>
<div class="stat-card"><div class="value">{len(town['medical'])}</div><div class="label">医療施設</div></div>
<div class="stat-card"><div class="value">{len(town['parks'])}</div><div class="label">公園</div></div>
</div>
<div class="scores"><h3 style="font-size:1rem;margin-bottom:12px;color:#1a1a2e">住みやすさスコア</h3>{score_bar_html}</div>
<div class="description"><h3 style="font-size:1rem;margin-bottom:12px;color:#1a1a2e">エリア解説</h3>
{''.join(f'<p>{escape(line)}</p>' for line in description.split(chr(10)) if line.strip())}
</div>
<div class="data-section">{facilities_html}</div>
<div class="nearby"><strong>{muni_name}の他のエリア:</strong> {nearby_html}</div>
</div>
<div class="footer">
データ出典: 警察庁・神奈川県警・国土地理院・国土数値情報・e-Stat<br>
<a href="../../../">神奈川県 住みやすさマップ</a> | 本サイトはオープンデータに基づく参考情報です
</div>
</body></html>'''


def render_muni_page(muni, all_munis):
    """市区町村の一覧ページHTML"""
    name = escape(muni['name'])
    towns = [t for t in muni['towns'] if t['population'] > 0 and t.get('total_score') is not None]
    towns.sort(key=lambda x: -x.get('total_score', 0))

    rows = []
    for t in towns:
        tslug = town_slug(t['town_name'])
        short = escape(t['town_name'])
        score = t.get('total_score', 0)
        color = '#2ecc71' if score >= 60 else '#f39c12' if score >= 40 else '#e74c3c'
        rows.append(f'''
<a href="{tslug}/" class="town-card">
<div class="town-name">{short}</div>
<div class="town-score" style="color:{color}">{score:.1f}点</div>
<div class="town-meta">人口 {t['population']:,} / 犯罪 {t['crime_count']}件 / 医療 {len(t['medical'])}件</div>
</a>''')

    # 他の市区町村リンク
    other_munis = []
    for m in sorted(all_munis.values(), key=lambda x: -x['avg_score']):
        if m['code'] != muni['code']:
            ms = muni_slug(m['name'])
            other_munis.append(f'<a href="../{ms}/">{escape(m["name"])}</a>')

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} エリア別住みやすさ一覧 - 神奈川県住みやすさマップ</title>
<meta name="description" content="{name}の全{len(towns)}エリアの住みやすさスコアを一覧で比較。7軸パーセンタイルスコアリングで算出。">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;background:#f8f9fa;color:#333}}
.header{{background:#1a1a2e;color:#fff;padding:16px 24px}}.header h1{{font-size:1.1rem}}.header a{{color:#8ab4f8;text-decoration:none}}
.container{{max-width:1000px;margin:0 auto;padding:24px 16px}}
.breadcrumb{{font-size:.8rem;color:#666;margin-bottom:16px}}.breadcrumb a{{color:#1a73e8;text-decoration:none}}
h2{{font-size:1.4rem;margin-bottom:8px;color:#1a1a2e}}
.muni-summary{{background:#fff;border-radius:8px;padding:20px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.08);display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;text-align:center}}
.muni-summary .value{{font-size:1.3rem;font-weight:700;color:#1a1a2e}}.muni-summary .label{{font-size:.72rem;color:#888}}
.sort-controls{{margin:16px 0;display:flex;gap:8px;flex-wrap:wrap}}
.sort-btn{{padding:6px 14px;border:1px solid #ddd;border-radius:20px;background:#fff;cursor:pointer;font-size:.8rem;color:#555}}.sort-btn.active{{background:#1a1a2e;color:#fff;border-color:#1a1a2e}}
.town-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}}
.town-card{{display:block;background:#fff;border-radius:8px;padding:16px;text-decoration:none;color:#333;box-shadow:0 1px 3px rgba(0,0,0,.08);transition:box-shadow .2s}}
.town-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.15)}}
.town-name{{font-weight:700;font-size:1rem;margin-bottom:4px}}.town-score{{font-size:1.3rem;font-weight:700;margin-bottom:4px}}.town-meta{{font-size:.72rem;color:#888}}
.nearby{{margin:20px 0;font-size:.8rem;color:#666;line-height:2}}.nearby a{{color:#1a73e8;text-decoration:none;margin:0 4px}}
.footer{{background:#1a1a2e;color:#aaa;padding:16px 24px;font-size:.72rem;margin-top:40px;text-align:center}}.footer a{{color:#8ab4f8;text-decoration:none}}
</style>
<script>window.va = window.va || function () {{ (window.vaq = window.vaq || []).push(arguments); }};</script>
<script defer src="/_vercel/insights/script.js"></script>
</head>
<body>
<div class="header"><h1><a href="../../">神奈川県 住みやすさマップ</a></h1></div>
<div class="container">
<div class="breadcrumb"><a href="../../">トップ</a> &gt; <a href="../">エリア一覧</a> &gt; {name}</div>
<h2>{name} 全{len(towns)}エリアの住みやすさ</h2>
<div class="muni-summary">
<div><div class="value">{muni['population']:,}</div><div class="label">人口</div></div>
<div><div class="value">{muni['avg_score']:.1f}</div><div class="label">平均スコア</div></div>
<div><div class="value">{muni['crime_count']:,}</div><div class="label">犯罪件数</div></div>
<div><div class="value">{muni['medical_count']}</div><div class="label">医療施設</div></div>
<div><div class="value">{muni['park_count']}</div><div class="label">公園</div></div>
</div>
<div class="sort-controls">
<button class="sort-btn active" onclick="sortCards('score')">スコア順</button>
<button class="sort-btn" onclick="sortCards('name')">名前順</button>
<button class="sort-btn" onclick="sortCards('pop')">人口順</button>
<button class="sort-btn" onclick="sortCards('crime')">犯罪少ない順</button>
</div>
<div class="town-grid" id="townGrid">{''.join(rows)}</div>
<div class="nearby"><strong>他の市区町村:</strong> {" / ".join(other_munis[:20])}</div>
</div>
<div class="footer">
データ出典: 警察庁・神奈川県警・国土地理院・国土数値情報・e-Stat<br>
<a href="../../">神奈川県 住みやすさマップ</a>
</div>
<script>
function sortCards(key){{
  const grid=document.getElementById('townGrid');
  const cards=[...grid.children];
  cards.sort((a,b)=>{{
    if(key==='score')return parseFloat(b.querySelector('.town-score').textContent)-parseFloat(a.querySelector('.town-score').textContent);
    if(key==='name')return a.querySelector('.town-name').textContent.localeCompare(b.querySelector('.town-name').textContent,'ja');
    if(key==='pop'){{const g=t=>parseInt(t.querySelector('.town-meta').textContent.match(/人口 ([\\d,]+)/)?.[1]?.replace(/,/g,'')||0);return g(b)-g(a)}}
    if(key==='crime'){{const g=t=>parseInt(t.querySelector('.town-meta').textContent.match(/犯罪 (\\d+)/)?.[1]||0);return g(a)-g(b)}}
  }});
  cards.forEach(c=>grid.appendChild(c));
  document.querySelectorAll('.sort-btn').forEach(b=>b.classList.remove('active'));
  if(event&&event.target)event.target.classList.add('active');
}}
</script>
</body></html>'''


def render_area_index(munis):
    """市区町村一覧ページ"""
    rows = []
    for m in sorted(munis.values(), key=lambda x: -x['avg_score']):
        ms = muni_slug(m['name'])
        name = escape(m['name'])
        color = '#2ecc71' if m['avg_score'] >= 60 else '#f39c12' if m['avg_score'] >= 40 else '#e74c3c'
        town_count = len([t for t in m['towns'] if t['population'] > 0])
        rows.append(f'''
<a href="{ms}/" class="muni-card">
<div class="muni-name">{name}</div>
<div class="muni-score" style="color:{color}">{m['avg_score']:.1f}点</div>
<div class="muni-meta">人口 {m['population']:,} / {town_count}エリア / 犯罪 {m['crime_count']:,}件</div>
</a>''')

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>神奈川県 市区町村別住みやすさ一覧</title>
<meta name="description" content="神奈川県の全{len(munis)}市区町村の住みやすさスコアを比較。治安・交通・医療・子育て・コスト・交通利便性・公園の7軸で評価。">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;background:#f8f9fa;color:#333}}
.header{{background:#1a1a2e;color:#fff;padding:16px 24px}}.header h1{{font-size:1.1rem}}.header a{{color:#8ab4f8;text-decoration:none}}
.container{{max-width:1000px;margin:0 auto;padding:24px 16px}}
.breadcrumb{{font-size:.8rem;color:#666;margin-bottom:16px}}.breadcrumb a{{color:#1a73e8;text-decoration:none}}
h2{{font-size:1.4rem;margin-bottom:8px;color:#1a1a2e}}
.sort-controls{{margin:16px 0;display:flex;gap:8px;flex-wrap:wrap}}
.sort-btn{{padding:6px 14px;border:1px solid #ddd;border-radius:20px;background:#fff;cursor:pointer;font-size:.8rem;color:#555}}.sort-btn.active{{background:#1a1a2e;color:#fff;border-color:#1a1a2e}}
.muni-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
.muni-card{{display:block;background:#fff;border-radius:8px;padding:16px;text-decoration:none;color:#333;box-shadow:0 1px 3px rgba(0,0,0,.08);transition:box-shadow .2s}}
.muni-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.15)}}
.muni-name{{font-weight:700;font-size:1.1rem;margin-bottom:4px}}.muni-score{{font-size:1.4rem;font-weight:700;margin-bottom:4px}}.muni-meta{{font-size:.75rem;color:#888}}
.footer{{background:#1a1a2e;color:#aaa;padding:16px 24px;font-size:.72rem;margin-top:40px;text-align:center}}.footer a{{color:#8ab4f8;text-decoration:none}}
</style>
<script>window.va = window.va || function () {{ (window.vaq = window.vaq || []).push(arguments); }};</script>
<script defer src="/_vercel/insights/script.js"></script>
</head>
<body>
<div class="header"><h1><a href="../">神奈川県 住みやすさマップ</a></h1></div>
<div class="container">
<div class="breadcrumb"><a href="../">トップ</a> &gt; エリア一覧</div>
<h2>神奈川県 全{len(munis)}市区町村の住みやすさ</h2>
<div class="sort-controls">
<button class="sort-btn active" onclick="sortCards('score')">スコア順</button>
<button class="sort-btn" onclick="sortCards('name')">名前順</button>
<button class="sort-btn" onclick="sortCards('pop')">人口順</button>
</div>
<div class="muni-grid" id="muniGrid">{''.join(rows)}</div>
</div>
<div class="footer">
データ出典: 警察庁・神奈川県警・国土地理院・国土数値情報・e-Stat<br>
<a href="../">神奈川県 住みやすさマップ</a>
</div>
<script>
function sortCards(key){{
  const grid=document.getElementById('muniGrid');
  const cards=[...grid.children];
  cards.sort((a,b)=>{{
    if(key==='score')return parseFloat(b.querySelector('.muni-score').textContent)-parseFloat(a.querySelector('.muni-score').textContent);
    if(key==='name')return a.querySelector('.muni-name').textContent.localeCompare(b.querySelector('.muni-name').textContent,'ja');
    if(key==='pop'){{const g=t=>parseInt(t.querySelector('.muni-meta').textContent.match(/人口 ([\\d,]+)/)?.[1]?.replace(/,/g,'')||0);return g(b)-g(a)}}
  }});
  cards.forEach(c=>grid.appendChild(c));
  document.querySelectorAll('.sort-btn').forEach(b=>b.classList.remove('active'));
  if(event&&event.target)event.target.classList.add('active');
}}
</script>
</body></html>'''


# ====== メインパイプライン ======

def main():
    print('=' * 60)
    print('神奈川県 住みやすさデータ統合パイプライン')
    print('=' * 60)

    # 1. 境界データ読み込み
    print('\n[1/8] 境界データ読み込み...')
    towns = load_boundaries()
    print(f'  {len(towns)}町丁目を読み込み')

    # 2. 犯罪データ結合
    print('\n[2/8] 犯罪データ結合...')
    crime_total = load_crime_data(towns)
    print(f'  犯罪件数: {crime_total}件マッチ')

    # 3. 交通事故データ結合（最も時間がかかる）
    print('\n[3/8] 交通事故データ結合...')
    acc_total = load_accident_data(towns)
    print(f'  交通事故: {acc_total}件マッチ')

    # 4. 地価・医療・保育データ結合
    print('\n[4/8] 地価・医療・保育データ結合...')
    lp_count = spatial_join_points(towns, DATA / 'landprice.geojson',
                                   lambda t, f: t['landprices'].append(f['properties']))
    print(f'  地価: {lp_count}件マッチ')

    med_count = spatial_join_points(towns, DATA / 'medical.geojson',
                                   lambda t, f: t['medical'].append(f['properties']))
    print(f'  医療施設: {med_count}件マッチ')

    nur_count = spatial_join_points(towns, DATA / 'nursery.geojson',
                                   lambda t, f: t['nurseries'].append(f['properties']))
    print(f'  保育施設: {nur_count}件マッチ')

    # 5. 駅距離計算
    print('\n[5/8] 最寄り駅距離計算...')
    calc_nearest_station(towns)
    print('  完了')

    # 6. 公園データ結合
    print('\n[6/8] 公園データ結合...')
    calc_park_area(towns)

    # 7. スコアリング
    print('\n[7/8] パーセンタイルスコアリング...')
    calculate_scores(towns)
    scored = sum(1 for t in towns.values() if t.get('total_score') is not None)
    print(f'  {scored}エリアをスコアリング')

    # 8. ページ生成
    print('\n[8/8] ページ生成...')
    munis = aggregate_municipalities(towns)
    area_dir = SITE / 'area'
    area_dir.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    for muni in munis.values():
        muni_dir = area_dir / muni_slug(muni['name'])
        muni_dir.mkdir(parents=True, exist_ok=True)

        # 市区町村ページ
        muni_html = render_muni_page(muni, munis)
        with open(muni_dir / 'index.html', 'w', encoding='utf-8') as f:
            f.write(muni_html)
        total_pages += 1

        # 町丁目ページ
        for town in muni['towns']:
            if town['population'] == 0 and town['crime_count'] == 0:
                continue
            if town.get('total_score') is None:
                continue

            tslug = town_slug(town['town_name'])
            if not tslug:
                continue
            town_dir = muni_dir / tslug
            town_dir.mkdir(parents=True, exist_ok=True)

            town_html = render_town_page(town, muni, muni['towns'])
            with open(town_dir / 'index.html', 'w', encoding='utf-8') as f:
                f.write(town_html)
            total_pages += 1

    # エリア一覧ページ
    area_index_html = render_area_index(munis)
    with open(area_dir / 'index.html', 'w', encoding='utf-8') as f:
        f.write(area_index_html)
    total_pages += 1

    # データJSON出力
    export = {}
    for code, muni in munis.items():
        export[code] = {
            'name': muni['name'],
            'population': muni['population'],
            'avg_score': muni['avg_score'],
            'max_score': muni['max_score'],
            'min_score': muni['min_score'],
            'crime_count': muni['crime_count'],
            'medical_count': muni['medical_count'],
            'park_count': muni['park_count'],
            'town_count': len([t for t in muni['towns'] if t['population'] > 0]),
        }
    with open(DATA / 'municipality_data.json', 'w', encoding='utf-8') as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f'\n{"=" * 60}')
    print(f'完了!')
    print(f'  市区町村: {len(munis)}')
    print(f'  ページ数: {total_pages}')
    print(f'{"=" * 60}')


if __name__ == '__main__':
    main()
