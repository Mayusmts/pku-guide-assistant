# -*- coding: utf-8 -*-
"""app/template.html にデータを埋め込んで app/index.html を書き出す。

データは fetch ではなく <script type="application/json"> に直接埋め込む。
Artifact の CSP は同一オリジンでない fetch を黙って落とすため、埋め込みの
方が読み込み失敗の余地がない。"<" だけエスケープすれば script の早期終了を
防げる。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')


def read(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


def embed(path):
    """JSON を最小化し、script を早期終了させ得る '<' を退避する。"""
    data = json.loads(read(path))
    s = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return s.replace('<', '\\u003c')


def endpoint():
    """環境変数 AI_ENDPOINT を JSON 文字列リテラルにして返す。

    未設定なら空文字。空のままなら AI の欄は出ず、ページは検索だけで動く。
    独立配備するときだけ代理サーバ（FC）の URL を入れる。値は json.dumps を
    通すので、引用符などが混ざっても JS を壊さない。
    """
    url = os.environ.get('AI_ENDPOINT', '').strip()
    if url and not url.startswith('https://'):
        raise SystemExit('AI_ENDPOINT は https:// で始まる必要があります: %s' % url)
    return json.dumps(url)


def main():
    tpl = read(os.path.join(APP, 'template.html'))
    guide = embed(os.path.join(APP, 'data', 'guide.json'))
    tasks = embed(os.path.join(APP, 'data', 'tasks.json'))
    syn = embed(os.path.join(APP, 'data', 'synonyms.json'))

    # 検索モジュールは別ファイルで編集し、ここで差し込む
    retrieval = read(os.path.join(APP, 'retrieval.js.part'))

    for token in ('__GUIDE_JSON__', '__TASKS_JSON__', '__SYN_JSON__', '__RETRIEVAL_JS__', '__AI_ENDPOINT__'):
        if token not in tpl:
            raise SystemExit('テンプレートに %s がありません' % token)

    ai = endpoint()
    out = (tpl.replace('__RETRIEVAL_JS__', retrieval)
              .replace('__GUIDE_JSON__', guide)
              .replace('__TASKS_JSON__', tasks)
              .replace('__SYN_JSON__', syn)
              .replace('__AI_ENDPOINT__', ai))

    dest = os.path.join(APP, 'index.html')
    with io.open(dest, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)

    size = os.path.getsize(dest)
    print('index.html :', '{:,}'.format(size), 'bytes', '(%.1f MB)' % (size / 1048576.0))
    print('guide json :', '{:,}'.format(len(guide.encode('utf-8'))), 'bytes')
    print('tasks json :', '{:,}'.format(len(tasks.encode('utf-8'))), 'bytes')
    print('synonyms   :', '{:,}'.format(len(syn.encode('utf-8'))), 'bytes')
    print('retrieval  :', '{:,}'.format(len(retrieval.encode('utf-8'))), 'bytes')
    print('AI endpoint:', ai if ai != '""' else '(未設定 — AI の欄は出ません)')
    if size > 16 * 1024 * 1024:
        raise SystemExit('16MB を超えています')
    for token in ('__GUIDE_JSON__', '__TASKS_JSON__', '__SYN_JSON__', '__RETRIEVAL_JS__', '__AI_ENDPOINT__'):
        if token in out:
            raise SystemExit('プレースホルダ %s が残っています' % token)
    print('OK')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
