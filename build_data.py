# -*- coding: utf-8 -*-
"""note の記事本文（HTML）から app/data/guide.json を生成する。

materials/inventory.json の text は本文を行単位に潰したもので、note の
太字が独立した行になるため段落と箇条書きの区別が失われている。そこで
materials/api_export/<id>.json の data.body（元の HTML）を解析し、段落・
箇条書き・見出しの構造を保ったまま取り出す。

文章そのものは一切書き換えない。落とすのは note 固有の装飾要素
（自動目次・区切り線）と、外部から読み込めない画像だけで、画像は
キャプションを残して「元記事に図あり」と分かるようにする。

分類とタグは SOURCE_INVENTORY.md の整理を引き継いだ編集タグであり、
作者による統一宣言ではない。
"""
import glob
import io
import json
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_INV = os.path.join(ROOT, 'materials', 'inventory.json')
SRC_API = os.path.join(ROOT, 'materials', 'api_export')
OUT = os.path.join(ROOT, 'app', 'data', 'guide.json')

# ---- 分類（46篇を手作業で割り当て） ----
CATEGORY = {
    'meta':      ['n75c0b775e9e2'],
    'schedule':  ['nbebdeb048253', 'n960d0ae94257'],
    'pre':       ['nad1c4d69e689', 'ne1cd0ad6011b', 'ned5f6d417396', 'nf6744365b4aa'],
    'housing':   ['n14e161185f83', 'n23faa8ef9b03', 'ndeb841474810', 'n0dede70ff906',
                  'n42015e37d961'],
    'procedure': ['n690d781e6106', 'n3584dbcda120', 'n6305b4e3cabf', 'n35eb601ddae5',
                  'nbbed5fc388e1', 'nc7da92d02801', 'ne3f008f7c5fd'],
    'life':      ['n490c5918bbc0', 'na4b6b212017a', 'n04d70dacd6bd', 'n1e6a0e54d731',
                  'nd7655beed895', 'n16ebac3b1594'],
    'health':    ['n1ff0c3032fc0', 'ne76a41fe31ee'],
    'online':    ['n45a0835bada6', 'ndca8ccfbcae8', 'n386d808f7535', 'n46618c491d10',
                  'n3d18a4a9d78d', 'nad3b3edd5b3a'],
    'academic':  ['ndd64e74f56c7', 'n280685d12e73', 'n790e19250f29'],
    'activity':  ['n491ac622d20d', 'n3b55242670ab'],
    'about':     ['n35c660733e3c', 'n4c7ddd634fa9', 'n9a854627e103'],
    'misc':      ['n28763e69ba9f', 'n240b8b8daa44', 'na0ee16446457', 'nf782fd3fad87'],
}

CATEGORY_LABEL = {
    'meta':      {'ja': 'ガイドについて',       'order': 0},
    'schedule':  {'ja': 'スケジュール',         'order': 1},
    'pre':       {'ja': '渡航前の準備',         'order': 2},
    'housing':   {'ja': '住まい',               'order': 3},
    'procedure': {'ja': '到着後の手続き',       'order': 4},
    'life':      {'ja': '学内生活・サービス',   'order': 5},
    'health':    {'ja': '医療・健康',           'order': 6},
    'online':    {'ja': 'アプリ・情報源',       'order': 7},
    'academic':  {'ja': '授業・進学・奨学金',   'order': 8},
    'activity':  {'ja': 'サークル・アルバイト', 'order': 9},
    'about':     {'ja': '北京大学について',     'order': 10},
    'misc':      {'ja': 'その他・連絡先',       'order': 11},
}

# ---- 適用条件タグ（編集タグ。その条件の人にだけ関係する記事に限る） ----
TAGS = {
    'ne3f008f7c5fd': {'visa': ['X1']},
    'nbbed5fc388e1': {'visa': ['X1']},
    'ne1cd0ad6011b': {'visa': ['X1']},
    'n14e161185f83': {'housing': ['dorm']},
    'n42015e37d961': {'housing': ['dorm']},
    'n23faa8ef9b03': {'housing': ['rent']},
    'ndeb841474810': {'housing': ['hotel']},
    'n960d0ae94257': {'campus': ['main']},
    'nbebdeb048253': {'campus': ['main']},
    'n280685d12e73': {'program': ['yoka', 'honka', 'grad', 'shinshu']},
    'ndd64e74f56c7': {'program': ['gogaku', 'shinshu', 'gakui']},
}

INLINE = {'strong', 'em', 'br', 'a'}
DROP = {'table-of-contents', 'hr'}      # note の自動目次と区切り線
TOP_LINK = '留学ガイドトップページ'
ATT_HOST = 'note.com/api/v2/attachments/download/'

# ---- 画面に出す画像 ----
# 画像本体は note の外部ホストにあり Artifact の CSP では読めないので、
# 必要なものだけ webp に変換して supporting file として同梱する。
# caption を書くと原文の figcaption より優先する。ビザの図は原文では
# どれも「イメージ画像」で、並べたときにどれがどれだか分からなくなる。
IMAGE_EMBED = {
    'https://assets.st-note.com/img/1787271692-siqWTrKbAcj2uoU0yk5a7ZYV.jpg': {
        'src': 'img/annual-schedule.webp',
        'w': 1536, 'h': 1024,
        'alt': '中国留学（北京大学の例）1年間のスケジュール。'
               '9月入学・7月学年終了で、秋学期（9月〜翌1月上旬）、冬休み（1月中旬〜2月中旬）、'
               '春学期（2月下旬〜7月上旬）、夏休み（7月中旬〜8月末）を月ごとに並べた図。',
    },
    'https://assets.st-note.com/img/1786296681-DQI620K7bZpgkrCnAqWUSteo.jpg': {
        'src': 'img/visa-x1.webp',
        'w': 1107, 'h': 784,
        'caption': 'X1ビザの見本（氏名などの欄は伏せてある）',
        'alt': 'X1ビザの見本。中華人民共和国の入国ビザ（签证 / VISA）のシールで、'
               '種類（M. Category）の欄が「X1」になっている箇所が赤枠で囲ってある。'
               '入国期限・有効期間・入国回数などの欄が並び、下部に'
               '「请于入境之日起30日内申请居留证件（入国の日から30日以内に居留許可を'
               '申請すること）」と書かれている。氏名や番号の欄は見本のため伏せてある。',
    },
    'https://assets.st-note.com/img/1786296699-oewsHvLm8utSNrd7bgXFyD0O.jpg': {
        'src': 'img/visa-x2.webp',
        'w': 1106, 'h': 784,
        'caption': 'X2ビザの見本（氏名などの欄は伏せてある）',
        'alt': 'X2ビザの見本。中華人民共和国の入国ビザ（签证 / VISA）のシールで、'
               '種類（M. Category）の欄が「X2」になっている箇所が赤枠で囲ってある。'
               '様式は X1 と同じで、違うのは種類の欄だけ。'
               '氏名や番号の欄は見本のため伏せてある。',
    },
    'https://assets.st-note.com/img/1786297656-rcaFhjelgDUXKyt2Z1nPm7Jb.jpg': {
        'src': 'img/visa-residence.webp',
        'w': 1258, 'h': 832,
        'caption': '居留許可の見本（氏名などの欄は伏せてある）',
        'alt': '居留許可（中华人民共和国外国人居留许可 / RESIDENCE PERMIT）の見本。'
               'ビザのシールとは別の様式で、居留事由（Residence Category）の欄が'
               '「学習」になっている箇所が赤枠で囲ってある。'
               '性別・生年月日・パスポート番号・有効期限（有效期至）・'
               '発行日（签发日期）・発行地（签发地、見本では北京）・備考の欄が並ぶ。'
               '氏名や番号の欄は見本のため伏せてある。',
    },
    'https://assets.st-note.com/img/1786295638-A7nPFJNWHU0fhxwDKRdLuZvk.png': {
        'src': 'img/visa-x1-x2-flow.webp',
        'w': 1810, 'h': 556,
        'caption': '図：X1／X2と居留許可の関係',
        'alt': 'X1ビザ・X2ビザと居留許可の関係を、渡航前の準備と入国後の手続きに'
               '分けて並べた図。180日以内の短期留学は「X2ビザの申請・取得 → 入国 → '
               'そのまま最大180日間滞在可能（居留許可は不要）。ただし原則として'
               '使い切りのシングルビザ」。180日を超える長期留学は「X1ビザの申請・取得 → '
               '入国 → 30日以内に『学習類居留許可』へ切り替え申請 → 完了すれば'
               '期間内は何度でも出入国自由（マルチ化）」。',
    },
}
# 出さない画像（作者の指示による）
IMAGE_DROP = {
    'https://assets.st-note.com/img/1786111253-HoIzfy0eRO6lFcQ3KrnshVxP.jpg',
}

# ---- 画面に載せない記事 ----
EXCLUDE = {
    # note 版の目次。中身は 45 本すべてが note へのリンクで、
    # このページには独自の分類ナビがあるため載せない。
    'nafe1e8c9b900',
}

# ---- 画面から外す本文ブロック ----
# note プラットフォーム固有の案内（問い合わせ窓口・note 版の更新履歴）。
# 記事の中身ではなく note 上での運用情報なので、このページには出さない。
DROP_TEXT = {
    # 「下記からご連絡ください」は削除した問い合わせ窓口を指す一文なので、
    # 残すと宛先のない案内になる。
    'n75c0b775e9e2': ('質問箱', 'クリエイターへのお問い合わせ', '更新状況等',
                      'PDF版作成・配布', 'note版作成・更新',
                      '下記からご連絡ください'),
}

# note のページへ飛ぶリンク。添付ファイルのダウンロード URL は
# リンクではなく機能なので対象にしない。
NOTE_PAGE_LINK = re.compile(
    r'<a href="https://note\.com/(?!api/v2/attachments/)[^"]*"[^>]*>(.*?)</a>', re.S)

# ---- 編集上の補足（原文ではない。画面上もそう明示する） ----
# 年間スケジュールと新入生スケジュールは扱う範囲が重なるため、
# どちらを見ればよいか記事の先頭で示す。
EDITOR_NOTES = {
    'nbebdeb048253':
        '毎年くり返す学年の流れ（学期・休み・行事）です。'
        '入学までに一度だけ行う準備の流れは「📅 新入生留学スケジュール」に、'
        '手続きの持ち物と前後関係は「手続き」タブにまとめています。',
    'n960d0ae94257':
        '出願から留学修了までの、一度だけ通る流れです。'
        '在学中の毎年の予定は「📅 年間スケジュール（燕園校区／本部）」を、'
        '手続きの持ち物と前後関係は「手続き」タブを見てください。',
}


def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def flat(s):
    """タグを落として空白を詰める。"""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()


def classify_figure(f):
    """<figure> の中身を見て、何として出すかを決める。

    note は figure を画像だけでなく、添付ファイル・外部リンクカード・
    引用（ポイント枠）の入れ物にも使う。一律に画像扱いすると、
    リンクや添付が「画像あり」の空枠になって中身が消える。
    """
    cap_m = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', f, re.S)
    cap = flat(cap_m.group(1)) if cap_m else ''

    # 添付ファイル（PDF・DOC）
    att = re.search(r'href="(https?://[^"]*%s[^"]*)"' % re.escape(ATT_HOST), f)
    if att:
        name_m = re.search(r'<strong>(.*?)</strong>', f, re.S)
        name = flat(name_m.group(1)) if name_m else '添付ファイル'
        size_m = re.search(r'(\d+(?:[.,]\d+)?\s*[KMG]B)', flat(f))
        return {'t': 'att', 'name': name,
                'size': size_m.group(1) if size_m else '',
                'url': att.group(1)}

    # 画像
    img = re.search(r'<img[^>]*src="([^"]+)"', f)
    if img:
        src = img.group(1)
        if src in IMAGE_DROP:
            return None
        known = IMAGE_EMBED.get(src)
        if known:
            b = {'t': 'img', 'src': known['src'], 'alt': known['alt'],
                 'w': known['w'], 'h': known['h'], 'href': src}
            cap = known.get('caption', cap)
            if cap:
                b['caption'] = cap
            return b
        # 画像そのものは収録していない。ここで「図」の枠を出すと、
        # 出てこない画像の抜け殻がページに並ぶ。説明文は本文として
        # 意味を持つ（家賃・面積・手順など）ので段落に落とし、
        # 説明文も無い figure は捨てる。
        return {'t': 'p', 'html': cap} if cap else None

    # 引用（ポイント枠）。中にリンクが入っていることもあるので、
    # リンクカードより先に判定する。
    if re.search(r'<blockquote', f):
        return {'t': '_inner'}

    # 外部リンクカード
    a = re.search(r'href="(https?://[^"]+)"', f)
    if a:
        title_m = re.search(r'<strong>(.*?)</strong>', f, re.S)
        title = flat(title_m.group(1)) if title_m else ''
        site = ''
        for e in reversed(re.findall(r'<em>(.*?)</em>', f, re.S)):
            e = flat(e)
            if e:
                site = e
                break
        return {'t': 'card', 'title': title or site or a.group(1),
                'site': site, 'url': a.group(1)}

    return None      # 中身のない figure は捨てる


def preprocess_figures(body):
    """figure を分類し、本文からはコメント印に置き換えて取り出す。"""
    figs = []

    def repl(m):
        f = m.group(0)
        info = classify_figure(f)
        if info is None:
            return ''
        if info['t'] == '_inner':
            bq = re.search(r'<blockquote.*?</blockquote>', f, re.S)
            return bq.group(0) if bq else ''
        figs.append(info)
        return '<!--FIG%d-->' % (len(figs) - 1)

    return re.sub(r'<figure.*?</figure>', repl, body, flags=re.S), figs


class Body(HTMLParser):
    """note 本文の HTML を段落・箇条書き・見出しに復元する。

    インライン要素は strong / em / br / a のみ残す。a は http(s) だけ。
    """

    def __init__(self, figs=None):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.blocks = []
        self.buf = []
        self.astack = []
        self.list = None          # {'ordered': bool, 'items': [...]}
        self.depth_li = 0
        self.in_quote = False
        self.heading = None       # pending heading level
        self.figs = figs or []    # preprocess_figures が取り出した figure

    # -- inline buffer --
    def _take(self):
        s = ''.join(self.buf)
        self.buf = []
        s = re.sub(r'[ \t\r\n]+', ' ', s)
        s = re.sub(r'(?:\s*<br>\s*)+$', '', s)
        s = re.sub(r'^(?:\s*<br>\s*)+', '', s)
        s = re.sub(r'(?:\s*<br>\s*){2,}', '<br>', s)
        return s.strip()

    def _flush_text(self):
        """バッファを段落（または箇条書きの項目）として確定する。"""
        s = self._take()
        if not s:
            return
        if self.heading is not None:
            self.blocks.append({'t': 'h', 'level': self.heading, 'html': s})
            self.heading = None
        elif self.list is not None and self.depth_li > 0:
            self.list['items'].append(s)
        elif self.in_quote:
            self.blocks.append({'t': 'quote', 'html': s})
        else:
            self.blocks.append({'t': 'p', 'html': s})

    def _close_list(self):
        if self.list is not None:
            if self.list['items']:
                self.blocks.append({'t': 'list', 'ordered': self.list['ordered'],
                                    'items': self.list['items']})
            self.list = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('strong', 'em'):
            self.buf.append('<%s>' % tag)
        elif tag == 'br':
            self.buf.append('<br>')
        elif tag == 'a':
            href = a.get('href', '') or ''
            if re.match(r'^https?://', href):
                self.buf.append('<a href="%s" target="_blank" rel="noopener">' % esc(href))
                self.astack.append(True)
            else:
                self.astack.append(False)
        elif tag in ('h2', 'h3'):
            self._flush_text()
            self._close_list()
            self.heading = 2 if tag == 'h2' else 3
        elif tag in ('ul', 'ol'):
            self._flush_text()
            self._close_list()
            self.list = {'ordered': tag == 'ol', 'items': []}
        elif tag == 'li':
            self._flush_text()
            self.depth_li += 1
        elif tag == 'p':
            # li の中の p は項目本体なので、段落として切り出さない
            if self.depth_li == 0:
                self._flush_text()
        elif tag == 'blockquote':
            self._flush_text()
            self._close_list()
            self.in_quote = True
        elif tag in DROP:
            self._flush_text()
            self._close_list()

    def handle_endtag(self, tag):
        if tag in ('strong', 'em'):
            self.buf.append('</%s>' % tag)
        elif tag == 'a':
            if self.astack and self.astack.pop():
                self.buf.append('</a>')
        elif tag in ('h2', 'h3'):
            self._flush_text()
        elif tag == 'li':
            self._flush_text()
            self.depth_li = max(0, self.depth_li - 1)
        elif tag in ('ul', 'ol'):
            self._flush_text()
            self._close_list()
        elif tag == 'p':
            self._flush_text()
        elif tag == 'blockquote':
            self._flush_text()
            self.in_quote = False

    def handle_data(self, data):
        self.buf.append(esc(data))

    def handle_comment(self, data):
        """preprocess_figures が置いた figure の印を、その位置に差し込む。"""
        m = re.match(r'^FIG(\d+)$', data.strip())
        if not m:
            return
        self._flush_text()
        self._close_list()
        i = int(m.group(1))
        if 0 <= i < len(self.figs):
            self.blocks.append(self.figs[i])

    def finish(self):
        self._flush_text()
        self._close_list()
        return self.blocks


def strip_tags(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()


def unesc(s):
    return (s.replace('&amp;', '&').replace('&lt;', '<')
             .replace('&gt;', '>').replace('&quot;', '"'))


WARN_MARK = re.compile(r'^(?:⚠|❗|‼)️?\s*')
TIP_MARK = re.compile(r'^(?:\U0001f4a1|⭐|\U0001f449|☝)️?\s*')


def mark_of(html):
    t = strip_tags(html)
    if WARN_MARK.match(t):
        return 'warn'
    if TIP_MARK.match(t):
        return 'tip'
    return None


def split_callouts(blocks):
    """段落に <br> で詰め込まれた ⚠️・⭐️ の一言を独立した注記にする。

    note では注意書きが一つの段落に改行で並んでいることが多く、そのまま
    出すと本文に埋もれる。記号付きの断片が一つでもあれば分割する。
    """
    out = []
    for b in blocks:
        if b['t'] != 'p':
            out.append(b)
            continue
        parts = [p.strip() for p in b['html'].split('<br>')]
        parts = [p for p in parts if p]
        if not any(mark_of(p) for p in parts):
            out.append(b)
            continue
        for p in parts:
            kind = mark_of(p)
            if kind:
                out.append({'t': 'note', 'kind': kind, 'html': p})
            else:
                out.append({'t': 'p', 'html': p})
    return out


# 「時期：内容」形式の項目。note では太字の位置が三通りある。
KV_FORMS = (
    r'^<strong>([^：:<]{1,26})[：:]\s*</strong>\s*(.+)$',   # <strong>キー：</strong>値
    r'^<strong>([^：:<]{1,26})</strong>\s*[：:]\s*(.+)$',   # <strong>キー</strong>：値
    r'^([^：:<]{1,26})[：:]\s*(.+)$',                        # キー：値
)


def split_kv(item):
    for pat in KV_FORMS:
        m = re.match(pat, item)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if key and val:
                return key, val
    return None


def strong_labels(blocks):
    """段落まるごとが太字の短い行は、原文が小見出しとして使っている。

    h2 / h3 の下にもう一段の区切りを太字で作っているため、本文の段落と
    同じ見た目にすると、その下の箇条書きがどこに属するのか分からない。
    長い強調文を巻き込まないよう、短いものだけに限る。
    """
    out = []
    for b in blocks:
        if b['t'] == 'p':
            m = re.match(r'^<strong>(.*)</strong>$', b['html'], re.S)
            if m and '<strong>' not in m.group(1) and 0 < len(flat(m.group(1))) <= 42:
                out.append({'t': 'label', 'html': m.group(1)})
                continue
        out.append(b)
    return out


def kv_lists(blocks):
    """「時期：内容」が並ぶ箇条書きを定義リストに変える。

    元記事は月別の予定や窓口の一覧を「キー：値」の箇条書きで書いている。
    そのまま点を打って並べるとキーと値が地の文に混ざるので、二列に組む。
    半端に一項目だけ変えると逆に読みにくいので、過半数が該当する場合だけ。
    """
    out = []
    for b in blocks:
        if b['t'] != 'list' or b.get('ordered') or len(b['items']) < 2:
            out.append(b)
            continue
        pairs = [split_kv(i) for i in b['items']]
        hit = [p for p in pairs if p]
        if len(hit) < 2 or len(hit) * 10 < len(pairs) * 6:
            out.append(b)
            continue
        rows = []
        for item, pair in zip(b['items'], pairs):
            if pair:
                rows.append({'k': pair[0], 'v': pair[1]})
            else:
                rows.append({'v': item})       # キーが無い行は値だけ
        out.append({'t': 'dl', 'rows': rows})
    return out


def latex_table(html):
    """note の数式機能で書かれた \\begin{array} を表の行列に戻す。

    元記事では授業時間割がこの形で書かれている。そのまま出すと生の
    LaTeX が並ぶので、行と列に戻して表として組む。セルの文字は変えず、
    行と列の並びも元のままにする。
    """
    s = re.sub(r'<[^>]+>', '\n', html).replace('&amp;', '&')
    m = re.search(r'\\begin\{array\}(?:\{[^}]*\})?(.*?)\\end\{array\}', s, re.S)
    if not m:
        return None
    body = m.group(1).replace('\\hline', ' ')
    rows = []
    for raw in body.split('\\\\'):
        cells = [c.strip() for c in raw.split('&')]
        cells = [re.sub(r'^\\text\s*\{(.*)\}$', r'\1', c).strip() for c in cells]
        if any(cells):
            rows.append(cells)
    return rows or None


def convert_tables(blocks):
    out = []
    for b in blocks:
        if b['t'] == 'p' and '\\begin{array}' in b['html']:
            rows = latex_table(b['html'])
            if rows:
                out.append({'t': 'table', 'rows': rows})
                continue
        out.append(b)
    return out


def strip_note_links(html):
    """note のページへ飛ぶリンクを外す。文字は残す。"""
    def repl(m):
        inner = m.group(1)
        # リンク文字が URL そのものなら、外すと裸の URL が残るだけなので消す
        if re.match(r'^https?://', flat(inner)):
            return ''
        return inner
    return NOTE_PAGE_LINK.sub(repl, html)


def clean_blocks(blocks, aid):
    """note へのリンクを外し、note 固有の案内ブロックを落とす。"""
    drop = DROP_TEXT.get(aid, ())
    out = []
    for b in blocks:
        b = dict(b)
        if b['t'] in ('p', 'label', 'note', 'quote'):
            b['html'] = strip_note_links(b['html'])
            if not flat(b['html']):
                continue
        elif b['t'] == 'list':
            # 除外は項目ごとに判定する。箇条書きまるごとを落とすと、
            # 同じリストに並んだ免責事項まで一緒に消える。
            items = []
            for i in b['items']:
                i = strip_note_links(i)
                if not flat(i):
                    continue
                if drop and any(k in i for k in drop):
                    continue
                items.append(i)
            if not items:
                continue
            b['items'] = items
        elif b['t'] == 'dl':
            rows = []
            for r in b['rows']:
                r = dict(r)
                r['v'] = strip_note_links(r['v'])
                if flat(r['v']) or r.get('k'):
                    rows.append(r)
            if not rows:
                continue
            b['rows'] = rows
        elif b['t'] == 'card':
            # note のページを指すカードは外す（添付ファイルは att なので残る）
            if re.match(r'^https://note\.com/(?!api/v2/attachments/)', b['url']):
                continue

        # 箇条書きは項目ごとに上で判定済み
        if drop and b['t'] != 'list':
            text = json.dumps(b, ensure_ascii=False)
            if any(k in text for k in drop):
                continue
        out.append(b)
    return out


def to_sections(blocks):
    """見出しを境にセクションへ束ねる。先頭の前文は heading なしのセクション。"""
    secs = []
    cur = {'heading': None, 'level': 0, 'blocks': []}
    for b in blocks:
        if b['t'] == 'h':
            if cur['blocks'] or cur['heading']:
                secs.append(cur)
            cur = {'heading': strip_tags(b['html']), 'level': b['level'], 'blocks': []}
        else:
            cur['blocks'].append(b)
    if cur['blocks'] or cur['heading']:
        secs.append(cur)

    # 末尾のガイド内リンク（「📖留学ガイドトップページ」）は落とす
    for s in secs:
        s['blocks'] = [b for b in s['blocks']
                       if not (b['t'] == 'p' and TOP_LINK in strip_tags(b['html']))]
        if s['blocks'] or s['heading']:
            continue
    return [s for s in secs if s['blocks'] or s['heading']]


def plain_text(secs):
    """検索用の素のテキスト。"""
    out = []
    for s in secs:
        if s['heading']:
            out.append(s['heading'])
        for b in s['blocks']:
            if b['t'] in ('p', 'quote', 'note', 'label'):
                out.append(unesc(strip_tags(b['html'])))
            elif b['t'] == 'list':
                out.extend(unesc(strip_tags(i)) for i in b['items'])
            elif b['t'] == 'table':
                for row in b['rows']:
                    out.append(' '.join(row))
            elif b['t'] == 'dl':
                for r in b['rows']:
                    out.append(((r.get('k', '') + '：') if r.get('k') else '')
                               + unesc(strip_tags(r['v'])))
            elif b['t'] == 'att':
                out.append(b['name'])
            elif b['t'] == 'card':
                out.append(b['title'] + ' ' + b.get('site', ''))
            elif b['t'] == 'img':
                out.append(b.get('caption') or b['alt'])
    return '\n'.join(out)


def main():
    with io.open(SRC_INV, encoding='utf-8') as f:
        inv = json.load(f)

    cat_of = {}
    for cat, ids in CATEGORY.items():
        for i in ids:
            cat_of[i] = cat
    inv = [a for a in inv if a['id'] not in EXCLUDE]
    missing = [a['id'] for a in inv if a['id'] not in cat_of]
    if missing:
        raise SystemExit('分類が未割り当ての記事: %s' % missing)

    articles = []
    stat = {'p': 0, 'list': 0, 'items': 0, 'fig': 0, 'quote': 0, 'h2': 0, 'h3': 0}

    for a in inv:
        apath = os.path.join(SRC_API, a['id'] + '.json')
        if not os.path.exists(apath):
            raise SystemExit('本文 HTML がありません: %s' % a['id'])
        with io.open(apath, encoding='utf-8') as f:
            body = (json.load(f).get('data') or {}).get('body') or ''
        if not body.strip():
            raise SystemExit('本文が空です: %s' % a['id'])

        body, figs = preprocess_figures(body)
        parser = Body(figs)
        parser.feed(body)
        secs = to_sections(clean_blocks(strong_labels(
            kv_lists(convert_tables(split_callouts(parser.finish())))), a['id']))
        plain = plain_text(secs)

        for s in secs:
            if s['level'] == 2:
                stat['h2'] += 1
            elif s['level'] == 3:
                stat['h3'] += 1
            for b in s['blocks']:
                if b['t'] == 'list':
                    stat['list'] += 1
                    stat['items'] += len(b['items'])
                else:
                    stat[b['t']] = stat.get(b['t'], 0) + 1

        title = re.sub(r'｜pku_guide_jp$', '', a.get('title') or '').strip()
        if not title:
            title = (a.get('directory_title') or a['id']).strip()

        articles.append({
            'id': a['id'],
            # 原文 URL は出力しない。note へ飛ぶ機能を置かないため画面では
            # 使わず、出典の追跡は SOURCE_INVENTORY.md と materials/ が持つ。
            'title': title,
            'directoryTitle': (a.get('directory_title') or '').strip(),
            'category': cat_of[a['id']],
            'tags': TAGS.get(a['id'], {}),
            'editorNote': EDITOR_NOTES.get(a['id'], ''),
            'published': (a.get('published') or '')[:10],
            'modified': (a.get('modified') or '')[:10],
            'chars': len(plain),
            'sections': secs,
            # plain は検索用だが本文と重複して容量が倍になるので保存しない。
            # 画面側で起動時に一度組み立てる。
            'wip': ('整理中' in plain or '準備中' in plain
                    or '整理中' in (a.get('directory_title') or '')),
        })

    articles.sort(key=lambda x: (CATEGORY_LABEL[x['category']]['order'], x['title']))

    out = {
        'generated': '2026-09-17',
        'sourceName': '北京大学留学ガイド（非公式・参考版）',
        'sourceBy': '留学経験者の有志（pku_guide_jp）',
        'sourceNote': '本文は掲載時点の文章をそのまま収録。',
        'categories': [
            {'key': k, 'label': v['ja'], 'order': v['order']}
            for k, v in sorted(CATEGORY_LABEL.items(), key=lambda kv: kv[1]['order'])
        ],
        'articles': articles,
    }
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    print('articles   :', len(articles))
    print('sections   :', sum(len(x['sections']) for x in articles))
    print('blocks     : 段落 %d / 箇条書き %d（項目 %d）/ 定義リスト %d / 注記 %d'
          % (stat['p'], stat['list'], stat['items'], stat.get('dl', 0),
             stat.get('note', 0)))
    print('             小見出し %d / 表 %d / 画像 %d / 添付 %d / リンクカード %d / 引用 %d'
          % (stat.get('label', 0), stat.get('table', 0), stat.get('img', 0),
             stat.get('att', 0), stat.get('card', 0), stat['quote']))
    print('headings   : h2 %d / h3 %d' % (stat['h2'], stat['h3']))
    print('wip        :', [x['id'] for x in articles if x['wip']])
    print('no modified:', [x['id'] for x in articles if not x['modified']])
    print('bytes      :', '{:,}'.format(os.path.getsize(OUT)))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
