# -*- coding: utf-8 -*-
"""検索方式の当たり確認用プロトタイプ（本番は画面側 JS に移す）。

日本語は語の区切りが無いので、辞書を持たずに済む 2-gram を単位にして
BM25 で並べる。「銀行口座を作りたい」→「銀行口座開設」のように、
表記が一致しなくても部分的に重なれば拾えるかを確かめる。
"""
import io
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))


def norm(s):
    """全角半角・大小文字・記号を畳んで、2-gram を安定させる。"""
    s = unicodedata.normalize('NFKC', s).lower()
    s = re.sub(r'[\s　]+', '', s)
    s = re.sub(r'[（）()「」『』【】、。・,.:：;；!！?？\-—–ー~〜/｜|"\'’”＋+*#＃※→←↑↓…]', '', s)
    return s


def grams(s):
    s = norm(s)
    if len(s) < 2:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


def strip_tags(h):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h)).strip()


def build_docs():
    """小節・手続き・用語を 1 件ずつの文書にする。"""
    guide = json.load(io.open(os.path.join(ROOT, 'app', 'data', 'guide.json'), encoding='utf-8'))
    tasks = json.load(io.open(os.path.join(ROOT, 'app', 'data', 'tasks.json'), encoding='utf-8'))
    docs = []

    for a in guide['articles']:
        for si, s in enumerate(a['sections']):
            parts = []
            for b in s['blocks']:
                t = b['t']
                if t in ('p', 'label', 'note', 'quote'):
                    parts.append(strip_tags(b['html']))
                elif t == 'list':
                    parts.extend(strip_tags(i) for i in b['items'])
                elif t == 'dl':
                    for r in b['rows']:
                        parts.append((r.get('k', '') + '：' if r.get('k') else '') + strip_tags(r['v']))
                elif t == 'table':
                    parts.extend(' '.join(r) for r in b['rows'])
                elif t == 'att':
                    parts.append(b['name'])
                elif t == 'card':
                    parts.append(b['title'] + ' ' + b.get('site', ''))
                elif t in ('img', 'fig'):
                    parts.append(b.get('caption') or b.get('alt', ''))
            body = '\n'.join(p for p in parts if p)
            if not body and not s['heading']:
                continue
            docs.append({
                'id': '%s#%d' % (a['id'], si),
                'kind': 'section',
                'title': a['title'],
                'heading': s['heading'] or '',
                'body': body,
            })

    for t in tasks['tasks']:
        parts = [t.get('summary', '')]
        parts += t.get('bring', []) + t.get('items', []) + t.get('notes', [])
        parts += [t.get('cost', ''), t.get('where', ''), t.get('window', '')]
        for r in t.get('requires', []):
            parts.append(r.get('why', ''))
        docs.append({
            'id': 'task:' + t['id'],
            'kind': 'task',
            'title': t['title'],
            'heading': '',
            'body': '\n'.join(p for p in parts if p),
        })

    for g in tasks['glossary']:
        docs.append({
            'id': 'term:' + g['cn'],
            'kind': 'term',
            'title': g['cn'] + ' / ' + g['ja'],
            'heading': '',
            'body': g.get('note', ''),
        })
    return docs


# 質問から「内容語」を切り出す。日本語は語の区切りが無いが、文字種の
# 切れ目はほぼ語の切れ目になる。漢字列・カタカナ列・英数列は内容語の
# 候補、ひらがな列は助詞や活用が主なので捨てる。
KANJI = r'一-鿿々〆'
KATA = r'ァ-ヺー'
CONTENT = re.compile('[%s]{2,}|[%s]{2,}|[a-z0-9]{2,}' % (KANJI, KATA))


def content_words(q):
    return CONTENT.findall(norm(q))


def load_synonyms():
    p = os.path.join(ROOT, 'app', 'data', 'synonyms.json')
    m = json.load(io.open(p, encoding='utf-8'))['map']
    return [(norm(k), v) for k, v in m.items()]


SYN = load_synonyms()


def expand(q):
    """質問に資料側の言い回しを足す。元の質問より軽く数える。"""
    nq = norm(q)
    extra = [v for k, v in SYN if k and k in nq]
    return ' '.join(extra)


class BM25:
    """見出し・題名を重めに数えた BM25。"""

    K1 = 1.2
    B = 0.82          # 長い記事（9.1 その他情報は2.6万字）が何にでも当たるのを抑える
    W_TITLE = 3
    W_HEADING = 3
    W_SYN = 0.45      # 同義語で足した分は本来の語より軽く
    W_EXACT = 6.0     # 内容語がそのまま出てくる文書を強く押し上げる

    def __init__(self, docs):
        self.docs = docs
        self.tf = []
        self.df = Counter()
        self.post = defaultdict(list)
        total = 0
        for i, d in enumerate(docs):
            g = (grams(d['title']) * self.W_TITLE
                 + grams(d['heading']) * self.W_HEADING
                 + grams(d['body']))
            c = Counter(g)
            self.tf.append(c)
            total += len(g)
            for term in c:
                self.df[term] += 1
                self.post[term].append(i)
        self.avg = total / max(1, len(docs))
        self.len = [sum(c.values()) for c in self.tf]
        self.N = len(docs)
        # 完全一致の判定用に、正規化した全文を持っておく
        self.flat = [norm(d['title'] + d['heading'] + d['body']) for d in docs]

    def _bm25(self, text, weight, scores):
        for term, qn in Counter(grams(text)).items():
            if term not in self.post:
                continue
            idf = math.log(1 + (self.N - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for i in self.post[term]:
                f = self.tf[i][term]
                denom = f + self.K1 * (1 - self.B + self.B * self.len[i] / self.avg)
                scores[i] += weight * idf * (f * (self.K1 + 1) / denom) * min(qn, 3)

    def search(self, q, k=10):
        scores = defaultdict(float)
        self._bm25(q, 1.0, scores)
        syn = expand(q)
        if syn:
            self._bm25(syn, self.W_SYN, scores)

        # 「中関新園」「居留許可」のような固有名詞は 2-gram に割ると散って
        # しまう。語がそのまま出てくる文書を別枠で押し上げる。
        for w in content_words(q):
            if len(w) < 2:
                continue
            idf = math.log(1 + self.N / (1 + sum(1 for f in self.flat if w in f)))
            for i, f in enumerate(self.flat):
                if w in f:
                    scores[i] += self.W_EXACT * idf * math.log(1 + len(w))

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        return [(self.docs[i], sc) for i, sc in ranked]


# 「この記事（または手続き）が入っていれば答えられる」という正解の目印。
# 資料を読んで手で付けた。LLM は上位 k 件すべてを読むので、順位そのものより
# 上位 k に入るかどうか（recall@k）が効く指標になる。
EXPECT = {
    'パスポートを預ける前に銀行口座を作りたいです。何を準備しますか？': ['n35eb601ddae5', 'task:bank'],
    '学生証がまだありません。SIMカードを買うには何が必要ですか？': ['n6305b4e3cabf', 'task:sim'],
    '中関新園に住みます。入寮のとき何を確認すればいいですか？': ['n0dede70ff906', 'n14e161185f83', 'n42015e37d961', 'task:move_in'],
    '报到の日は何を持っていけばよいですか？': ['n3584dbcda120', 'task:baodao'],
    '居留許可の申請中に高速鉄道に乗れますか？': ['ne3f008f7c5fd', 'task:residence_permit'],
    'ケータイの料金はいくらくらいかかりますか？': ['n6305b4e3cabf', 'task:sim', 'task:sim_close'],
    '体检はどこで受けられますか？予約は必要ですか？': ['nbbed5fc388e1', 'task:tijian'],
    '寮の退去はいつまでですか': ['n0dede70ff906', 'n42015e37d961', 'task:checkout'],
    '授業は何時から始まりますか': ['nbebdeb048253'],
    '病院に行きたい': ['n1ff0c3032fc0'],
    '学食でお金はどう払うの': ['nd7655beed895'],
    'ビザの種類がわかりません': ['nad1c4d69e689', 'task:visa'],
}


def doc_key(d):
    """記事単位・手続き単位に丸めた目印。"""
    return d['id'].split('#')[0]


def recall_report(idx):
    print('=== recall@k（正解の記事が上位 k 件に入るか） ===')
    for k in (4, 8, 12, 20):
        hit = 0
        miss = []
        for q, want in EXPECT.items():
            keys = {doc_key(d) for d, _ in idx.search(q, k)}
            if keys & set(want):
                hit += 1
            else:
                miss.append(q)
        print('  k=%-3d %2d/%d' % (k, hit, len(EXPECT)),
              ('　取れず: ' + ' / '.join(x[:26] for x in miss)) if miss else '　全問命中')
    print()
    print('=== 正解が何位で最初に出るか ===')
    for q, want in EXPECT.items():
        rank = None
        for i, (d, _) in enumerate(idx.search(q, 30), 1):
            if doc_key(d) in want:
                rank = i
                break
        print('  %s位  %s' % (str(rank).rjust(3) if rank else ' --', q[:44]))


QUESTIONS = [
    'パスポートを預ける前に銀行口座を作りたいです。何を準備しますか？',
    '学生証がまだありません。SIMカードを買うには何が必要ですか？',
    '中関新園に住みます。入寮のとき何を確認すればいいですか？',
    '报到の日は何を持っていけばよいですか？',
    '居留許可の申請中に高速鉄道に乗れますか？',
    'ケータイの料金はいくらくらいかかりますか？',
    '体检はどこで受けられますか？予約は必要ですか？',
    '寮の退去はいつまでですか',
    '授業は何時から始まりますか',
    '病院に行きたい',
    '学食でお金はどう払うの',
    'ビザの種類がわかりません',
]


def main():
    docs = build_docs()
    idx = BM25(docs)
    print('文書数      : %d（小節 %d / 手続き %d / 用語 %d）' % (
        len(docs),
        sum(1 for d in docs if d['kind'] == 'section'),
        sum(1 for d in docs if d['kind'] == 'task'),
        sum(1 for d in docs if d['kind'] == 'term')))
    print('ユニーク2-gram: %d' % len(idx.post))
    print('転置エントリ  : %d' % sum(len(v) for v in idx.post.values()))
    print('平均文書長    : %.0f gram' % idx.avg)
    print()

    for q in QUESTIONS:
        print('■', q)
        for d, sc in idx.search(q, 4):
            label = d['title'] + (' > ' + d['heading'] if d['heading'] else '')
            print('   %5.1f [%s] %s' % (sc, d['kind'][:4], label[:66]))
        print()

    recall_report(idx)
    print()
    # 上位 12 件を prompt に入れたときの文字数を見る（64KiB ≒ 21000 字の制約）
    print('--- prompt に入れる資料の分量（上位12件） ---')
    for q in QUESTIONS[:5]:
        chars = sum(len(d['body']) + len(d['title']) + len(d['heading'])
                    for d, _ in idx.search(q, 12))
        print('  %5d 字  %s' % (chars, q[:34]))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
