# -*- coding: utf-8 -*-
"""代理サーバが引く資料表 server/docs.json を作る。

画面側の検索が返すのは小節の id だけで、本文は代理側がこの表から引く。
こうすれば画面から本文や指示を差し替えられない。前後で資料がずれない
ように、画面側の buildDocs（retrieval.js.part）と同じ単位・同じ順序で
作る。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'server', 'docs.json')


def untag(h):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h)).strip()


def build(guide, tasks):
    docs = {}

    for a in guide['articles']:
        for si, s in enumerate(a['sections']):
            parts = []
            for b in s['blocks']:
                t = b['t']
                if t in ('p', 'label', 'note', 'quote'):
                    parts.append(untag(b['html']))
                elif t == 'list':
                    parts.extend('・' + untag(i) for i in b['items'])
                elif t == 'dl':
                    for r in b['rows']:
                        parts.append((r.get('k', '') + '：' if r.get('k') else '')
                                     + untag(r['v']))
                elif t == 'table':
                    parts.extend(' | '.join(r) for r in b['rows'])
                elif t == 'att':
                    parts.append('［添付ファイル］%s %s（中身は未収録）'
                                 % (b['name'], b.get('size', '')))
                elif t == 'card':
                    parts.append('［リンク］%s %s' % (b['title'], b.get('site', '')))
                elif t in ('img', 'fig'):
                    # 同梱した画像は alt に中身を書いてある。画面向けの
                    # 短いキャプションより、そちらの方が模型の役に立つ。
                    cap = b.get('alt') or b.get('caption', '')
                    if cap:
                        parts.append('［図］' + cap)
            body = '\n'.join(p for p in parts if p)
            if not body and not s['heading']:
                continue
            label = a['title'] + ('　＞　' + s['heading'] if s['heading'] else '')
            docs['%s#%d' % (a['id'], si)] = {
                'label': label,
                'updated': a.get('modified', ''),
                'body': body,
            }

    # 前提の参照は内部 id ではなく手続きの名前で出す。模型に "sim" と
    # 渡しても何のことか分からない。
    titles = {t['id']: t['title'] for t in tasks['tasks']}

    for t in tasks['tasks']:
        parts = []
        if t.get('summary'):
            parts.append(t['summary'])
        if t.get('window'):
            parts.append('時期：' + t['window'])
        if t.get('cost'):
            parts.append('費用：' + t['cost'])
        if t.get('where'):
            parts.append('場所：' + t['where'])
        for r in t.get('requires', []):
            parts.append('先に必要：%s（%s）'
                         % (titles.get(r['id'], r['id']), r['why']))
        for key, lb in (('bring', '持ち物'), ('items', '内容'), ('notes', '注意')):
            for v in t.get(key, []):
                parts.append('%s：%s' % (lb, v))
        for k in ('discrepancy', 'clarification'):
            if t.get(k):
                parts.append(t[k])
        docs['task:' + t['id']] = {
            'label': '手続き：' + t['title'],
            'updated': '',
            'body': '\n'.join(parts),
        }

    for g in tasks['glossary']:
        docs['term:' + g['cn']] = {
            'label': '用語：%s / %s' % (g['cn'], g['ja']),
            'updated': '',
            'body': g.get('note', ''),
        }
    return docs


def main():
    with io.open(os.path.join(ROOT, 'app', 'data', 'guide.json'), encoding='utf-8') as f:
        guide = json.load(f)
    with io.open(os.path.join(ROOT, 'app', 'data', 'tasks.json'), encoding='utf-8') as f:
        tasks = json.load(f)

    docs = build(guide, tasks)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(docs, f, ensure_ascii=False, separators=(',', ':'))

    kinds = {'section': 0, 'task': 0, 'term': 0}
    for k in docs:
        kinds['task' if k.startswith('task:') else
              'term' if k.startswith('term:') else 'section'] += 1
    print('docs       :', len(docs),
          '（小節 %d / 手続き %d / 用語 %d）' % (kinds['section'], kinds['task'], kinds['term']))
    print('bytes      :', '{:,}'.format(os.path.getsize(OUT)))
    longest = max(docs.values(), key=lambda d: len(d['body']))
    print('最長の本文 :', len(longest['body']), '字 —', longest['label'][:44])


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
