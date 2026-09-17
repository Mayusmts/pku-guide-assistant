# 问答的代理服务端

从页面（`app/index.html`）接收提问，附上资料投给千问（阿里云百炼），再把答案用 SSE 流式返回。

日文版说明：[README.ja.md](README.ja.md)

## 为什么要隔一层代理

**API 密钥不能放在浏览器里。** 只为这一点的话，简单转发就够了；但如果只是转发，页面侧就能随意替换指令文和资料，从而被人当成免费的 LLM 代理挪作他用。所以把职责这样划分：

| | 持有的东西 |
|---|---|
| 页面侧 | 只有检索（判断哪些小节相关）。发送的是**提问、用户的条件、小节的 id** |
| 代理侧 | API 密钥、资料正文（`docs.json`）、指令文（`RULES`） |

页面只能发送 id，因此无法让模型读到资料以外的文本。指令文也无法被替换。

## 先在本地跑起来（无需 Node）

`local.py` 把页面和代理由同一个服务端提供。因为是同源的，CORS 和 Artifact 的 CSP 都不再相关，而密钥**只有这个进程**持有。仅用 Python 标准库即可运行。

PowerShell:

```
$env:DASHSCOPE_API_KEY  = "sk-..."
$env:DASHSCOPE_BASE_URL = "https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
python server/local.py
```

→ 打开 `http://127.0.0.1:8787/`。启动时会显示密钥是否已配置（只显示后 4 位，密钥全文不会写出到任何地方）。监听地址固定为 `127.0.0.1`，要放到局域网必须显式指定 `--host`。

`app/index.html` 分发时 `AI_ENDPOINT` 可以保持为空，由 `local.py` 在返回时注入 `/ask`。所以 Artifact 版和本地版不需要生成两种产物。

不配置密钥直接启动也可以正常使用检索标签页（只是不显示 AI 那一栏）。

## 组装

```
npm run build:docs     # 在项目根目录执行 python build_docs.py
```

`server/docs.json`（588 条・约 476KB）由 `app/data/guide.json` 与 `app/data/tasks.json` 生成。它与页面侧检索采用相同的单位和相同的 id，所以前后不会对不上。**资料更新后必须重新生成。**

## 环境变量

| 名称 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 百炼（Model Studio）的 API 密钥 |
| `DASHSCOPE_BASE_URL` | `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| `MODEL` | 默认 `qwen3.7-plus` |
| `ALLOW_ORIGIN` | 已部署页面的来源。默认 `*`。**生产环境必须显式指定** |

`WorkspaceId`（业务空间 ID）在百炼控制台查看。**API 密钥必须与创建它的地域的 `base_url` 配套使用**（在北京创建的密钥不能用于东京的 base_url）。地域按用户所在位置选择：在校期间选北京（`cn-beijing`），如果多数是渡航前从日本访问则选东京（`ap-northeast-1`）。

## 部署（阿里云函数计算 FC 3.0）

**必须创建成「Web 函数」。** 支持 SSE 流式返回的只有 Web 函数，事件函数不会流式输出（会一直无响应直到答案生成完毕）。

1. 运行时选 Node.js 20 以上，类型选 **Web 函数**
2. 上传 `server/` 里的四个文件（`index.mjs` / `docs.json` / `rules.txt` / `package.json`）
   —— `rules.txt` 漏了的话，函数启动时读不到指令文会直接崩溃
3. 启动命令 `node index.mjs`，监听端口 `9000`
4. 配置上面的环境变量
5. 添加 HTTP 触发器，以无认证（`anonymous`）方式公开
6. 把分配到的 URL 交给构建侧（**不改源码**）：

   - 本地重新生成：`$env:AI_ENDPOINT = "https://<函数URL>"; python build_app.py`
   - GitHub Pages：在仓库 *Settings → Secrets and variables → Actions → Variables*
     新建变量 `AI_ENDPOINT`，值为同一个 URL。之后每次部署都会自动注入

   `AI_ENDPOINT` 不是密钥，它只是公网地址；密钥只存在于 FC 的环境变量里。
   不设这个变量时生成的是纯检索版，Agent 栏显示「まだ接続されていません」。

   `ALLOW_ORIGIN` 必须设成页面的来源。用 GitHub Pages 时是
   `https://mayusmts.github.io`（**只有协议+主机名，不带仓库路径**，浏览器
   发送的 `Origin` 头就是这个形式）。

确认方法：`curl <URL>/health` 返回 `{"ok":true,"configured":true,...}` 即可。

`index.mjs`（Node 版）与 `local.py`（Python 版）读取同一份 `rules.txt` 和 `docs.json`，因此指令文和资料可以在一处统一管理。分工是：本地试用跑 `local.py`，给大家用则把 `index.mjs` 放到 FC 上。

## 输入限制（滥用对策）

- 提问最多 400 字，请求体整体最多 8KB
- 小节 id 最多 20 个，`docs.json` 里没有的 id 一律丢弃
- 资料总量在 12,000 字处截断（光是体检那篇的全国保健中心一览就有 3,000 字）
- 同一 IP 每分钟最多 20 次

**这个连点限制是在内存里的，聊胜于无。** FC 会起多个实例，各自分开计数。要真正限制住，应该在 API 网关或 WAF 那一侧做。在扩大公开范围之前，必须连同 `ALLOW_ORIGIN` 的配置一起重新审视。

## 答案的生成方式（`RULES`）

把资料本身的性质所带来的约束固定写进了指令文。

- 只用传过去的资料作答。没有的就不推测，回答「提供された資料では確認できません」（所提供的资料中无法确认）
- 在此基础上，如果有相近的信息可以给出引导（作者的意向：*相关信息和文章可以给出，但没有确证的信息不要给*）
- 必须附上依据编号 `[S1]`。**页面侧只会把传过去的那些编号转换成跳转目标**，因此模型无法编造引用来源。超出范围的编号会显示为虚线的无效标记
- 不把「非官方」这件事写成断定表述
- 费用、日期、窗口时间要注明是资料在某个时点的信息
- 资料之间有出入时同时给出两边（住宿登记的 URL 等确实存在出入）
- 会随用户条件（签证／住处／项目）变化的手续，按条件给出对应的答案

`temperature: 0.2`。办手续的事，措辞摇摆没有好处。

## 已确认 / 尚未确认

`local.py` 在本环境启动后，实测了以下各项。

- `/health` 能读到 588 条资料
- `/` 能返回页面，并且 `AI_ENDPOINT` 被注入了 `/ask`
- 输入校验：空提问→400、超过 400 字→413、未知 id→400、无 id→400
- 未配置密钥→500 `unauthorized`
- 连续提交不会破坏 keep-alive（在读完请求体之前就响应会导致连接重置，因此用 `_drain` 确保读完丢弃后再返回）
- prompt 的组装（用户条件、资料编号、更新日都会进去）
- **与上游（qwen3.7-plus）的往返以及 SSE 流式返回**（2026-09-17）。把密钥放进环境变量后实际提问，一直跑到答案流式返回为止。

**尚未确认。**

- **`index.mjs`（Node 版）没有实际运行过。** 此环境没有 Node，只做到了语法的目视确认。上到 FC 后用 `curl <URL>/health` 确认 `configured:true`。
- **实际的应答质量没有测量。** 检索侧用 12 道自制题测得 recall@8 = 12/12，但答案的正确性、引用的妥当性、以及该说「不知道」的场合能否说出来，都未评估。公开前应通过 `MATERIALS_REVIEW.md` 的验收标准（含资料缺失、条件不明、来源冲突、范围外的题目）。
- 费用（token 计费）的实测。
