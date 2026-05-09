"""
Phase 2: 町丁目ごとの個別ページを静的生成するスクリプト
- 全GeoJSONから町丁目ごとにデータを集約
- HTML個別ページ + 一覧ページを生成
- JSON-LD構造化データを埋め込み
"""

import json
import re
import math
from pathlib import Path
from html import escape

BASE = Path(__file__).parent.parent
SITE = BASE / 'site'
DATA = SITE / 'data'
AREA_DIR = SITE / 'area'


def load_json(path):
    if not path.exists():
        return {'type': 'FeatureCollection', 'features': []}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


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


def point_in_feature(lon, lat, feature):
    geom = feature.get('geometry')
    if not geom:
        return False
    gtype = geom['type']
    coords = geom['coordinates']

    if gtype == 'Polygon':
        return point_in_polygon(lon, lat, coords[0])
    elif gtype == 'MultiPolygon':
        for poly in coords:
            if point_in_polygon(lon, lat, poly[0]):
                return True
    return False


def town_slug(name):
    slug = re.sub(r'横浜市青葉区', '', name)
    slug = slug.strip()
    slug = re.sub(r'[０-９]', lambda m: str(ord(m.group()) - 0xFF10), slug)
    slug = re.sub(r'[一二三四五六七八九十]丁目', lambda m: {
        '一丁目': '1', '二丁目': '2', '三丁目': '3', '四丁目': '4',
        '五丁目': '5', '六丁目': '6', '七丁目': '7', '八丁目': '8',
        '九丁目': '9', '十丁目': '10'
    }.get(m.group(), m.group()), slug)
    slug = re.sub(r'[１-９]丁目', lambda m: str(ord(m.group()[0]) - 0xFF10), slug)
    slug = re.sub(r'\s+', '-', slug)
    return slug


def aggregate_data():
    """全GeoJSONから町丁目ごとにデータを集約"""
    population = load_json(DATA / 'population.geojson')
    crime_map = load_json(DATA / 'crime_map.geojson')
    accidents = load_json(DATA / 'accidents.geojson')
    landprice = load_json(DATA / 'landprice.geojson')
    nursery = load_json(DATA / 'nursery.geojson')
    medical = load_json(DATA / 'medical.geojson')
    mansion = load_json(DATA / 'mansion.geojson')

    towns = {}
    for feat in population['features']:
        props = feat['properties']
        name = props.get('town', props.get('name', ''))
        if not name:
            continue
        display = props.get('name', f'横浜市青葉区{name}')
        towns[name] = {
            'name': name,
            'display_name': display,
            'slug': town_slug(display),
            'population': props.get('population', 0),
            'households': props.get('households', 0),
            'crime_count': 0,
            'crime_breakdown': '',
            'accident_count': 0,
            'landprices': [],
            'nurseries': [],
            'medical_facilities': [],
            'mansions': [],
            'geometry': feat.get('geometry'),
        }

    for feat in crime_map['features']:
        props = feat['properties']
        name = props.get('town', '')
        if name in towns:
            towns[name]['crime_count'] = props.get('count', 0)
            towns[name]['crime_breakdown'] = props.get('breakdown', '')

    for feat in accidents['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        for name, town in towns.items():
            if town['geometry'] and point_in_feature(lon, lat, {'geometry': town['geometry']}):
                town['accident_count'] += 1
                break

    for feat in landprice['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        for name, town in towns.items():
            if town['geometry'] and point_in_feature(lon, lat, {'geometry': town['geometry']}):
                town['landprices'].append(feat['properties'])
                break

    for feat in nursery['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        for name, town in towns.items():
            if town['geometry'] and point_in_feature(lon, lat, {'geometry': town['geometry']}):
                town['nurseries'].append(feat['properties'])
                break

    for feat in medical['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        for name, town in towns.items():
            if town['geometry'] and point_in_feature(lon, lat, {'geometry': town['geometry']}):
                town['medical_facilities'].append(feat['properties'])
                break

    for feat in mansion['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]
        for name, town in towns.items():
            if town['geometry'] and point_in_feature(lon, lat, {'geometry': town['geometry']}):
                town['mansions'].append(feat['properties'])
                break

    return towns


def score_livability(town):
    """簡易スコアリング（各項目0-20点、合計100点満点）"""
    scores = {}

    pop = town['population']
    if pop > 0:
        crime_rate = town['crime_count'] / pop * 1000
        scores['safety'] = max(0, min(20, int(20 - crime_rate * 2)))
    else:
        scores['safety'] = 10

    acc = town['accident_count']
    scores['traffic'] = max(0, min(20, int(20 - acc * 0.5)))

    med = len(town['medical_facilities'])
    scores['medical'] = min(20, int(med * 2))

    nur = len(town['nurseries'])
    scores['childcare'] = min(20, int(nur * 4))

    prices = [lp.get('price', 0) for lp in town['landprices'] if lp.get('price')]
    if prices:
        avg = sum(prices) / len(prices)
        scores['cost'] = max(0, min(20, int(20 - (avg - 200000) / 30000)))
    else:
        scores['cost'] = 10

    total = sum(scores.values())
    return scores, total


def generate_description(town, scores, total):
    """データに基づく定型解説文を生成"""
    name = town['display_name']
    pop = town['population']
    hh = town['households']
    crime = town['crime_count']
    acc = town['accident_count']
    med = len(town['medical_facilities'])
    nur = len(town['nurseries'])
    mansions = town['mansions']

    lines = []
    lines.append(f'{name}は、人口{pop:,}人・{hh:,}世帯が暮らすエリアです。')

    if crime == 0:
        lines.append('2024年の犯罪統計では犯罪の報告がなく、治安の良いエリアといえます。')
    elif crime <= 3:
        lines.append(f'2024年の犯罪件数は{crime}件と少なく、比較的安全なエリアです。')
    elif crime <= 10:
        lines.append(f'2024年の犯罪件数は{crime}件です。')
    else:
        lines.append(f'2024年の犯罪件数は{crime}件とやや多めです。交通量の多い駅周辺エリアが含まれる可能性があります。')

    if acc == 0:
        lines.append('交通事故の報告はありません。')
    elif acc <= 5:
        lines.append(f'交通事故は{acc}件と少なめです。')
    else:
        lines.append(f'交通事故は{acc}件発生しています。幹線道路沿いのエリアでは注意が必要です。')

    if med > 0:
        hospitals = sum(1 for m in town['medical_facilities'] if m.get('type') == '病院')
        clinics = sum(1 for m in town['medical_facilities'] if m.get('type') == '診療所')
        dental = sum(1 for m in town['medical_facilities'] if m.get('type') == '歯科')
        parts = []
        if hospitals: parts.append(f'病院{hospitals}')
        if clinics: parts.append(f'診療所{clinics}')
        if dental: parts.append(f'歯科{dental}')
        lines.append(f'医療施設は{med}件（{"、".join(parts)}）あります。')

    if nur > 0:
        total_cap = sum(n.get('capacity', 0) for n in town['nurseries'])
        lines.append(f'保育施設は{nur}か所（定員計{total_cap:,}人）あり、子育て環境が整っています。')
    else:
        lines.append('エリア内に保育施設はありませんが、隣接エリアの施設が利用できます。')

    prices = [lp.get('price', 0) for lp in town['landprices'] if lp.get('price')]
    if prices:
        avg = int(sum(prices) / len(prices))
        lines.append(f'地価公示の平均価格は{avg:,}円/m²です。')

    if mansions:
        names = [m.get('name', '') for m in mansions]
        lines.append(f'建設中・建設予定のマンションとして{"、".join(names)}があります。')

    return '\n'.join(lines)


def render_town_page(town, scores, total, description, all_towns):
    """個別ページHTMLを生成"""
    name = escape(town['display_name'])
    slug = town['slug']
    raw_name = town['name']

    prices = [lp.get('price', 0) for lp in town['landprices'] if lp.get('price')]
    avg_price = int(sum(prices) / len(prices)) if prices else None

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Place",
        "name": town['display_name'],
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "横浜市青葉区",
            "addressRegion": "神奈川県",
            "addressCountry": "JP"
        },
        "description": description[:200]
    }

    score_bar = ''
    label_map = {'safety': '治安', 'traffic': '交通安全', 'medical': '医療', 'childcare': '子育て', 'cost': 'コスト'}
    for key, label in label_map.items():
        val = scores.get(key, 0)
        pct = val / 20 * 100
        color = '#2ecc71' if val >= 14 else '#f39c12' if val >= 8 else '#e74c3c'
        score_bar += f'''
            <div class="score-row">
                <span class="score-label">{label}</span>
                <div class="score-bar-bg"><div class="score-bar-fill" style="width:{pct}%;background:{color}"></div></div>
                <span class="score-value">{val}/20</span>
            </div>'''

    facilities_html = ''
    if town['medical_facilities']:
        facilities_html += '<h3>医療施設</h3><ul>'
        for m in town['medical_facilities'][:10]:
            facilities_html += f'<li>{escape(m.get("name", ""))}<span class="facility-type">{escape(m.get("type", ""))}</span></li>'
        if len(town['medical_facilities']) > 10:
            facilities_html += f'<li>...他{len(town["medical_facilities"]) - 10}件</li>'
        facilities_html += '</ul>'

    if town['nurseries']:
        facilities_html += '<h3>保育施設</h3><ul>'
        for n in town['nurseries']:
            cap = n.get('capacity', 0)
            facilities_html += f'<li>{escape(n.get("name", ""))} <span class="facility-type">定員{cap}人</span></li>'
        facilities_html += '</ul>'

    if town['mansions']:
        facilities_html += '<h3>建設中・予定マンション</h3><ul>'
        for m in town['mansions']:
            facilities_html += f'<li>{escape(m.get("name", ""))} <span class="facility-type">{escape(m.get("status", ""))}</span></li>'
        facilities_html += '</ul>'

    neighbor_links = []
    for t in sorted(all_towns.values(), key=lambda x: x['display_name']):
        if t['name'] != raw_name:
            neighbor_links.append(f'<a href="../{t["slug"]}/">{escape(t["display_name"].replace("横浜市青葉区", ""))}</a>')

    nearby_html = ' / '.join(neighbor_links[:20])
    if len(neighbor_links) > 20:
        nearby_html += f' <a href="../">...全{len(neighbor_links)}エリア</a>'

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name}の住みやすさ - 青葉区住みやすさマップ</title>
    <meta name="description" content="{escape(description[:160])}">
    <link rel="canonical" href="https://example.com/area/{slug}/">
    <script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif; background:#f8f9fa; color:#333; line-height:1.7; }}
        .header {{ background:#1a1a2e; color:#fff; padding:16px 24px; }}
        .header h1 {{ font-size:1.1rem; }}
        .header a {{ color:#8ab4f8; text-decoration:none; }}
        .container {{ max-width:800px; margin:0 auto; padding:24px 16px; }}
        .breadcrumb {{ font-size:0.8rem; color:#666; margin-bottom:16px; }}
        .breadcrumb a {{ color:#1a73e8; text-decoration:none; }}
        h2 {{ font-size:1.5rem; margin-bottom:8px; color:#1a1a2e; }}
        .total-score {{ font-size:2.5rem; font-weight:700; color:#1a1a2e; margin:16px 0; }}
        .total-score span {{ font-size:1rem; color:#666; font-weight:400; }}
        .description {{ background:#fff; border-radius:8px; padding:20px; margin:20px 0; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
        .description p {{ margin-bottom:8px; }}
        .scores {{ background:#fff; border-radius:8px; padding:20px; margin:20px 0; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
        .score-row {{ display:flex; align-items:center; gap:12px; margin-bottom:8px; }}
        .score-label {{ width:80px; font-size:0.85rem; font-weight:600; color:#555; }}
        .score-bar-bg {{ flex:1; height:20px; background:#eee; border-radius:10px; overflow:hidden; }}
        .score-bar-fill {{ height:100%; border-radius:10px; transition:width 0.5s; }}
        .score-value {{ width:50px; text-align:right; font-size:0.85rem; font-weight:600; }}
        .data-section {{ background:#fff; border-radius:8px; padding:20px; margin:20px 0; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
        .data-section h3 {{ font-size:1rem; margin-bottom:12px; color:#1a1a2e; border-bottom:2px solid #e0e0e0; padding-bottom:6px; }}
        .data-section ul {{ list-style:none; }}
        .data-section li {{ padding:6px 0; border-bottom:1px solid #f0f0f0; font-size:0.9rem; }}
        .facility-type {{ color:#888; font-size:0.8rem; margin-left:8px; }}
        .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin:20px 0; }}
        .stat-card {{ background:#fff; border-radius:8px; padding:16px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
        .stat-card .value {{ font-size:1.5rem; font-weight:700; color:#1a1a2e; }}
        .stat-card .label {{ font-size:0.75rem; color:#888; margin-top:4px; }}
        .nearby {{ margin:20px 0; font-size:0.8rem; color:#666; line-height:2; }}
        .nearby a {{ color:#1a73e8; text-decoration:none; margin:0 4px; }}
        .nearby a:hover {{ text-decoration:underline; }}
        .footer {{ background:#1a1a2e; color:#aaa; padding:16px 24px; font-size:0.72rem; margin-top:40px; text-align:center; }}
        .footer a {{ color:#8ab4f8; text-decoration:none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1><a href="../../">青葉区 住みやすさマップ</a></h1>
    </div>
    <div class="container">
        <div class="breadcrumb">
            <a href="../../">トップ</a> &gt; <a href="../">エリア一覧</a> &gt; {name}
        </div>

        <h2>{name}の住みやすさ</h2>
        <div class="total-score">{total}<span> / 100点</span></div>

        <div class="stats">
            <div class="stat-card"><div class="value">{town['population']:,}</div><div class="label">人口</div></div>
            <div class="stat-card"><div class="value">{town['households']:,}</div><div class="label">世帯数</div></div>
            <div class="stat-card"><div class="value">{town['crime_count']}</div><div class="label">犯罪件数(2024)</div></div>
            <div class="stat-card"><div class="value">{town['accident_count']}</div><div class="label">交通事故(2024)</div></div>
            <div class="stat-card"><div class="value">{len(town['medical_facilities'])}</div><div class="label">医療施設</div></div>
            <div class="stat-card"><div class="value">{len(town['nurseries'])}</div><div class="label">保育施設</div></div>
        </div>

        <div class="scores">
            <h3 style="font-size:1rem;margin-bottom:12px;color:#1a1a2e;">住みやすさスコア</h3>
            {score_bar}
        </div>

        <div class="description">
            <h3 style="font-size:1rem;margin-bottom:12px;color:#1a1a2e;">エリア解説</h3>
            {''.join(f'<p>{escape(line)}</p>' for line in description.split(chr(10)) if line.strip())}
        </div>

        <div class="data-section">
            {facilities_html}
        </div>

        <div class="nearby">
            <strong>青葉区の他のエリア:</strong> {nearby_html}
        </div>
    </div>
    <div class="footer">
        データ出典: 警察庁・神奈川県警・国土地理院・国土数値情報・e-Stat・横浜市オープンデータ<br>
        <a href="../../">青葉区 住みやすさマップ</a> | 本サイトはオープンデータに基づく参考情報です
    </div>
</body>
</html>'''


def render_index_page(all_towns):
    """エリア一覧ページを生成"""
    rows = []
    for town in sorted(all_towns.values(), key=lambda x: x['display_name']):
        scores, total = score_livability(town)
        short_name = escape(town['display_name'].replace('横浜市青葉区', ''))
        color = '#2ecc71' if total >= 60 else '#f39c12' if total >= 40 else '#e74c3c'
        rows.append(f'''
            <a href="{town['slug']}/" class="town-card">
                <div class="town-name">{short_name}</div>
                <div class="town-score" style="color:{color}">{total}点</div>
                <div class="town-meta">人口 {town['population']:,} / 犯罪 {town['crime_count']}件 / 医療 {len(town['medical_facilities'])}件</div>
            </a>''')

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>青葉区 エリア別住みやすさ一覧 - 青葉区住みやすさマップ</title>
    <meta name="description" content="横浜市青葉区の全{len(all_towns)}エリアの住みやすさスコアを一覧で比較。犯罪・交通事故・医療・保育・地価のデータから算出。">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif; background:#f8f9fa; color:#333; }}
        .header {{ background:#1a1a2e; color:#fff; padding:16px 24px; }}
        .header h1 {{ font-size:1.1rem; }}
        .header a {{ color:#8ab4f8; text-decoration:none; }}
        .container {{ max-width:1000px; margin:0 auto; padding:24px 16px; }}
        .breadcrumb {{ font-size:0.8rem; color:#666; margin-bottom:16px; }}
        .breadcrumb a {{ color:#1a73e8; text-decoration:none; }}
        h2 {{ font-size:1.4rem; margin-bottom:16px; color:#1a1a2e; }}
        .town-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }}
        .town-card {{ display:block; background:#fff; border-radius:8px; padding:16px; text-decoration:none; color:#333; box-shadow:0 1px 3px rgba(0,0,0,0.08); transition:box-shadow 0.2s; }}
        .town-card:hover {{ box-shadow:0 4px 12px rgba(0,0,0,0.15); }}
        .town-name {{ font-weight:700; font-size:1rem; margin-bottom:4px; }}
        .town-score {{ font-size:1.3rem; font-weight:700; margin-bottom:4px; }}
        .town-meta {{ font-size:0.72rem; color:#888; }}
        .footer {{ background:#1a1a2e; color:#aaa; padding:16px 24px; font-size:0.72rem; margin-top:40px; text-align:center; }}
        .footer a {{ color:#8ab4f8; text-decoration:none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1><a href="../">青葉区 住みやすさマップ</a></h1>
    </div>
    <div class="container">
        <div class="breadcrumb">
            <a href="../">トップ</a> &gt; エリア一覧
        </div>
        <h2>青葉区 全{len(all_towns)}エリアの住みやすさ</h2>
        <div class="town-grid">
            {''.join(rows)}
        </div>
    </div>
    <div class="footer">
        データ出典: 警察庁・神奈川県警・国土地理院・国土数値情報・e-Stat・横浜市オープンデータ<br>
        <a href="../">青葉区 住みやすさマップ</a>
    </div>
</body>
</html>'''


def main():
    print('データ集約中...')
    towns = aggregate_data()
    print(f'{len(towns)}エリア分のデータを集約')

    AREA_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    for name, town in towns.items():
        if town['population'] == 0 and town['crime_count'] == 0:
            continue

        scores, total = score_livability(town)
        description = generate_description(town, scores, total)
        html = render_town_page(town, scores, total, description, towns)

        page_dir = AREA_DIR / town['slug']
        page_dir.mkdir(parents=True, exist_ok=True)
        with open(page_dir / 'index.html', 'w', encoding='utf-8') as f:
            f.write(html)
        generated += 1

    index_html = render_index_page({k: v for k, v in towns.items()
                                     if v['population'] > 0 or v['crime_count'] > 0})
    with open(AREA_DIR / 'index.html', 'w', encoding='utf-8') as f:
        f.write(index_html)

    print(f'生成完了: {generated}エリアの個別ページ + 一覧ページ')
    town_data_path = DATA / 'town_data.json'
    export = {}
    for name, town in towns.items():
        if town['population'] == 0 and town['crime_count'] == 0:
            continue
        scores, total = score_livability(town)
        export[name] = {
            'display_name': town['display_name'],
            'slug': town['slug'],
            'population': town['population'],
            'households': town['households'],
            'crime_count': town['crime_count'],
            'accident_count': town['accident_count'],
            'medical_count': len(town['medical_facilities']),
            'nursery_count': len(town['nurseries']),
            'mansion_count': len(town['mansions']),
            'score': total,
            'scores': scores,
        }
    with open(town_data_path, 'w', encoding='utf-8') as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    print(f'町丁目集約データ → {town_data_path.name}')


if __name__ == '__main__':
    main()
