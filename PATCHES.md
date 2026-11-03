# 相对上游 0.10.0 的改动

镜像里的 `family_brief` 不是原版。逐条说明改了什么、为什么、会不会影响别处。

⚠️ **升级上游版本时，下面每一条都要重新应用**，否则容器跑不起来或功能残缺。

---

## A. 让上游在 Linux 容器里跑得起来

### A1. `config.py` — 恢复 `email.sender`

```python
class EmailConfig:
    enabled: bool = True
    sender: Literal["gateway", "gmail"] = "gateway"   # ← 新增
```

上游 0.10.0 删掉了 `sender` 字段，只认官方 gateway（需要 Gateway Key）。家庭自建没有 Key，所以恢复它，允许走自家 Gmail。

### A2. `actions/email.py` — 加 Gmail SMTP 发送分支

`sender == "gmail"` 时不走 gateway，改为 `smtplib` 连 `smtp.gmail.com:465`（SSL），用 `~/.family/secrets/gmail-imap-<address>` 里的 App Password 认证，`From:` 就是该 Gmail 地址。

Gmail 的 App Password 同时适用于 IMAP 读取和 SMTP 发送，所以一个密码够两用。

### A3. `system/jobs_linux.py` — 没有 `loginctl` 时不要崩

上游调 `systemctl --user` 前先跑 `loginctl show-user`，容器里没有 systemd，直接抛异常把 `doctor` 打断。改成捕获 `FileNotFoundError` 并优雅降级：计划由 `entrypoint.sh` 自己算点，不用 systemd。

### A4. `sources.py` — WhatsApp 放开到 Linux ← **最关键**

```python
WHATSAPP = Source(..., systems=frozenset({"macos", "windows", "linux"}), ...)
```

上游把「Linked Device 常驻服务」限定在 macOS / Windows，Linux 上整个源被判定为不可用。但 Baileys 本身跨平台，容器里跑得好好的（已实测无需重新扫码即可重连）。

### A5. `ops.py` — `doctor` 的邮件检查口径

上游的 "Brief sending" 检查固定去验 Gateway Key，改走 Gmail 后一直误报。改成按 `sender` 分支检查：`gmail` 就验 App Password。

---

## B. 网页设置（本次新增）

上游的 `setup page` 是给 macOS 桌面设计的：只绑 `127.0.0.1`、随机端口、假定本机有浏览器。要让它成为一台无头服务器的设置入口，改了五处。

### B1. `setup_server/server.py` — 可绑局域网地址

- 新增 `SETUP_BIND`（默认 `127.0.0.1`）、`SETUP_PORT`（默认随机）、`SETUP_PUBLIC_URL`（对外地址，写进日志给人看）三个环境变量
- 命令行也支持 `parent-recap setup page --bind 0.0.0.0 --port 8090`
- **Host / Origin 校验改为"请求自洽"**：原来要求 `Origin` 严格等于启动时推导出的 `origin`（即 `127.0.0.1:端口`），绑到局域网 IP 后必然 403。现在绑定非回环地址时，校验 `Origin` 是否等于**本次请求的 Host**。CSRF 防护不变（别的站点发来的请求，`Origin` 是它自己的域名，照样被拒），但不再需要预先知道访问者用哪个 IP。
- `SETUP_IDLE_MINUTES`：默认仍 30 分钟；`0` 表示永不自动关。

安全边界没放松：地址里那段 64 字符随机 code 仍然是唯一的通行证，`/favicon.ico` 之外任何请求都必须带它。

### B2. `setup_ai.py` + `setup_server/ai.py` — Codex 设备码登录

上游 `codex login` 走 OAuth，回调服务器只绑 `127.0.0.1:1455` —— 在容器里等于死路，浏览器在别人电脑上，够不到容器的回环地址。

改成：没有桌面浏览器时（Linux）用 `codex login --device-auth`。Codex 会打印一个网址和一个一次性码，后台线程读出来存进 `_codex_device`，通过 `api/codex/login` 和 `api/codex/check` 返回给页面（`device_code` / `device_url`）。

这其实就是 Codex 自己的提示：*"On a remote or headless machine? Use `codex login --device-auth` instead."*

### B3. `page/page.js` + `page/text.json` — 页面上显示那个码

`codexResult()` 检测到 `out.device_code` 时，用现成的 `showSource(key, {values})` 占位符机制渲染（`{url}` / `{code}`）。三种语言各加一条 `codex.device-code` 文案。

### B4. `system/profile_linux.py` — 打开完整设置页

上游 Linux profile 里：

```python
ais=("gateway",)
page_skips=frozenset({"ai", "gmail"})
```

意思是「Linux 服务器由维护者运维，家庭不需要在页面上配 AI 和 Gmail」。这不符合"家庭自己的 NAS"。

改成由环境变量 `PARENT_RECAP_OWN_SERVER=1` 控制（Dockerfile 里设好了）：

```python
ais = ("codex",) if _own_server() else ("gateway",)
page_skips = frozenset() if _own_server() else frozenset({"ai", "gmail"})
```

**默认行为完全不变**，维护者的托管服务器不受影响。

### B5. `nas/entrypoint.sh` + Dockerfile + compose — `MODE=setup`

`MODE=setup` 时容器只跑设置页（`exec parent-recap setup page --bind 0.0.0.0 --port 8090`），不跑每日任务、不启动 WhatsApp 常驻服务，避免和设置页抢同一批文件。`MODE=daily`（默认）就是原来的行为。

---

## 验证记录

- 容器内 `parent-recap doctor`：12 项 / 11 OK / 1 警告（无 systemd，预期）
- `codex login --device-auth` 实测输出：`https://auth.openai.com/codex/device` + 一次性码
- WhatsApp 迁移到容器后 3 秒内 `connected`，无需重新扫码
- Gmail SMTP 真实发信到 hotmail 成功

---

## C. 收件人列表与发件人明示（20:45 追加）

上游的收件人 UI 在两个地方都写死为 2 个：Welcome 是「我 + 伴侣」（`PartnerAnswer` 单个），
Gmail 步骤是 `address + partner`。而后端 `BriefTo.recipients: list[SentTo]` 本来就支持任意多个。
另外上游假定「设置者自己的邮箱就是第一个收件人」，且简报从 `brief@parentrecap.com` 发出。

### C1. `setup_server/welcome.py` — 收件人改成列表

- `PartnerAnswer` → `RecipientAnswer`，`WelcomeAnswer.partner` → `recipients: list[...]`（最少 1 个）
- `save_welcome` 直接写 `answers["recipients"]`，不再走 `progress.partner` 中转
- `_welcome()` 返回 `recipients` 列表（读 config 的 `email.to`，没有则给一行空的）
- 新增 `_recipients(data, language)` 辅助函数

### C2. `setup_server/gmail.py` — 删掉 `recipients()` 中转

那个函数强制把 `parent`（发信 Gmail）塞成第一个收件人。现在 Welcome 直接给完整列表，它没有调用点了，删掉。

### C3. `send_key.py::may_request` — Gmail 发信时不要 Gateway Key

```python
return cfg.llm.backend != "gateway" and cfg.email.sender != "gmail"
```

原来只看 AI 后端。codex + 自己 Gmail 的组合会去请求 Gateway Key，必然失败，把设置页的 Gmail 步骤卡死。

### C4. `config.py` — `email.sender` 默认值跟随环境

```python
def _default_sender():
    own = os.environ.get("PARENT_RECAP_OWN_SERVER", "").strip().lower() in ("1", "true", "yes")
    return "gmail" if own else "gateway"

sender: Literal["gateway", "gmail"] = Field(default_factory=_default_sender)
```

全新安装（空 config）时默认就走 Gmail，不需要手工写 `sender: gmail`。非容器部署保持 ADR 0032 的 gateway。

### C5. 前端 — 可增删的收件人行

- `index.html`：Welcome 的 partner radio + 单字段 → `<div id="recipient-rows">` + 「再加一个」按钮；
  Gmail 步骤的 `gmail-brief-address` + `gmail-brief-partner` → `<div id="gmail-recipient-rows">`
- `page.js`：新增 `recipientRow()` / `renderRecipientRows()` / `addRecipientRow()` / `readRecipientRows()`
  四个通用函数，两处复用；删掉 `showPartner()` / `showBriefPartner()`；
  `saveRecipients` 不再有 `kept = page.gmail.to.slice(2)` 那套「超过两个的留在后面」逻辑
- `page.css`：`.recipient` 三列网格（地址 / 语言 / 删除）
- `page/text.json`：新增 `welcome.recipients.note`、`recipients.add`、`recipients.remove`、
  `gmail.brief.from`、`gmail.brief.from.unset`；改写 `gmail.brief.explain` 和 `gmail.brief.unread`
  （原文案都在说「从 brief@parentrecap.com 发、经过团队服务器」，Gmail 发信模式下不成立）

### C6. 发件人明示

Gmail 步骤顶部新增 `#gmail-brief-from`，随 `gmail-address` 输入实时更新：
未填时显示「日报从你自己的 Gmail 发出：请在下面填上它的地址」，填了显示「日报将从 xxx@gmail.com 发出」。

### 验证记录（rc3，临时容器 + 空卷）

- `POST api/welcome` 带 2 个地址 → `saved`
- 落盘 config：`email.to` 正好两个地址，**不含发信 Gmail**
- `api/state` 回读 `welcome.recipients` 与 `gmail.to` 均为两条
- `POST api/gmail/recipients` → `saved`，不再请求 Gateway Key
- 容器内 `Config.load(None).email.sender` = `gmail`，`may_request` = `False`

---

## D. 第一份日报做不出来 + WhatsApp 掉线（21:00-21:25）

### D1. `system/jobs_linux.py::run_detached` —— 原来是个抛异常的桩

设置页最后一步「你的第一份日报」调 `jobs.run_detached(["run","--preview",...])`，
Linux 适配器里这个函数只有 `raise RuntimeError(NO_BACKGROUND)`，容器里必然 `make-failed`。
上游的理由是「服务器上的调用方本来就有定时任务的权限，直接跑命令就行」——但容器里没有 systemd，
设置页又是必须走这条路。

实现成普通子进程：`sys.executable -m family_brief [-c config] <args>`，同一个 Python 和环境，
stdout 用独立线程读（防止管道写满阻塞子进程），主线程按 1 秒粒度把已读到的输出交给 `progress`（页面据此显示进度），
到 deadline 就 kill 并返回 None（jobs.py 转成 `TIMED_OUT=124`）。
实测：8 秒 deadline → 8.0 秒退出、8 次 progress 回调、子进程确认已被杀掉。

### D2. `actions/email.py::write_to` —— 页脚说错话

上一轮我改成「Gmail 发信时返回自己的地址」，但 `unread_sender` 的文案是
「这封邮件的发件地址无人查看，如需回复请写信给 {address}」——自家 Gmail 发信时这句话是错的。
改回上游的契约：`sender == "gmail"` 时返回 `None`（回复直接就到，不需要这句提示）。

### D3. `nas/entrypoint.sh` —— 停止时杀掉 Node，未配对时不重连

两个问题都导致 WhatsApp 被服务端 401 踢下线（`logged out: the link ended`）：

1. 监控循环里的 `while true; do parent-recap-follow; done` 是前台顺序执行，
   trap 只 kill 了子 shell，`follow`（`os.execv` 后就是 Node）成了孤儿，旧连接还活着；
   新容器一连上，服务端就把旧会话登出。
   → 改成 `parent-recap-follow & child=$!; wait "$child"`，trap 里 `kill -TERM` 子进程。
2. 链路已结束后，循环每 30 秒重连一次，每次都是 401（还会和设置页正在进行的配对抢同一套凭据）。
   → 加 `awaiting_pairing()`：`status.json` 里 `paired` 不是 true 就不启动，只等设置页重新配对。

compose 加 `stop_grace_period: 30s`，让停止有时间把连接关干净。

**代价**：已经失效的配对凭据必须清掉才能重新出二维码（备份在 `data/linked-device/auth.revoked-*`），
然后在设置页的 WhatsApp 步骤重新扫码。

---

## E. 明天的日程不再被丢掉 + 收尾页适配服务器（21:30-21:40）

### E1. `run.py::_ics_candidates` —— 已通知过的「明天」也要进简报

上游只把**没通知过**的事件放进简报（`calendar_action.already_created`）。
一条训练在 10 天前第一次出现时已经被列过一次，于是**它真正要发生的前一晚反而静默**——
用户遇到的正是这个。

改成：已经通知过的也算，只要它「还没结束，且开始日期在今天或明天」（`_ahead()`，按 `cfg.timezone` 判）。
效果：今晚 dry-run 只列出 11-01 周日 10:00 的训练（其余 5 条是更远的未来且已通知，不重复列）。
附带好处：只要明天有日程，晚上就一定会发信（`nothing_to_show` 不再为真），
不再出现「今晚安静所以没发」而错过第二天要准备的事。

.ics 的 UID 由 `event_hash` 生成，重复附上只会更新，不会在日历里产生重复条目。

### E2. 收尾页四项清单在容器里全绿

`setup_status.check()` 四项里有两项在容器里必然失败：

- `installed`：`_installed()` 找的是 `~/ParentRecap/app/pyproject.toml` + `.venv`，
  容器里应用装在 `/opt/venv`，没有这个目录 → ❌
- `nightly`：`jobs.installed()` 靠 `systemctl --user` → 空集 → ○

于是页面显示红色「✗ Parent Recap 已安装」，并弹出「设置先停在这里…把安装那一行再粘贴到终端里…`$parent-recap-setup`」
的横幅（那个命令在容器里根本不存在）。

修法：新增 `PARENT_RECAP_CONTAINER=1`（Dockerfile ENV）：
- `setup_status._installed()`：容器里直接认 `importlib.metadata.version("family-brief")`
- `jobs_linux.installed()` 返回 `{jobs.DAILY}`，`install()` / `remove_all()` 变成空操作
  （排程由 `entrypoint.sh` 的循环负责，没有 timer 可装）
- 顺带 `doctor` 的 schedule 警告消失：现在 `all 12 checks OK`

实测：`Outcome('installed', ok=True, reason='0.10.0 in this container')`、
`Outcome('nightly', ok=True, reason='parent-recap-daily runs every day at 20:00')`。

### E3. `setup_server/finish.py` —— 完成后不关页面

上游 `done` 后 `context.closing = True`，设置页直接停掉。容器里页面是唯一的配置入口
（也是重新配 WhatsApp 的入口），关掉就只能重启容器。
容器模式下改成返回 `stays`，页面留着。

### E4. 文案

`finish.leave.linux`（三语言）：「服务器请保持开机联网：到点它会自己运行，不需要有人登录。」
（原文案是「晚上请让 Mac 睡眠或锁屏，不要关机」）

## F. 用了一晚之后的三处反馈（2026-11-02）

三处都改了实际行为，不是文案。

### F1. Wilma：当天的消息全量汇总，不再按「发过/已读」跳过

原来 `_collect_list` 用 `state.has_seen_message()` 过滤，一条消息只要进过任何一版简报，
之后永远不再出现；Wilma 里被家长读过的也一样被跳过——两者在程序里是同一个东西。

改成：**窗口内全量**。`cutoff` 从 `now - lookback_hours` 改为
`max(now - lookback_hours, state.caught_up_at("wilma"))`，即「上一次把 Wilma 读干净并送达」之后的所有消息，
不论已读与否、不论是否被上一版提过。

- 用 `caught_up_at` 而不是 `last_run_at`：它只在**该来源读完且送达**时前进，跑失败不会推进窗口，不会漏
- 仍然每天只出现一次（窗口从上次送达处开始，天然衔接，不重复）
- 保留 `mark_message_seen` 的写入（`forget_new_seen_messages` 的失败回滚仍依赖它），只是不再拿它做门禁
- **news 的「多给一天」要跟着收**：news 只有发布日期（当天 00:00），原来无条件 `cutoff - 1 day`，
  在 seen 已经不挡重复的情况下会让同一条新闻连发两晚。改成只在**没有 caught_up（首次运行）**时多给一天

### F2. MyClub：只取明天，并把地点与内容带进简报

`collectors/myclub.py` 原本 `LOOKAHEAD_DAYS = 14`，把两周内所有日程都塞进来。11-01 那份简报里
出现「11-15 周日 10:00」就是这么来的——它不是明天，却占了简报唯一的版面。

- 窗口改成**明天的 00:00–24:00**（按 `cfg.timezone`，不是 UTC），`LOOKAHEAD_DAYS` 删除
- 每天晚上只报明天，所以每个事件只会在它前一天的简报里出现一次，不会重复进 .ics
- `run.py::_as_created` 增加 `location` / `description`；`render.py` 的 HTML 与纯文本两条渲染路径
  都在事件下面多一行「地点 · 内容」（都没有时不输出空标签）

### F3. 「明天的课表」不再被整段吞掉（周日简报只剩日历事件的根因）

11-01 那份简报正文完全是空的：入参只有 1 条合成课表（11-02 周一的 13 节课，正文完整）+
1 个 MyClub 事件，`summary.message_digest` 是 `""`。

根因在 prompt：第 4 条只说「课表不是日历事件」，没说它该去哪；再加上「没有新闻就给空 Digest」，
模型就两头都不写——而课表恰恰是「明天要准备什么」的主体。

`summarize.py` 第 4 条补上：课表不进 `calendar_events`，但**必须进 Digest**，每个孩子一行，
说清那天几点开始/结束、以及要家长留意的事（不在本校的课、要带的东西、提早或延后放学），
且不要逐节课罗列。

**验证（全新镜像，`run --dry-run`）**：

```
MyClub: 1 events for Kid B tomorrow (2026-11-03)
wilma messages list: 60 items total, 1 new
wilma news list:     50 items total, 2 new
DRY-RUN: calendar mode=ics, 4 candidate events

### Andy
- 11月3日 周二学校日程：8:30开始，12:20结束。
### Eric
- 11月3日 周二学校日程：9:15开始，12:20结束。
...
• ⚽ Pojat 2019: Honka P2019 treenit — 11月3日 周二 18:30 (Eric)
   <venue, address> · https://club.example.fi/...
```

候选事件从 12 个（含 11-15、12 月一堆）降到 4 个，正文从 0 字到 602 字且带明天的时间。
`doctor` 12/12。

## G. 未来一周的考试（2026-11-02 晚）

Wilma 本身就把考试存成结构化数据，不需要从消息里猜：`wilma exams --json` 给
`{students:[{student, exams:[{date, time, subject, name, topic, teacher}]}]}`，
其中 `topic` 就是「要复习的范围」（章节、页码）。所以整件事不靠模型抽取，只靠模型转述。

### G1. `collectors/wilma.py::_collect_exams` —— 新增一条合成消息

- 窗口 `EXAM_WINDOW_DAYS = 7`：**今天起 7 天**（含今天），按日期排序
- 每个孩子一段，每场考试一行：`[YYYY-MM-DD 周三 · today/tomorrow/in N days]  科目 · 名称  |  to revise: 范围  |  teacher: 老师`
- Wilma 没给 `topic` 的就不写范围（例如 11-26 的 Elämänkatsomustieto），不编造
- `time` 多为 `null`，有则拼在日期后面
- 每晚都生成一条（`external_id = exams:<今天>`），所以「本周考试」是**每天可见的提醒**，不是一次性新闻
- 走现有链路：`source=wilma`、`wilma_kind=exams_next_week`，进模型输入、进 Digest、自动翻译成简报语言

### G2. `summarize.py` —— 一条硬规则

「每条考试单独一行，日期 + 科目 + 名称 + 范围，章节页码照抄，不许合并、不许省略范围」。

**验证**（容器内直接跑，不改镜像）：

```
周一实际数据 7 场（把窗口临时放到 45 天看排版）：
  [2026-11-02 Mon · today]  Englanti, A1 · sanakoe kpl 4 | to revise: Textbook s. 32 ... | teacher: the teacher
  [2026-11-12 Thu · in 10 days] Matematiikka · Mittaaminen | to revise: Kpl 29-37 | ...
  ...（共 7 行，字段齐）

模型输出同样是 7 行：
- 11月2日 周一有英语词汇小测，第4课。                     ← 唯一瑕疵：这条的范围被省了
- 11月12日 周四有数学考试《测量》，复习第29–37课。
- 12月3日 周四有环境学考试《地球与太空》，复习第12–16课、第42–43页和第52–53页。
  ...（其余均带范围与页码）
```

当天真实 dry-run（窗口就是 7 天）也确认了考试进了 Digest：
「11月2日周一有英语 A1 词汇测验，第4课；复习课本第32页的时间表达，以及练习册第48页至橙色横线处的单词。」

**已知瑕疵**：同一条在今天那场被省略范围（单场时反而完整），prompt 已写「不许省略范围」，
先观察几晚；若复现，考虑把考试从模型转述改成独立段落直接渲染（代价：中文简报里会夹芬兰语原文）。

## H. 每天发生的课堂记录（2026-11-02 夜）

对应 Wilma 的 `attendance/view` 页面：老师记的 merkinnät——缺勤、迟到、没带书/没做作业、表扬，
每条挂在某一节课上，可能带老师原话。`wilma notes --json` 直接给结构：
`{date | from+to, students:[{student, notes:[{date, start, end, subject, typeLabel, teacher, note}]}]}`
（默认就是「今天」，`--days N` 取区间）。

### H1. `collectors/wilma.py::_collect_notes` —— 每条记录一条 Message

- 窗口 `NOTE_LOOKBACK_DAYS = 2`：老师常在**第二天**才补记前一天的课，只看今天会漏
- 去重按指纹 `sha1(date|start|course|typeLabel|note[:60])`，进 `state`，所以补记能进、重复不会
- `Message.subject` = `课程代码 · 类型标签`（如 `YM07 · Opettajan kommentti (…), Kotitehtävät tekemättä`）
- `body` = 老师原话；**Wilma 没给原文时留空**，不编造
- `kid_hint` = 学生名，`sender` = 老师，`timestamp` = 那节课的日期+开始时间

### H2. `summarize.py` —— 一条规则

「课堂记录写进该孩子的 Digest：日期与课程、是哪一类、老师要点的转述；**没有原文时说记录在 Wilma 的出勤页**，
不要猜原因；如果这条记录要求家长做事（交作业、带书、回复），同时生成待办。」

**验证**（容器内把窗口临时放到 20 天跑，未改镜像；本周暂无记录，故用历史数据）：

```
采集到 3 条（Andy）：
10-29 10:00 | YM07  | body: ''                      ← 老师只写了「去 Wilma 看」
10-28 10:00 | SU207 | body: ''
10-22 14:00 | SU207 | body: 'the pupil had no notebook and no pen…'

模型输出：
- 10月29日的环境与自然课（YM07）：缺少作业；老师的评论可在 Wilma 查看。
- 10月28日的芬兰语课（SU207）：缺少作业；老师的评论可在 Wilma 查看。
- 10月22日的芬兰语课（SU207）：老师说，Andy 没带笔记本和笔；尽管老师提醒用纸代替缺少的笔记本，
  课堂上仍有很多时间花在坐着不动。
```

日期、课程、类型、原文转述都对；空原文没有编造。

**顺带核实**：归档 `2026-11-02.md` 里内容看起来出现两遍（摘要 + 注意事项），
查证是**归档 md 的设计**（digest / notices / 待办分段全记），邮件正文只有 digest——
`render._shown_digest()` 仅在 digest 为空时才用 notices 顶上。邮件不重复。

## I. 群聊概述更详细 + 投票不再丢内容（2026-11-03 晚）

### I1. `baileys/linked_device.mjs` —— 投票带上题目与选项

原来 `pollCreationMessage*` 一律记成 `"[poll]"`，投票问的是什么、有哪些选项全都丢了。
改成 `[poll] <题目> — <选项1> / <选项2> …`，`caption` 仍然优先（带文字说明的投票）。
只影响**新收到**的投票；已存的记录里仍是 `[poll]`。

### I2. `summarize.py` —— 群聊要写细节（第 5 条，正文规则）

第一版写在 Notes 里，模型没执行：仍然压成一句「1B 班级聚会定于11月18日…，兄弟姐妹也欢迎参加」，
丢了「自带食物（nyyttärit）」和投票。原因是被更靠前的「简洁 / at most 8 points」约束压过去了。

改成放进 **Your job 第 5 条**（编号顺延到 8），并给了一个「什么算够详细」的示例，
明确「普通闲聊仍然不占行」。Notes 里那条改成引用第 5 条，避免两处重复。

**验证**（同一批原文，容器内直接跑，不发信）：

改前：`1B 班级聚会定于11月18日 周三17:00至20:00，在镜子厅和一年级学习村举行；兄弟姐妹也欢迎参加。`

改后：
```
1B班级聚会定在11月18日（周三）17:00–20:00，在镜厅和一年级学习村举行；投票选中了这一天，
大家自带食物分享，兄弟姐妹也欢迎参加。孩子们据说会安排一些小活动，其余没有正式节目；
一位家长会在11月4日（周三）询问老师能否在学习村用餐，并愿意协助筹备，目前尚未确认能否在那里用餐。
```
日期、投票结果、自带食物、待确认事项都保住了。

## J. 第二个 WhatsApp 账号（后台，2026-11-03 夜）

目标：两个不同的 WhatsApp 号，各自覆盖**不同的群**（用户 2026-11-03 确认），互不干扰。
第一个号必须与改造前**完全一致**，否则会破坏已在用的配对与「已读」记录。

### J1. `config.py` —— 账号模型，旧配置不动

- 新增 `WhatsAppAccount {id, label, chats}`；`WhatsAppConfig.accounts` 存第二个及以后的号
- **第一个号仍然存在原有的 `chats` 字段里**，所以任何读 `cfg.whatsapp.chats` 的旧代码（设置页、
  保存逻辑）行为不变
- 新增 `all_accounts() -> [(id, chats)]`、`chats_of(id)`、`all_chats()`；
  `picked_ids(account="1")`、`kid_for()` 支持多号（`kid_for` 扫全部，群 id 本就唯一）

### J2. `linked_device.py` —— 路径与命令按号分组

- `account_folder("1")` = 原来的 `linked-device/`（`auth`、`messages.jsonl`、`status.json`、
  `picked-groups.json` 全在原处）；其他号在 `linked-device/accounts/<id>/`
- `command()`、`link()`、`records()`、`prune()`、`picked_records()`、`keep_picked()`、`mark_paired()`
  全部加 `account="1"` 默认参数，旧调用点自动指向第一个号

### J3. `nas/follow.py` —— 一个号一个进程

原来 `os.execv` 把自身替换成单个 Node，只能守一个号。改成：

- 每个号一条 `follow` 命令、一个子进程（WhatsApp 会因两个连接用同一配对而断链，**不能共用**）
- 15 秒退避重启；收到 SIGTERM/SIGINT 时先 `terminate` 全部子进程、最多等 25 秒，让它们把链接关干净
  （这正是配对不掉的关键，与 `stop_grace_period: 30s` 配合）

### J4. `collectors/whatsapp.py` —— 合并两个号的记录

- 逐号 `keep_picked` → 读 `records` → `picked_records` → `prune`，合并成 `(account, record)`
- **第一个号的 external_id 保持原样**（否则「已发过」的指纹全部失配，一次重报）；
  其他号加 `<id>:` 前缀
- `connected()` 要求**每个号**都配对且有群；`unread()` 报告第一个需要重配的号

### J5. `ops.py` —— 体检分行

单号时输出与改造前逐字一致；多号时每句以 `account <id>:` 开头，`; ` 连接。

**验证（无网络、只读挂载，绝不连 WhatsApp）**：

```
accounts: [('1', ['1B parents'])]
first account external_id: AAA          ← 第一个号不变
second account external_id: 2:BBB       ← 第二个号带前缀

doctor 单号: ('✅', 'whatsapp', 'connected since 2026-11-03 17:27, keeping 1 picked group: "1B parents"')
doctor 双号: ('❌', 'whatsapp', 'account 1: connected since …; account 2: needs a new pairing: …')

follow 命令:
  1 -> --store /root/ParentRecap/linked-device/messages.jsonl
  2 -> --store /root/ParentRecap/linked-device/accounts/2/messages.jsonl
```

切换后生产环境：日志出现 `starting account 1: …`，`status.json` 立刻 `paired: true`，
`connected_since` 刷新，`doctor` 12/12。

### ⚠️ 事故与教训（本次）

第一次验证时用 `docker run` 跑了带**真实 WhatsApp 凭据副本**的容器，且没覆盖 `ENTRYPOINT`，
结果卡在 entrypoint 的日常循环里——等于第二个 Baileys 会话用同一配对连接，**可能导致生产者断链**。
发现后立刻 `docker rm -f`，生产 `status.json` 仍是 `paired: true` / `link_ended_at: null`，未受影响。

此后验证一律：`--network none` + 只读挂载 + `--entrypoint /opt/venv/bin/python`，
只跑纯逻辑，不碰连接。

### 还没做的（下一步）

设置页的「添加第二个账号」按钮：需要 `setup_server/whatsapp.py` 的 `_Run` 支持按号并存、
`_paired()` 写进对应账号而不是覆盖 `chats`、页面跨语言文案，**并且必须由第二部手机实扫一次才算验证**。
在那之前，第二个号只能靠命令行配对（`linked_device.command("pair", cfg, account="2")`），
对使用者不友好，所以没有交付为「可用」。
