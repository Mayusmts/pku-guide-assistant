import json
from pathlib import Path
from bs4 import BeautifulSoup

r = json.loads(Path('materials/inventory.json').read_text(encoding='utf-8'))
audiences = [
'全体读者', '燕园校区／本部学生', '本部新生；正文明确排除医学部', '前往北京大学及在京出行者',
'在日本申请中国留学签证者；区分 X1/X2', '需体检或认证者；居留许可、奖学金等条件分别适用',
'准备赴华留学者；按时长和材料状况区分', '准备赴华留学者；按项目区分费用',
'拟住中关新园、勺园等宿舍者；特殊项目有例外', '选择校外租房者', '临时或长期住酒店者及来访者',
'初到北京大学的新生', '住寮、租房、酒店或亲友家者；办理方式不同', '北京大学新生；按项目和年份区分',
'需中国手机号的留学生；学生套餐需资格材料', '需中国银行账户者；短期学生和奖学金领取者有额外条件',
'申请居留许可、需体检或认证者；正文重点为 X1', '来华留学生；具体承保范围待附件核实',
'正文限定 X1 长期留学者', '中关新园住户；其他宿舍不能直接套用', '在籍学生及访客；两种 WiFi 分开',
'在京生活的留学生', '在华就医者；非诊断依据', '需理解药品名称者；非用药指导',
'需查教室和院系信息的学生', '校园设施使用者；资格依设施而异', '校园购物者', '校园就餐者；支付和准入条件需区分',
'在校学生、教职工；依平台权限区分', '在校学生；部分应用状态不确定', '有大学软件及网络使用资格者',
'需关注校园通知者', '语学进修生、其他进修生及学位生；不能混用选课规则', '予科、本科、研究生、进修申请者',
'奖学金申请者及在校生；按项目资格区分', '希望参加社团的学生', '希望实习或勤工助学的留学生；身份条件需核实',
'希望了解北京大学者', '希望了解北京大学历史者', '希望了解校园文化、设施和人物者',
'留学生及部分访华、短期停留者；逐段判断适用性', '需要机构联系方式者；部分仅适用日本国籍者',
'需关注大学及在华信息者', '需要中国相关网站入口者', '在京生活、关注空气质量者', '全体指南读者（目录入口）']
lines = ['# 资料逐篇清单', '', '检查日期：2026-09-17。共 46 页：目录 1 页、使用说明 1 篇、主题文章 44 篇。', '',
'日期来自页面 JSON-LD 的 datePublished / dateModified，保留页面 +09:00 日期；不是政策生效日，也不代表内容已被官方核实。完整时间戳见 inventory.json。', '',
'下表“适用人群”是依据正文主题与条件整理的编辑标签，不是作者统一声明，未明示处仍需逐段确认。所有页面均为 pku_guide_jp 非官方指南；文中链接到官方机构不改变本文来源性质。', '',
'“正文已取”指已取得网页正文区域的可见文本，不包括图片内文字、PDF/DOC 附件或外链全文，不代表已逐条验证事实。HTML 含表格结构；TXT 是阅读用文本，不宜直接作为最终引用分段。', '',
'|文章标题／来源|发布日期|更新日期|适用人群（整理）|性质／读取状态|本地文本|', '|---|---|---|---|---|---|']
assets = []
for x, audience in zip(r,audiences):
    meta = next(y for z in x['metadata'] for y in z.get('@graph',[]) if y.get('@type')=='BlogPosting')
    status = '目录，不能作为手续正文' if x['id']=='nafe1e8c9b900' else '正文已取'
    if x['id']=='n75c0b775e9e2': status='使用说明已取'
    if '整理中' in x['text'] or '整理中' in x['title']: status += '；含整理中标记'
    if x['id']=='n46618c491d10': status += '；部分条目仅名称／省略号'
    x.update(audience_editorial=audience,source_type='非官方留学经验指南',read_status=status,checked_on='2026-09-17',published=meta.get('datePublished'),modified=meta.get('dateModified'))
    title=meta['headline'].replace('|','／')
    lines.append(f"|[{title}]({x['url']})|{x['published'][:10]}|{x['modified'][:10]}|{audience}|非官方；{status}|[{x['id']}](materials/{x['id']}.txt)|")
    soup=BeautifulSoup(Path('materials',x['id']+'.html').read_text(encoding='utf-8'),'html.parser')
    body=soup.select_one('.note-common-styles__textnote-body')
    for a in body.select('a[href]'):
        url=a['href']
        if any(ext in url.lower() for ext in ['.pdf','.doc','.xls','.zip']) or 'assets.st-note.com' in url:
            assets.append(dict(article=x['url'],label=a.get_text(' ',strip=True),url=url,status='未读取附件内容'))
Path('SOURCE_INVENTORY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
Path('materials/inventory.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
Path('materials/unread_attachments.json').write_text(json.dumps(assets,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Inventory: {len(r)} pages; attachment links: {len(assets)}')
