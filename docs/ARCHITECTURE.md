# Voice Action Gate · 架构

> 🇬🇧 **English readers: start at [§0 · English Summary](#0--english-summary).**
> It is self-contained — design, evidence status, and the limits this project does not claim.

> 🔴 **净室声明。** 本设计的**方法**借鉴了我们此前做过的确定性闸,
> **实现从零写,一行代码都不搬。** 本文件描述的是这个作品自己的结构。
>
> 🔴 **本文件里每一条断言都必须落在下面「§6 证据状态」表里的某一行。**
> 表里标 `假设` 的,正文措辞一律用「设计意图是」,**不写「不可能 / 做不到」**。

## 0 · English Summary

> The rest of this document is in Chinese. This section is a self-contained English
> summary of the design, the evidence behind it, and — just as important — what is
> **not** claimed. Every status word here maps to a row of the evidence table in §6.

### What it is

A deterministic gate that sits between a voice agent's proposed `tool.call` and the code
that performs an irreversible action (moving money, in this demo). It answers exactly one
question: **was every argument value actually spoken by the human?**

### Threat model (§1)

| | Threat | Shape |
|---|---|---|
| **M1** | Misrecognition | *"five hundred"* heard as *"five thousand"* |
| **M7** | **Argument fabrication** | the language model fills a `tool.call` with a value that **does not exist in the transcript** |

M7 is the target. It is the nastier of the two: M1 at least has audio behind the wrong
value; M7 has none — the value was *generated*, and a generated value reads exactly like
a real one.

**Explicitly out of scope**, stated so no reader assumes otherwise: speaker spoofing,
replay, a genuine instruction given under coercion, authorization in the downstream
system, and **a malicious demo client**.

That last one follows from where the trust boundary is drawn: **between the agent and the
human, not between the browser and the server.** The adversary is the language model; the
person is the party being protected. So "a client could forge a transcript and feed it to
the gate" is true, and is *not* a refutation of this design — it amounts to the person
lying to themselves. Defending it needs a different threat model (device attestation,
audio signing), which would be a different piece of work.

One more limit belongs here rather than in a footnote, because it bounds what a passing
verdict means at all: **the gate proves provenance, not truth.** If the recognizer
confidently mishears and the model then proposes exactly what was misheard, every argument
*is* grounded and the action passes. M1 is mitigated by the confidence floor and by
read-back — and read-back is the half that is specified but not implemented this round.

### Four structural ideas

**1 · A capability, not a check (§2).** The usual shape is `if (is_safe()) { execute() }`,
which leaves two permanent failure paths: forgetting to call the check, and ignoring what
it returned. Here the executing function accepts an `Execute` capability as its only way
in; that capability has exactly one construction site, inside the gate; and the gate does
not construct it when the evidence is insufficient. "Undecided, so allow" has no
expressible form.

> **Honest boundary.** This buys *"bypassing it must be an explicit, visible code change"*
> — **not** *"it cannot be bypassed"*. Anyone who can edit the code can add a second
> construction site. What guards that is the load-time lint in §5 and human review, not
> the type system. In §6 this line is filed as an **assumption, not a result**.

**2 · A parser, not a matcher (§3.2).** The tempting implementation — take the proposed
value and search the transcript for it — lets the adversary choose the query. The model
invents `500`, we search for `500`, and an unrelated `500` in the transcript (a house
number, a time, leftovers from an earlier sentence) hands the fabrication a witness.
Instead, the **witness set is generated from the transcript alone, with no sight of the
proposal**; only afterwards is the proposed value tested for membership.

**3 · Normalization is a partial function (§3.3).** `"five hundred"` → `500` is mandatory,
or no spoken number ever matches. But every rewrite rule manufactures new witnesses — push
it far enough and every value finds evidence. So normalization is allowed to answer
`VALUE_UNDECODABLE`, and **`UNDECODABLE` is not a pass**. It deliberately has no fallback
return value: a total normalizer quietly turns "I cannot read this" into "I believe this
equals something", which is the asymmetric direction to fail in.

**4 · Four-state registry + a deployment lint (§5).** A check on a parameter is
`REQUIRED`, `NOT_REQUIRED`, or `NOT_IMPLEMENTED`; a check missing from the registry
altogether is a fourth state (`ABSENT`) with no enum member of its own. `NOT_IMPLEMENTED`
and `ABSENT` both **BLOCK** irreversible actions, `NOT_REQUIRED` is skipped, and
`lint_deployment` rejects any registry carrying a `NOT_IMPLEMENTED` check on an
`IRREVERSIBLE` action. The point is the direction of the default: forgetting to
*implement* a check becomes a **loud** failure instead of a **silent** one.

🔴 **Two limits, measured 2026-09-03, written here because measuring them retracted what
an earlier draft of this section claimed.** (a) `NOT_REQUIRED` is the lint's escape hatch,
and the shipped profile lives inside it: the Worker's registry is *derived from* the
checker table it is afterwards linted against — `policy._checks()` marks every implemented
checker `REQUIRED` and everything else `NOT_REQUIRED` — so the lint compares a table with
the thing that generated it, and cannot fail. Deleting any one of the three checkers from
`STANDARD_CHECKERS` therefore builds cleanly, 3/3. The registry that *does* refuse is
`gate/reference.py`, whose requirements are declared independently of the checker table;
against that one the lint bites (4/4 rejected, same experiment). (b) The lint runs inside
`build_gate()`, which the Worker calls **per request**, not once at process start. An
earlier draft claimed "refuses to boot" and "no CheckId can be switched off to make the
demo run"; both were wrong and are withdrawn.

Grounding itself is not defenceless, and the blast radius is worth stating exactly: with
`WITNESS_PRESENT` deleted, a tampered amount is **still blocked**, because `ROLE_MATCH`
also reports `no_witness` — grounding is enforced in `gate/witness.py`, not by that
registry entry. Delete both and the tampered amount is **allowed**.

**Read-back (§4).** Confirmation is not "the model says the user agreed". It must be the
user's own words, read back against **the parameters the gate intends to execute** — not
against the model's paraphrase of them. 🔴 **Specified, not shipped:**
`READ_BACK_CONFIRMED` is a `CheckId` with no checker behind it. `gate/reference.py`
declares it `NOT_IMPLEMENTED` — which is precisely why that registry is rejected by the
lint — while the deployed profile demotes it to `NOT_REQUIRED`, i.e. skipped. Treat it as
an interface slot, not a feature.

### Where it runs (§5.5–§5.6)

The browser never holds the master key. A Cloudflare Worker mints a short-lived token; the
browser streams audio **directly** to AssemblyAI; the Worker only ever sees
`{transcript, proposed tool.call}` and returns a verdict. Two consequences are good — no
audio and no master key traverse our server, so we **cannot** store anyone's voice — and
one is bad and stated rather than hidden: **the gate eats a transcript supplied by the
client** (see the out-of-scope note above).

The gate itself runs on **Cloudflare Python Workers** (Pyodide, Python 3.13.2). This was
measured, not assumed:

| Question | How it was answered | Result |
|---|---|---|
| Do the 13 modules bundle? | `wrangler dev --local` bundle listing | ✅ all 13 |
| Do they import under Pyodide? | `import gate.*` inside the Worker | ✅ all |
| Same behaviour as local? | **whole test suite re-run inside the Worker process** | **151 / 152** |
| Does 3.14-authored code run on 3.13? | local run on 3.13.15 and on 3.14.5 | ✅ 152 / 152 each |

**The one that did not pass is a *did-not-run*, not a failure.** An eight-thread property
test raises `RuntimeError: can't start new thread`; Workers is a single-threaded runtime,
so the property does not apply there. But "does not apply" and "verified" are different
things, and the thread-safety evidence is therefore credited only to the local run.

`gate/` imports six standard-library modules and nothing else — no `re`, no `unicodedata`,
no C extensions. That is not a portability compromise; it falls out of "a parser, not a
matcher": with no regular expressions, there is nothing for regular expressions to drag in.

Daily token issuance is counted in a **Durable Object, not KV** — load-bearing, not taste.
KV is eventually consistent, so two concurrent requests can both read the stale count and
both write stale+1, and the cap leaks under precisely the load it exists for. **A gate that
claims to be fail-closed and is in fact permeable is worse than no gate**, because it
publishes a bound it does not hold. A DO instance is single-threaded with strongly
consistent storage, making `read; +1; write` atomic.

🔴 **What was measured, and what was not.** Two runs, in two runtimes.

**Local (`workerd` under `wrangler dev`), limit forced to 2.** Three **sequential** requests
returned `502 / 502 / 429` with `issued:2 limit:2` — the first two consumed quota and failed
upstream (a placeholder key was in use at the time, §5.7), the third was refused **at the
quota gate** and the counter did not advance. Two things that run did *not* cover: it was
not Cloudflare's runtime, and three sequential requests cannot exhibit the concurrent
interleaving that the DO-over-KV argument above is about.

**Production (`voice-action-gate.<subdomain>.workers.dev`, real Cloudflare, 2026-09-03).**
Both gaps are now closed. Median solo latency for `/api/token` was 0.19 s. Twelve requests
fired concurrently finished in **0.77 s wall** against a **2.26 s serial lower bound**, and
each request's in-flight interval was recorded: **66 of 66 pairs overlapped**. The DO handed
back `issued` 16…27 — twelve distinct, contiguous values, zero duplicates.

🔴 **What that still does not prove.** It shows the DO serialized twelve genuinely
overlapping requests correctly on Cloudflare's own runtime. It does not show the property
holds at arbitrary concurrency, nor across DO eviction or migration — those are platform
behaviours this run never provoked.

### Cost bound (§6.2)

AssemblyAI bills by connection wall-time, independent of audio volume. The server enforces
`max_session_duration_seconds`, closing the socket at `expires_at + ~60s` with
`error_code 3008`. Both factors in the worst case are ours:

```
worst-case billed time per connection = max_session_duration_seconds + ~60s
worst-case daily cost                 = tokens minted × (cap + ~60s)
```

⚠ **That `~60s` is observed, not documented** (n=2, 60±0.3s). It is fine to compute with;
it must be labelled "observed, not documented" wherever it is published.

### Evidence status, honestly (§6)

- ✅ **Confirmed** — word-level `confidence` and `word_is_final` exist in the streaming API;
  the `tool.call` → our code → `tool.result` interception seam is the officially documented
  architecture; streaming v3 works on this account.
- ✅ **Measured** — the server *does* enforce the session cap (V-5c / V-5d), with a no-cap
  control arm still alive at 30 minutes, which rules out an idle timeout; and a Worker-minted
  token carries both cap parameters through unchanged (§5.7).
- ⚠ **Measured but sample-domain mismatched** — the `confidence` distribution (n=200 final
  words) came from 45s of broadcast news. It proves confidence is genuinely dispersed rather
  than pinned at 1.0, which is enough to justify that check existing. It is **not** enough to
  pick a threshold for near-field short commands, where a studio-derived threshold would be
  systematically too loose. **So this project publishes no *recommended* confidence
  threshold, and will not until it is re-measured in the target scenario.** A running
  deployment must nonetheless pick a number: `app/worker/policy.py` ships
  `CONFIDENCE_FLOOR = 0.90`. That is a deployment default, not a finding — read it as
  "this deployment chose 0.90", never as "0.90 is the right floor".
- ⚠ **Risk confirmed from the docs, not reproduced by us** — formatting rewrites
  `words[].text` itself (case, trailing punctuation), not only the aggregate transcript. Our
  own run could not reproduce the documented pair because it connected to a Pro model on
  which `turn_is_formatted` is always true. The design constraint already applies regardless:
  normalization unconditionally absorbs case and trailing punctuation.
- ❓ **Not measured** — whether the agent's own TTS returns through the microphone and
  pollutes the witness set (V-3, needs a real speaker and room); whether non-English input
  produces zero witnesses rather than failing silently (V-4).
- 🔴 **Assumption, not result** — "the capability cannot be bypassed" (see §2).

**Not yet done, and worth saying plainly:** a true end-to-end run — browser microphone →
Worker mints → websocket → transcript → gate — **has never been executed**. It needs a
physical microphone. The 2026-09-03 test proved only that the Worker mints a usable token
with the right parameters; it never opened a websocket.

### One self-correction worth reading (§6.2)

An early probe concluded that the session cap was *not* enforced server-side. Both arms ran
past their cap and were closed by our own timer, so the reading looked clean. The probe's
grace margin was 60 seconds — and the server's closing lag is ~60 seconds. **The
instrument's parameter collided with the phenomenon it was measuring, and the experiment
returned a self-consistent, reproducible, mutually corroborating, and entirely wrong
answer**: no error, no exception, two arms agreeing. The decisive field was sitting in the
same log file the whole time (`Begin.expires_at`, echoed back exactly as requested).

The transferable lesson, and the reason it is written down here: **a probe's timeout or
grace parameter is itself a hypothesis.** When choosing one, ask — *if the truth landed
exactly on this number, would I see it?*

---

## 1 · 威胁模型(先说清楚在防谁)

不是防「用户说错」。防的是**系统把一个没人说过的值当成用户说过的**。

| 编号 | 威胁 | 形态 |
|---|---|---|
| **M1** | 误识别 | *"five hundred"* 被听成 *"five thousand"* |
| **M7** | **参数编造** | 语言模型在 `tool.call` 里填了一个**转写里根本不存在**的值 |

M7 是本作品的主目标。它比 M1 更阴:M1 至少有一段音频对应那个错值,
M7 连音频都没有 —— 值是**生成**出来的,而生成物读起来和真值完全一样。

⚠ **不在射程内**(如实写出来,别让读者以为都防了):
说话人身份伪造 · 重放攻击 · 被胁迫下的真实指令 · 下游系统本身的授权 ·
**恶意的 demo 客户端**。

最后一条要说明白,因为它和部署形态有关(见 §5.5):
**信任边界画在「agent ↔ 人」之间,不在「浏览器 ↔ 服务端」之间。**
对手是**语言模型**,不是坐在前面的那个人 —— 人是被保护的一方。
所以「客户端可以伪造一段转写再喂给闸」是真的,而且**不构成对本设计的反驳**:
那等于人自己对自己撒谎。要防它得换一个威胁模型(设备认证 · 音频签名),
那是另一件作品。

## 2 · 结构:凭据,而不是检查

常见做法是「执行前调用一个 `is_safe()` 检查」。它的问题不是不准,
是**「忘了调」和「调了但返回值没人看」这两条路一直存在**,而且不留痕迹。

这里的做法:

- 执行不可逆动作的那段代码,**只接受一个 `Execute` 凭据作为入参**
- `Execute` 凭据**只能由闸构造**,没有第二个构造点
- 闸在证据不足时**不构造它**

⇒ 「判不出来 → 放行」这条路径,**在类型层面没有对应的表达式可写**。

⚠ **诚实边界:** 这买到的是「绕过它必须是一次显式的、看得见的改动」,
**不是**「绕不过去」。任何能改代码的人都能加第二个构造点 —— 挡这一手的是
§5 的**部署期** lint 与评审,不是类型系统。**别把这两件事说成一件。**

## 3 · Grounding:参数值必须被"说过"

闸对每个参数值问一个问题:**这个值,在词级转写里找得到吗?**

### 3.1 见证集(witness set)

一个参数值的见证 = 转写里一段**连续的词**,经规范化后与该值相等。
见证不存在 ⇒ 该值**没有被说过** ⇒ 不构造凭据。

### 3.2 🔴 解析器,不是匹配器(D1)

最容易写错的地方:**「拿提案里的值去转写里搜」** —— 那是让**对手挑查询**。
模型编造了 `500`,我们就去搜 `500`,而转写里恰好有个无关的 `500`(门牌号、
时间、上一句话的余数)⇒ 编造的值拿到了见证。

正确形状:**见证集只由转写单独生成**,与提案无关;
然后问「提案的值**在不在**这个集合里」。
生成见证的那一步,**看不到提案**。

### 3.3 🔴 规范化是一台见证制造机

`"five hundred"` → `500` 是必需的,否则口语说的数一个都对不上。
但规范化越强,越多东西能被"读成"那个值 —— 极端情况下每个值都能找到证据。

⇒ 规范化函数是一个**偏函数**:它被允许说 **`VALUE_UNDECODABLE`**,
而 `UNDECODABLE` **不是通过**。

**绝不给它兜底返回值。** 一个总函数形态的规范化器,会把「我看不懂这段」
悄悄变成「我认为它等于某个东西」,而这正是失败方向不对称的那一侧。

## 4 · 读回确认(read-back)

闸不接受「模型说用户确认了」。确认必须是**用户说的话本身**,
并且拿**闸打算执行的那份参数**去读,不是拿模型的转述去读。

🔴 **本轮这一条【只有接口,没有实现】,别读成已交付的功能。**
`READ_BACK_CONFIRMED` 是一个有名无实的 `CheckId`:没有任何 checker 在它后面。
`gate/reference.py` 把它声明成 `NOT_IMPLEMENTED`(那份注册表被 lint 拒掉,正是因为它),
而**出厂那份**把它降成 `NOT_REQUIRED` = 跳过。
⇒ 它现在是一个接口槽位,不是一道在跑的闸。这条边界此前只写在一句 HTML 注释里,
渲染出来什么都看不见 —— 等于没写。

<!-- MEASURE: 确认话术、超时、重试次数 —— 9/1 实验后定,现在不写。 -->

## 5 · 注册表四态 + 部署期 lint

每个参数上的检查项有三种**枚举**状态,外加一种「根本不在表里」:

| 状态 | 含义 | 对不可逆动作的后果 |
|---|---|---|
| `REQUIRED` | 已实现,且要求它过 | 正常参与判定 |
| `NOT_REQUIRED` | 在表里,但声明「本部署不要求」 | ⚪ **跳过**(`outcome="skipped"`) |
| `NOT_IMPLEMENTED` | 声明了但没实现 | 🔴 **一律 BLOCK**,且被 `lint_deployment` 拒 |
| `ABSENT`(不是枚举成员) | 注册表里根本没这一项 | 🔴 **一律 BLOCK** |

🔑 **「没实现」的默认后果是拦,不是放。** 这条比任何单个检查都重要 ——
它让「漏写一个检查」变成一个**吵闹的**失败(动作被拦、demo 里看得见),
而不是一个**安静的**失败(动作照过、没人知道)。

🔴 **但 lint 有一个逃生口,而出厂配置就住在里面 —— 这是本节最该先读的一段。**
`lint_deployment` 只拒 `NOT_IMPLEMENTED`,不拒 `NOT_REQUIRED`。
而出厂那份注册表(`app/worker/policy.py` 的 `_checks()`)是**从** `STANDARD_CHECKERS`
**推出来**的:实现了的标 `REQUIRED`,其余一律标 `NOT_REQUIRED`。
于是 lint 拿一张表去比**生成这张表的那个东西** —— 判据抄自被检查者,承载 0 bit。

**2026-09-03 四臂实测**(摘 0 条 / 摘 `witness_present` / `role_match` / `confidence_floor`):

| 启动路径 | 摘 0 条 | 摘任一条 |
|---|---|---|
| Worker 真走的 `policy.build_gate()` | 构建成功 | **构建成功(3/3)** |
| `lint_deployment(reference_registry(), …)` | `DeploymentLintError` | `RegistryLintError`(3/3) |

⇒ **旧稿那句「没有任何 CheckId 可以被临时关掉来让 demo 跑起来」是假的,已撤。**
真会拒的是 `gate/reference.py` 那份注册表 —— 它的要求独立声明、不从 checker 表推导,
lint 对它才咬得动。另外 lint 跑在 `build_gate()` 里,而 Worker **每个请求**调它一次,
不是「进程起来时核一次」;旧稿「拒绝启动」的措辞同样是错的。

🔑 **爆炸半径要说清,不恐吓也不粉饰:** 只摘 `witness_present`,篡改金额**仍然 BLOCK** ——
`role_match` 也会报 `no_witness`,grounding 是在 `gate/witness.py` 的求值核里执行的,
不靠注册表那条检查项。**两条一起摘,篡改金额才 ALLOW(理由 `[]`)。**

⚠ **可砍的是功能,不是闸**:第二个动作域 · 多语种 · 真实认证 · 持久化 · 小数与 cents。
这五样砍掉不影响主张;砍掉任何一个检查项都会让主张变成假话。

### 5.5 · 闸跑在哪里(2026-08-31 定 · 🟡 **一处待定,见下**)

> 🔑 **本节承重的两句是「浏览器不持有主 key」与「会话上限由服务端执行」。**
> 两者都是 AssemblyAI 侧的性质,
> 🔴 **2026-09-02 两次改判,最终【两句都承重】:**当天早些时候 V-5 曾把后半句判为证伪、
> 我据此划掉过它;当晚 V-5c / V-5d 证明那次证伪本身是探针余量造成的假象(§6.2),
> 后半句**恢复承重**。⚠ 恢复的是「服务端执行」这个事实,不是「所以不必自己算成本」。
> 与跑在谁家机器上无关。**待定的只有前端落点,不是这套结构。**
> ✅ **2026-09-03:运行时那一半已实测落定,见 §5.6。**「前端落点」仍是同一个待定项 —— 别把 §5.6 读成它也答了。

浏览器 **不持有主 key**。流程:

```
浏览器 ──① 要一枚临时 token──▶ Worker(持主 key · 签发时填 max_session_duration_seconds ⚠ 见 §6.2:服务端在 expires_at+~60s 执行)
浏览器 ──② 直连 wss://…/v3/ws?token=… ──▶ AssemblyAI      (音频不经过我们)
浏览器 ──③ POST {转写, 提议的 tool.call} ──▶ Worker /gate  ──▶ 裁决
```

三个后果,**两好一坏,都写出来**:

- 🟢 音频与主 key 都不经过我们的服务器 ⇒ 我们**存不下**任何人的语音
- 🟢 **会话上限由 AssemblyAI 执行,不是我们的计时器** —— V-5c / V-5d 实测:服务端在
  `expires_at + ~60s` 主动关闭并回 `error_code 3008`(§6.2)。⚠ 该滞后是**观测值不是承诺值**,
  故单连接最坏计费时长按 `cap + ~60s` 算,别按 `cap` 算。
- 🔴 **闸吃的是客户端送来的转写** ⇒ 见 §1 那条 out-of-scope。
  **别把这条藏起来** —— 被问到时,答案是「威胁模型如此」,不是「我们没想到」。

### 5.6 · 运行时:已实测,不再是待定(2026-09-03)

`gate/` 跑在 **Cloudflare Python Workers**(Pyodide,**Python 3.13.2** —— 本包写于 3.14)。
这是量出来的,不是选出来的:

| 问的问题 | 怎么答的 | 结果 |
|---|---|---|
| 13 个模块能作为包被打包进去吗 | `wrangler dev --local` 的 bundle 清单 | ✅ 13 个全在 |
| 在 Pyodide 里 import 得起来吗 | Worker 内 `import gate.*` | ✅ 全部 ok |
| 行为和本机一样吗 | **整套测试搬进 Worker 进程内跑** | **151 / 152 通过** |
| 3.14 写的代码 3.13 跑得动吗 | 本机 3.13.15 与 3.14.5 各跑一遍 | ✅ 152 / 152 各自全绿 |

🔴 **那 1 条的诚实说法:它不是失败,是【没跑成】。** `TS-31`(一个 Gate 实例、八个线程)在
Pyodide 里抛 `RuntimeError: can't start new thread`。Workers 是单线程运行时,所以那条属性
在这里不适用 —— **但"不适用"和"验过了"是两回事**:线程安全的证据只来自本机那一次运行,
本文件不把它算进 Worker 侧的证据。

**依赖面为什么这么小:** `gate/` 只用 6 个标准库模块(`collections` · `dataclasses` · `types` ·
`typing` · `math` · `enum`),没有 `re`、没有 `unicodedata`、没有 C 扩展。
这不是为了可移植而做的妥协 —— 它是"解析器不是匹配器"(§3.2)的副产品:没有正则,就没有正则要带的东西。

**部署形状:** `app/wrangler.toml` 声明 `python_workers`,静态 UI 走 `[assets]`,
每日签发计数走一个 **Durable Object**(`DailyQuota`)。
🔴 **DO 而不是 KV,这是命门不是口味**:KV 最终一致 ⇒ 两个并发请求都读到旧值、都写回旧值+1
⇒ 上限在它唯一被需要的负载下漏计。**一个声称 fail-closed、实际会被穿过的闸,比没有闸更坏**,
因为它对外报出了一个它守不住的界。DO 实例单线程 + 存储强一致 ⇒ `读;+1;写` 天然原子。
🔴 **实测到的是什么、没实测到的是什么,分开写。** 两次跑,两个运行时。

**本机(`wrangler dev` 的 `workerd`),上限压到 2。** **顺序**发三个请求依次得
502 / 502 / **429**(`issued:2 limit:2`),第三次在**配额闸**处被拒且计数不再递增。
这一轮**盖不住**两件事:① 它不是 Cloudflare 的运行时;
② 三个**顺序**请求演示不出上面那段论证所针对的**并发交错**。

**生产(`voice-action-gate.<subdomain>.workers.dev`,真 Cloudflare,2026-09-03)。**
这两个缺口现在都补上了。`/api/token` 单发延迟中位数 0.19s;12 个请求并发打出去,
**墙钟 0.77s**,而串行下界是 **2.26s**;每个请求的在飞区间都记了下来,
**66 对里 66 对重叠**。DO 发回的 `issued` 是 16…27 —— 十二个互异且连续,零重复。

🔴 **它仍然不能证明什么。** 它证明的是:在 Cloudflare 自己的运行时上,DO 把十二个
**真正重叠**的请求正确串行化了。它**不**证明这条性质在任意并发度下成立,
也**不**覆盖 DO 的驱逐与迁移 —— 那些平台行为本轮压根没触发到。

> 📍 **§5.7(端到端:真 key 经 Worker 签发的实测)在本文件【靠后】的位置** ——
> 它是后来补测的,按时间顺序落在 §7 附近而不是紧跟本节。顺读的人容易漏掉它。

## 6 · 证据状态(这张表是本文件的脊梁)

| 断言 | 状态 | 依据 |
|---|---|---|
| 流式返回**词级 `confidence`** 与 `word_is_final` | ✅ **已证实** | 官方文档 `Turn` 消息结构;并已实测连通 |
| `tool.call` → 自己的代码 → `tool.result` 这条拦截接缝是**官方架构** | ✅ **已证实** | 官方文档 client-side function tools |
| 本账号可用流式 v3 | ✅ **已实测** | `/v3/token` 返回真 token;旧版 `/v2/realtime/token` 已 404 |
| formatting 是否改写 `word.text` | ⚠ **风险【已确认存在】(官方文档),但我方未复现(V-1)** | 见 §6.1 —— 这一格装不下,单独开了一节。**结论已经足以约束设计:规范化必须无条件吃掉大小写与词尾标点,这不再是可选项。** |
| `confidence` 的真实分布 | ⚠ **测到一个样本,但【样本域不匹配】(V-2)** | 2026-09-02 实测,n=200 个 final 词:`min .5293 · p01 .5882 · p05 .8032 · p50 .9996 · max 1.0` · `<0.7` 占 3.5% · `<0.9` 占 11.5%。🔴 **但素材是 45 秒英文广播新闻**(播音员 · 演播室音质 · 连续叙述), 而本作品的场景是**近场麦克风 + 短指令 + 金额词**。⇒ **这张分布可以证明「`confidence` 真的分散、不是恒 1.0」(这一条已足够支撑 C3 的存在理由),但【不能】拿来选阈值** —— 拿演播室分布定的阈值,到真实麦克风上会系统性偏松。 |
| agent 自己的 TTS 会不会被麦克风收回去混进 `words[]` | ❓ **未测(V-3)** | 若会,§3 的见证集会被自己的声音污染 |
| 非英语输入是否真的产出零见证 | ❓ **未测(V-4)** | 决定多语种要不要显式拒绝而不是静默失败 |
| `max_session_duration_seconds` 可设且**由服务端执行** | ✅ **已实测(V-5c / V-5d)** | 见 §6.2。服务端在 `expires_at + ~60s` 关连接并回 `error_code 3008`「Maximum session duration exceeded」;对照臂(无 cap)**30 分钟**不断,排除 idle timeout。⚠ 同日早些时候的 V-5 曾判「证伪」,那是探针余量 `GRACE=60` 恰好等于服务端滞后所致 —— **已推翻,别再引那个结论** |
| 临时 token 可由服务端签发、浏览器不拿主 key | ✅ **已实测(生产 · 2026-09-03)** | 部署后对真 Worker 连打 27 次,每次都拿到可用 token,返回体里两个上限都在(`expires_in_seconds: 60` · `max_session_duration_seconds: 120`);浏览器侧从头到尾没有主 key。`expires_in_seconds` 取值范围 `1`–`600` |
| SQLite 版 Durable Object 在 Workers 免费档可用 ⚠ **且平台形态已重开,见 §5.5** | ✅ **已实测(生产 · 2026-09-03)** | 已部署并真的在跑:12 个并发请求打同一个 DO,**66/66 对在飞区间重叠**,`issued` 16…27 互异且连续、零重复(墙钟 0.77s vs 串行下界 2.26s)。⚠ 这只证明**这个并发度**下正确,不证明任意并发度,也不覆盖 DO 驱逐 / 迁移 |
| 「凭据无法被绕过」 | 🔴 **假设,非结论** | 见 §2 诚实边界。**write-up 里不得写成已证明。** |

### 6.1 · V-1 的现状(2026-09-02,两步:查文档 + 回自己的数据抽验)

**① 风险是真的,不是假想。** 官方 streaming 文档给了一对逐字示例:同一 `turn_order`、同一段音频,
未格式化 final 与已格式化 final 的 **`words[].text` 本身不同** —— `"my"` → `"My"`,`"sonny"` → `"Sonny."`
(大小写改写 + 词尾附加标点);`start` / `end` / `confidence` 三个数值逐字不变。
⇒ **formatting 碰的不只是 `transcript` 这类聚合字段,它改写词本身。**
⚠ **诚实标注:这些引文来自一次文档调研,我【没有】独立回官方页复核过。**
但它对设计的约束方向是保守侧的(要求规范化更强),**采信它不会让闸变松**,故照它办。

**② 我方那次 45 秒 run 复现不了那对示例,原因已用【自己盘上的数据】查清:**

| 现场事实(现取,非记忆) | 读法 |
|---|---|
| `Begin.configuration.model` = `universal-3-5-pro` · `mode` = `balanced` · `api_version` = `2025-05-12` | 连的是 **Pro**,而官方那对示例属于非 Pro 的 Universal Streaming |
| `Termination` 消息**在**,`session_duration_seconds` = 55 | ⇒ **没有过早断开**;「提前关连接丢掉格式化 final」这条候选解释**被排除** |
| `(end_of_turn, turn_is_formatted)` 联合分布 = `(False,True)×24` · `(True,True)×2` | 每个 turn **只有一条** final,不是两条 |
| 官方对 Pro 的字段定义:`turn_is_formatted` *always matches `end_of_turn`* | 🔴 **与实测【字面冲突】** —— 24 条 partial 是 `eot=False` 而 `fmt=True` |

🩸 **这一轮里被抽验推翻的两条**(记下来,因为它们都读起来很有道理):
调研报告推断「你没显式传 `speech_model`,所以默认落到 Pro」—— **假的**,探针的
`_meta.params` 里逐字写着 `speech_model: universal-3-5-pro`,是显式传的;
以及「可能是发完 `Terminate` 没继续读、丢了那条 final」—— **也被排除**,`Termination` 就在盘上。
⇒ **两条都不必去"修",而在抽验之前它们看起来都值得修。**

**③ 对设计的约束(这一条现在就生效,不等重测):**
- 🔴 **规范化必须无条件吃掉大小写与词尾标点。** 我们拿到的 `words[].text` 有可能是格式化过的
  (Pro 下 `turn_is_formatted` 恒 `True`,而这个字段在该模型上的含义我们没有可信定义)。
- 🔴 **「见证从哪个字段取」必须是一个显式的、可替换的边界**,不得写死。
- ⬜ **未决:产品该用哪个模型。** 非 Pro 的 Universal Streaming 会发**两条 final**,
  即拿得到**未格式化**的那版 —— 那更接近「用户说的原话」,对见证集是更好的输入。
  Pro 拿不到。**这是一个真的设计裁决点,不是参数微调。**

**④ 重测怎么做(官方给了路径,比原设计便宜):**
`/v3/ws` 收**二进制帧的裸 PCM**(默认 16kHz / 16-bit / mono,`encoding` 另可取 `pcm_mulaw` / `opus` / `ogg_opus` / `aac`),
⇒ **同一份本地 PCM 文件可反复重放** —— 「直播流不可重现」这个障碍消失了,
也不需要麦克风。一句话的音频即可触发一次完整 turn,连接只需几秒 ⇒ 比那次 45 秒便宜一个量级。
臂:`speech_model=universal-streaming-english` + `format_turns=true`,发完 `Terminate` 后**继续读到 `Termination`**。
⚠ **预测不同,所以这个实验值得做**:若拿到两条 final 且 `words[].text` 逐词不同 ⇒ 复现官方示例;
若只拿到一条 ⇒ 模型/参数没对上,**不许读成「不改写」**。

### 6.2 · 会话上限【由服务端执行】—— 附一次自我推翻(2026-09-02)

🔴 **本节先记一件事:同一天我在这里写下过「上限不被执行」,那是错的。**
错因留着,因为它比结论本身更该传下去。

#### 错的那一轮(V-5)

两臂 `max_session_duration_seconds=60 / 180`,不发音频,硬 deadline = 上限 + `GRACE`,
而探针里 `GRACE = 60`。两臂都跑满自己的 deadline(120.03s / 240.04s)、由**我的** timer 关闭,
于是我判「服务端不执行上限」。

🩸 **`GRACE` 恰好等于服务端的滞后。** 服务端就在 `expires_at + ~60s` 关连接 ——
两臂真正会被关的时刻是 **120.21s** 与 **240.29s**(见下 V-5c / V-5d),
我的 timer 早了 **0.18 秒**和 **0.25 秒**。
**仪器的参数与被测现象撞在同一个数上,于是仪器把现象整个盖住了。**

🔑 **而判据一直躺在同一份落盘里,我没读:`Begin.expires_at`。**

| 请求的 cap | `Begin.expires_at` 距 mint |
|---|---|
| 不传 | **+10800s 整**(= 文档缺省 3 小时,秒级精确) |
| 60 | **+59s** |
| 180 | **+180s** |

⇒ 服务端**从未静默丢弃**这个参数,它原样回声。
我当时写下的「这是一个静默无效的参数」**是假的**,而那句话本身还被我标成了最危险的一点。

#### 对的那一轮(V-5c / V-5d)

同样不发音频、不发 ping,只把守候时间从 `cap+60` 拉到远超它:

| 臂 | cap | `expires_at` | 关闭者 | 关于 | 超期 |
|---|---|---|---|---|---|
| **V-5c** | 60 | mint+59s | **服务端** | **120.21 s** | +60 s |
| **V-5d** | 180 | mint+180s | **服务端** | **240.29 s** | +60 s |

服务端**逐字给出了原因**:

```json
{"type":"Error","error_code":3008,"error":"Session Expired: Maximum session duration exceeded"}
```

**对照臂排除了 idle timeout。** V-5b 的 `idle` 臂(**不带 cap**,同样零音频零 ping)
全程活过 **30 分钟**未断(1800.03s 由探针自己的硬 deadline 切断,不是服务端),
其运行时段**完整覆盖**了 V-5c / V-5d;若 120s 那次关闭是 idle timeout,它应当同时被关。

**两个候选规律被分开了**:「关于 `expires_at + 60s`」预测 240s,「关于 `2 × cap`」预测 360s;
V-5d 落在 **240.29s** ⇒ 规律是 **`expires_at + ~60s`**,与 cap 的倍数无关。

#### 成本边界(本节真正的产物)

计费按**连接时长**,与音频量无关。故:

```
单连接最坏计费时长 = max_session_duration_seconds + ~60s
最小可设 cap = 60(文档下限)      ⇒ 单连接最坏 ≈ 120 秒
当日最坏成本 = 签发的 token 数 × (cap + ~60s)
```

**两个因子都在我们自己的服务端手里**(token 由 Worker 签发、cap 由 Worker 填)
⇒「我们给公开 URL 加了成本边界」这句话**成立**,而且写得出算式。

⚠ **诚实边界,四条,别少读任何一条:**
1. **零音频。** 有音频流时是否仍在 `expires_at+60s` 关,**未测**。
   但 `Begin` 已到 = 已开始计费,而那正是最该被上限保护的状态。
2. **那个 ~60 秒是【观测到的滞后,不是文档承诺】。** n=2(cap=60 / 180 各一次),
   两次都是 60±0.3s;AssemblyAI 没有在任何文档里承诺这个数,**它可以变**。
   ⇒ 拿它算成本可以,写进对外材料必须标 "observed, not documented"。
3. **`expires_in_seconds`(1–600)仍然管不到这件事** —— 它决定这枚 token 还能不能用来
   **建**连接,不决定连上之后能挂多久。两个参数别混。
4. **没有测「cap 缺席时的关闭点」** —— V-5b 两臂(`idle` 零帧 / `silence` 发了 31747 帧静音)
   都活满 30 分钟、都由探针自己切断 ⇒ **只测到下界 `T > 1800s`,上界仍未知**;
   文档缺省的 3 小时是**声明**,不是我们测出来的。**绝不把「没断」写成「我们知道了」。**
   但这条**不再承重**:我们的 Worker 恒填 cap。

🔑 **留给下一次的教训,写在这里因为它会再来:**
一个探针的超时 / 余量参数,**本身就是一个假说**。它取的值若恰好等于被测量,
实验会安静地给出一个自洽、可复现、且完全错误的结论 —— 没有报错、没有异常、
两臂还互相印证。**⇒ 设余量时问一句「如果真相恰好落在这个数上,我会看见吗?」**

## 7 · 实验台账

### 7.0 已跑(2026-09-02 · 一次 55 秒计费连接 ≈ $0.007)

英文广播流 · `format_turns=true` · 26 条 `Turn` · 200 个 final 词。

| 维 | 结果 | 一句话 |
|---|---|---|
| **V-2** | ⚠ **测到,但样本域不匹配** | 分布见 §6 那一行。**证明了 `confidence` 真的分散(不是恒 1.0)**,但演播室音质定的阈值到近场麦克风上会偏松 ⇒ **阈值仍未定** |
| **V-1** | 🔬 **UNMEASURED —— 实验设计的前提被推翻** | `turn_is_formatted` 恒 `True`,同连接内无未格式化版 ⇒ 配对数结构性为 0。**重设计需固定音频源跑两次** |
| **V-3** | ⬜ **结构上不可由本臂回答** | 要真外放 → 空气 → 麦克风。`--source mic` 单独一臂,且需物理在场 |
| **V-4** | ⬜ **未跑该臂** | 本 run 源是英文流(含非 ASCII 词 = 0);已落 1618 词英文夹具备用 |
| **V-5** | ✅ **已跑,结论已被自己推翻一次** | 首轮 V-5 判「不执行」= **假**(探针余量撞上服务端滞后);V-5c / V-5d 证明上限**由服务端执行**于 `expires_at + ~60s`。**详见 §6.2** |

🔑 **探针的诚实阀在这一轮真的响了,这是它值钱的地方**:V-1 配对数为 0 时它输出 `UNMEASURED` + 诊断,
**没有输出「无差异」**。若当初图省事让它在零样本时打印「未发现改写」,今天这张表上就会多一条假的 ✅。

⚠ **退出码读法(踩过一次,记在这)**:URL 臂 rc **必然是 1**(V-3 结构上测不到),
**且 rc 会被管道吞掉** —— 经 `| tail` 读到的是 `tail` 的 0。**要判 rc 就别接管道。**

### 7.1 还要跑的


🩸 **本行原写「V-1 / V-2 / V-4 一次流式会话即可测完」—— 09-02 实测推翻,别再照它排活。**
一次会话只测得到 **V-2**;V-1 需要**同一段音频跑两次**(`format_turns` 一 `false` 一 `true`),
而直播流不可重现 ⇒ **必须先有固定音频源**;V-4 需要非英语源;V-3 需要真外放 + 麦克风。
⇒ **四个维度是四次不同的准备,不是一次会话。**
探针已写好并离线验过(**不随本仓发布** —— 它是实验工具,不是产品代码)。

**V-5(2026-08-31 新增,与托管方案一起定的):会话上限到底由谁执行。**
签一枚 `max_session_duration_seconds=180` 的 token,连上去,**什么都不做,掐表**。

| 观测 | 读法 |
|---|---|
| ~180 秒时服务端主动发 `Termination` / 关连接 | ✅ 硬上限成立 |
| 到点不断,连接继续 | 🔴 上限**不是**服务端执行的 ⇒ 成本边界那条断言不成立,必须自建计时器 |

🔴 **2026-09-02 已跑,而这张表【被读错了一次】,记在这里:**首轮 V-5 看起来落在第二行
(「到点不断」),我据此宣布上限不被执行;当晚 V-5c / V-5d 证明真正落的是**第一行** ——
服务端确实主动关,只是滞后 ~60 秒,而首轮探针的余量恰好也是 60 秒。详见 §6.2。
🩸 **预设读法表挡不住这一类错**:它约束的是「拿到观测怎么读」,而这次坏掉的是**观测本身**。
🔑 **这张预设读法表是【跑之前】写的,这是它值钱的地方** —— 结果出来时没有解释空间,
对着表读就行。⚠ 上面那句「必须自建计时器」**已被 §6.2 修正得更准确**:
客户端计时器是可绕的,自建计时器**不足以**替代;真缺口见 §6.2 末尾。

🔴 **这一臂的失败方向是「安静地不发生」** —— 不断开不会报错、不会抛异常、
日志里什么都不会多出来。⇒ **必须掐表读时间,不能只看"跑完了没报错"。**

🔴 **本项目对外不给出任何具体的置信度阈值,V-2 跑完之后也不给。**
理由不是谨慎,是判据不匹配:V-2 量到的是**演播室广播**语音的置信度分布,
而这套闸要用在**近场麦克风的短指令**上。拿前者去定后者的阈值会**系统性偏松** ——
一个先写上去、打算"以后再校准"的数,会先被人当成结论引用。
解除条件是明确的:**在目标场景(真麦克风 + 真指令)上重测过之后。**

🔴 **「会话上限由 AssemblyAI 服务端执行」这句话可以说,但【不能只说前半句】。**
必须同时给出算式 `最坏计费时长 = cap + ~60s`,并标明那个 `~60s` 是**观测值,
不是文档承诺**。只说前半句,等于把一个带误差的边界说成了硬保证。

🔑 **这句话本身的来历值得记一笔,因为它是本文档里最贵的一次自我纠正:**
它一度被判为**证伪**(§6.2 的 V-5),我据此把整句划掉;当晚 V-5c / V-5d 证明
那次证伪本身是探针余量造成的假象,这句话**是真的**。两条教训:
(a) 一个方案里「最好听的那句话」,该排在排查顺序的最前面 —— 它当初正是被这样标记的;
(b) **推翻一个结论时,新实验的资格要和被推翻的那个一样受审** ——
    那一轮我只审了旧结论,没审新实验。

---

### 5.7 端到端:真 key 经 Worker 签发(2026-09-03 实测)

此前 demo 的三次 `/api/token` 用的是占位 key,只证明了**配额闸在 mint 之前触发**
(拿到的是 AssemblyAI 的 `401 Temp token cannot create temp token`);
「Worker 真能签出可用 token」这一环当时**没有证据** —— 只有 V-3 / V-5c 那批
**绕过 Worker 直连**的探针。两者不是同一条路径。

本轮补上那一环。key 经 `wrangler dev --var` 注入,**不写 `.dev.vars`、不落盘**:

| 观测 | 值 |
|---|---|
| 签发 | 成功 |
| token 长度 | 2431 字符 |
| `ws_base` | `wss://streaming.assemblyai.com/v3/ws` |
| `expires_in_seconds` | 60(= `TOKEN_TTL_SECONDS`) |
| `max_session_duration_seconds` | 120(= `DEMO_CAP_SECONDS`) |
| `quota` | `{issued: 1, limit: 200, day: ...}` |

⇒ **两个 cap 参数是 Worker 填的、且原样被服务端接受** —— 这正是成本边界那条断言
「算式里的 cap 由我们控制」那半的直接证据。

🔴 **诚实边界:本轮【只签发,没连 ws】。**
它证明的是「token 签得出来、参数填得对」,**不证明**「连上后转写正常」。
后者的证据仍只在 V-3 / V-5c 那批**直连**探针里,而那条路径不经过本 Worker。
⇒ 真正的端到端(浏览器麦克风 → Worker 签发 → ws → 转写 → 闸)**仍未跑过一次**,
它需要一只真麦克风,只能人手跑。**别把本节读成「端到端已验」。**

⚠ 拿真 key 跑过本地 dev server 之后,记得 `rm -rf .wrangler` ——
miniflare 的 observability trace store 会把请求留在盘上,而那些请求带着凭据。
本轮跑完已清,并全树扫过该 key 的字面:**命中 0**。
