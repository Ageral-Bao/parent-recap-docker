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
