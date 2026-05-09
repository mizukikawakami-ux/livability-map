"""
Vercel Analytics スクリプトを全HTMLファイルの </head> 直前に追加する
"""
import os
import glob

ANALYTICS_SNIPPET = '    <script>window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };</script>\n    <script defer src="/_vercel/insights/script.js"></script>\n'

SITE_DIR = os.path.join(os.path.dirname(__file__), '..', 'site')

def add_analytics(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # すでに追加済みならスキップ
    if '/_vercel/insights/script.js' in content:
        return False

    if '</head>' not in content:
        return False

    new_content = content.replace('</head>', ANALYTICS_SNIPPET + '</head>', 1)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True

def main():
    pattern = os.path.join(SITE_DIR, '**', '*.html')
    files = glob.glob(pattern, recursive=True)

    updated = 0
    skipped = 0
    errors = 0

    for filepath in files:
        try:
            result = add_analytics(filepath)
            if result:
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f'ERROR: {filepath} -> {e}')
            errors += 1

    print(f'完了: {updated}件更新 / {skipped}件スキップ（追加済み or </head>なし）/ {errors}件エラー')
    print(f'対象ファイル数: {len(files)}')

if __name__ == '__main__':
    main()
