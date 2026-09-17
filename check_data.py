# -*- coding: utf-8 -*-
"""app/data/*.json の整合性を検査する。

- tasks.json の sources が guide.json に存在する記事 id か
- requires が存在するタスク id か、循環していないか
- appliesTo / when のキーと値が options に定義されているか
- phase が phases に定義されているか
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with io.open(os.path.join(ROOT, 'app', 'data', name), encoding='utf-8') as f:
        return json.load(f)


def main():
    guide = load('guide.json')
    tasks = load('tasks.json')

    art_ids = {a['id'] for a in guide['articles']}
    phases = {p['key'] for p in tasks['phases']}
    options = {k: {o['key'] for o in v} for k, v in tasks['options'].items()}
    task_ids = [t['id'] for t in tasks['tasks']]
    errors = []

    if len(set(task_ids)) != len(task_ids):
        errors.append('タスク id が重複している')

    for t in tasks['tasks']:
        tid = t['id']
        if t['phase'] not in phases:
            errors.append('%s: 未定義の phase %r' % (tid, t['phase']))
        for s in t.get('sources', []):
            if s not in art_ids:
                errors.append('%s: sources に存在しない記事 id %r' % (tid, s))
        if not t.get('sources'):
            errors.append('%s: sources が空' % tid)
        for r in t.get('requires', []):
            if r['id'] not in task_ids:
                errors.append('%s: requires に存在しないタスク %r' % (tid, r['id']))
            if not r.get('why'):
                errors.append('%s: requires %r に why がない' % (tid, r['id']))
            for k, vals in (r.get('when') or {}).items():
                if k not in options:
                    errors.append('%s: when の未定義キー %r' % (tid, k))
                    continue
                for v in vals:
                    if v not in options[k]:
                        errors.append('%s: when.%s の未定義値 %r' % (tid, k, v))
        for k, vals in (t.get('appliesTo') or {}).items():
            if k not in options:
                errors.append('%s: appliesTo の未定義キー %r' % (tid, k))
                continue
            for v in vals:
                if v not in options[k]:
                    errors.append('%s: appliesTo.%s の未定義値 %r' % (tid, k, v))
        for k in (t.get('byHousing') or {}):
            if k not in options['housing']:
                errors.append('%s: byHousing の未定義値 %r' % (tid, k))

    # 循環検出
    dep = {t['id']: [r['id'] for r in t.get('requires', [])] for t in tasks['tasks']}
    state = {}

    def visit(n, path):
        if state.get(n) == 'done':
            return
        if state.get(n) == 'open':
            errors.append('依存が循環している: %s' % ' -> '.join(path + [n]))
            return
        state[n] = 'open'
        for m in dep.get(n, []):
            if m in dep:
                visit(m, path + [n])
        state[n] = 'done'

    for n in dep:
        visit(n, [])

    # 到達できないタスク（前提にも登場せず、前提も持たない孤立ノードの確認用）
    referenced = {m for ms in dep.values() for m in ms}
    print('記事数        :', len(art_ids))
    print('タスク数      :', len(task_ids))
    print('依存エッジ数  :', sum(len(v) for v in dep.values()))
    print('用語数        :', len(tasks['glossary']))
    print('前提に現れない:', [t for t in task_ids if t not in referenced])

    cited = {s for t in tasks['tasks'] for s in t.get('sources', [])}
    print('引用されない記事 (%d):' % len(art_ids - cited))
    by_id = {a['id']: a for a in guide['articles']}
    for i in sorted(art_ids - cited):
        print('   ', i, by_id[i]['title'])

    if errors:
        print('\n❌ エラー %d 件' % len(errors))
        for e in errors:
            print('   -', e)
        return 1
    print('\n✅ 整合性エラーなし')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
