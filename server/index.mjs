/**
 * 「燕園手続きナビ」の質問応答の代理サーバ。
 *
 * 画面から受け取るのは「質問」「利用者の条件」「検索で選ばれた小節の id」
 * だけで、本文と指示はこちら側が持つ。こうすることで
 *   - API キーがブラウザに出ない
 *   - 画面側から指示や資料を差し替えられない（無関係な用途の代理に使えない）
 * という二つを同時に満たす。
 *
 * アリババクラウド関数計算（FC 3.0）の **Web 関数** として置く想定。
 * Web 関数だけが SSE の流し込みに対応する（イベント関数は非対応）。
 * 標準の node:http だけで書いてあるので、ローカルでもそのまま動く。
 *
 * 必要な環境変数:
 *   DASHSCOPE_API_KEY   百煉（Model Studio）の API キー
 *   DASHSCOPE_BASE_URL  例: https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
 *                       ※キーは作成したリージョンの base_url と組で使う
 *   MODEL               既定 qwen3.7-plus
 *   ALLOW_ORIGIN        配備したページの生成元。既定 * （本番では必ず指定する）
 */

import http from "node:http";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DOCS = JSON.parse(readFileSync(join(HERE, "docs.json"), "utf8"));

const API_KEY = process.env.DASHSCOPE_API_KEY || "";
const BASE_URL = (process.env.DASHSCOPE_BASE_URL || "").replace(/\/+$/, "");
const MODEL = process.env.MODEL || "qwen3.7-plus";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";
const PORT = process.env.FC_SERVER_PORT || process.env.PORT || 9000;

/* 資料の分量の上限。上位12件でも普段は 3,000〜6,500 字だが、
   体检の「中国各地域の国际旅行卫生保健中心」だけで 3,000 字あるので、
   積み上げが膨らんだときに切る。 */
const MAX_DOC_CHARS = 12000;
const MAX_QUESTION = 400;
const MAX_IDS = 20;

const PROFILE_FIELDS = {
  visa: { X1: "X1（180日以上・2学期以上）", X2: "X2（180日未満・1学期）" },
  housing: {
    dorm: "大学の留学生寮", rent: "学外の賃貸物件",
    hotel: "ホテル", family: "親戚・友人知人宅",
  },
  program: {
    gogaku: "語学進修生（対外漢語）", shinshu: "その他の進修生",
    exchange: "交換留学", honka: "本科（学部）",
    grad: "大学院（修士・博士）", yoka: "予科",
  },
};

const RULES = readFileSync(join(HERE, "rules.txt"), "utf8").trim();

function profileText(p) {
  const lines = [];
  for (const [key, table] of Object.entries(PROFILE_FIELDS)) {
    const v = p && typeof p[key] === "string" ? p[key] : "unknown";
    const label = { visa: "ビザ", housing: "住まい", program: "プログラム" }[key];
    lines.push(`- ${label}: ${table[v] || "まだ分からない（未選択）"}`);
  }
  return lines.join("\n");
}

function buildPrompt(question, profile, ids) {
  const picked = [];
  let chars = 0;
  let dropped = 0;
  for (const id of ids) {
    const d = DOCS[id];
    if (!d) continue;
    const piece = `${d.label}${d.updated ? `（資料の更新日 ${d.updated}）` : ""}\n${d.body}`;
    if (chars + piece.length > MAX_DOC_CHARS && picked.length) {
      dropped++;
      continue;
    }
    chars += piece.length;
    picked.push(`[S${picked.length + 1}] ${piece}`);
  }
  const note = dropped ? `\n（分量の都合で ${dropped} 件は省略しています）` : "";
  return {
    prompt: `${RULES}

# 利用者の条件
${profileText(profile)}

# 資料
${picked.join("\n\n")}${note}

# 質問
${question}`,
    used: picked.length,
  };
}

/* 粗い連打止め。FC は実例が複数立つのでこれは気休めで、
   本気で守るなら API ゲートウェイ側で絞る。 */
const seen = new Map();
function allow(ip, max = 20, windowMs = 60000) {
  const now = Date.now();
  const arr = (seen.get(ip) || []).filter((t) => now - t < windowMs);
  if (arr.length >= max) {
    seen.set(ip, arr);
    return false;
  }
  arr.push(now);
  seen.set(ip, arr);
  if (seen.size > 5000) seen.clear();
  return true;
}

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", ALLOW_ORIGIN);
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Vary", "Origin");
}

function fail(res, status, code) {
  cors(res);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: code }));
}

function readBody(req, limit = 65536) {
  return new Promise((resolve, reject) => {
    let n = 0;
    const chunks = [];
    req.on("data", (c) => {
      n += c.length;
      if (n > limit) {
        reject(Object.assign(new Error("too large"), { code: "too_long" }));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function handleAsk(req, res) {
  if (!API_KEY || !BASE_URL) return fail(res, 500, "unauthorized");

  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim()
    || req.socket.remoteAddress || "?";
  if (!allow(ip)) return fail(res, 429, "rate_limited");

  let body;
  try {
    body = JSON.parse(await readBody(req));
  } catch (e) {
    return fail(res, e?.code === "too_long" ? 413 : 400, e?.code || "bad_request");
  }

  const question = typeof body.question === "string" ? body.question.trim() : "";
  if (!question) return fail(res, 400, "bad_request");
  if (question.length > MAX_QUESTION) return fail(res, 413, "too_long");

  const ids = Array.isArray(body.sectionIds)
    ? body.sectionIds.filter((x) => typeof x === "string").slice(0, MAX_IDS)
    : [];
  const known = ids.filter((id) => DOCS[id]);
  if (!known.length) return fail(res, 400, "no_sections");

  const { prompt } = buildPrompt(question, body.profile, known);
  const history = Array.isArray(body.history) ? body.history.slice(-6) : [];
  const messages = history
    .filter((m) => m && ["user", "assistant"].includes(m.role) && typeof m.content === "string")
    .map((m) => ({ role: m.role, content: m.content.slice(0, 2400) }));
  messages.push({ role: "user", content: prompt });

  let upstream;
  try {
    upstream = await fetch(`${BASE_URL}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL,
        stream: true,
        temperature: 0.2,      /* 手続きの話なので揺らさない */
        max_tokens: 1200,
        messages,
      }),
    });
  } catch {
    return fail(res, 502, "upstream");
  }

  if (!upstream.ok || !upstream.body) {
    const status = upstream.status === 429 ? 429
      : upstream.status === 401 || upstream.status === 403 ? 401 : 502;
    const code = status === 429 ? "rate_limited"
      : status === 401 ? "unauthorized" : "upstream";
    return fail(res, status, code);
  }

  cors(res);
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    /* FC はこのヘッダを見て流し込みと判断する */
    "Transfer-Encoding": "chunked",
    "X-Accel-Buffering": "no",
  });

  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
  const reader = upstream.body.getReader();
  const dec = new TextDecoder();
  let buf = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const raw of lines) {
        const line = raw.trim();
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        let j;
        try { j = JSON.parse(payload); } catch { continue; }
        const piece = j?.choices?.[0]?.delta?.content;
        if (piece) send({ delta: piece });
      }
    }
  } catch {
    send({ error: "upstream" });
  }
  res.write("data: [DONE]\n\n");
  res.end();
}

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") {
    cors(res);
    res.writeHead(204);
    res.end();
    return;
  }
  if (req.method === "GET" && (req.url === "/health" || req.url === "/")) {
    cors(res);
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({
      ok: true,
      docs: Object.keys(DOCS).length,
      model: MODEL,
      configured: Boolean(API_KEY && BASE_URL),
    }));
    return;
  }
  if (req.method !== "POST") return fail(res, 405, "bad_request");
  handleAsk(req, res).catch(() => fail(res, 500, "upstream"));
});

server.listen(PORT, () => {
  console.log(`listening on ${PORT} / docs=${Object.keys(DOCS).length} / model=${MODEL}`);
});
