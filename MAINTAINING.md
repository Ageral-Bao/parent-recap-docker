# 维护者手册：把补丁搬到上游新版本

本仓库的 `app/` 不是原封不动的上游代码：它是上游 **v0.10.0（commit `6e96d02`）** 加上 25 个文件的改动，
**+848 / −241 行**。这些改动不是散落的手改，而是 git 提交，所以可以整套搬到上游的任何新版本上。

本文件讲的就是那件「上游发新版之后该怎么做」的事。只自用、不跟上游的话，看 [README](README.md) 就够了。

## 1. 先留退路

```bash
docker tag <当前镜像>:0.10.0 <当前镜像>:rollback
git -C . log --oneline -1          # 记下当前基线
```

## 2. 拉上游

```bash
git clone https://github.com/kinlace/parent-recap.git upstream
cd upstream
git fetch --tags
git checkout <新 tag 或新 commit>
```

## 3. 把补丁叠上去

补丁来自本仓库的 `app/` 与上游基线之间的 diff。取出来的两种办法，任选其一：

```bash
# 办法一：直接对本仓库 app/ 下的文件做 diff（推荐，无需历史）
diff -ru upstream/app app/ > /tmp/nas-docker.patch    # 需要时用 patch -p1 应用

# 办法二：在本仓库里先提交一次，再用 format-patch 导出（有历史、能 git am）
git format-patch 6e96d02..HEAD -o /tmp/patches/
git am -3 /tmp/patches/0001-*.patch
```

`-3`（三方合并）比默认更容易自动合上。冲突时：

```bash
git status                 # 看哪些文件冲突
# 手改完 → git add <文件> → git am --continue
# 放弃重来 → git am --abort
```

## 4. 冲突时按这个顺序判断

上游最爱重构的就是下面这几处，冲突都发生在这里：

| 冲突文件 | 处理原则 |
|---|---|
| `sources.py` 里 WhatsApp 的 `systems` | 上游原本把 `linux` 关掉了。**若新版本已支持 Linux，这段整块丢掉**，功能等价 |
| `system/jobs_linux.py::run_detached` | 上游原本是个抛异常的桩。**若新版本有真实实现，以上游为准**，我们的丢弃 |
| `config.py` 的 `EmailConfig.sender` + `actions/email.py` 的 Gmail 分支 | **若上游已支持自有 SMTP，整块换成上游写法**，别再叠加 |
| `run.py::_ics_candidates` | 我们的版本保留「已通知过但还在明天」的事件。若上游改了过滤逻辑，以「明天的日程不能丢」为准重写 |
| 设置页相关（`setup_server/*`、`page/*`） | 多是新增文件或纯前端，冲突概率低，按新版本结构调整即可 |

改完确认补丁确实在：

```bash
grep -c sender app/src/family_brief/config.py          # 期望 >= 1
grep -n "gmail" app/src/family_brief/actions/email.py | head -3
```

## 5. 三处版本号要一起改

```bash
grep -n '^version' app/pyproject.toml                       # 程序版本
grep -n 'image:' nas/docker-compose.yml                      # 镜像标签
grep -rn '0\.10\.0' . --include="*.yml" --include="*.md"     # README / compose / .env.example
```

## 6. 构建并验收

```bash
docker compose -f nas/docker-compose.yml build      # 3–5 分钟，npm + pip
docker compose -f nas/docker-compose.yml up -d
```

验收清单（不要只看容器起没起来）：

- [ ] `docker exec parent-recap parent-recap doctor` **12/12 全绿**
- [ ] 手动跑一次 `docker exec parent-recap parent-recap run` 成功
- [ ] 邮件正文里有**明天的**日历事件（MyClub）
- [ ] 邮件页脚**没有** "unattended sender" 一类的话（Gmail 发信时不该出现）
- [ ] 设置页能打开、能保存、收件人可增删、发件地址有明示
- [ ] 日志里 `next run at <明天的 20:00>`
- [ ] WhatsApp 没掉线（`data/linked-device/status.json`）

## 7. 回滚

```bash
# 改回旧标签，或用留好的 rollback 镜像
sed -i 's|image: .*|image: <镜像>:rollback|' docker-compose.yml
docker compose up -d
```

## 8. 踩过的坑

| 现象 | 原因 | 做法 |
|---|---|---|
| 起不来，日志 `unknown instruction: PARENT_RECAP_CONTAINER=1` | `Dockerfile` 的 `ENV` 多行续行漏了 `\` | 改完 `sed -n '8,18p' nas/Dockerfile` 看每行末尾 |
| 脚本 `exec format error` / `syntax error` | `.sh` 被 Windows 存成 CRLF | 仓库已有 `.gitattributes` 的 `* text=auto eol=lf`；手工拷贝时用 `tr -d '\r'` 兜底 |
| 第一次运行 `make-failed` | `jobs_linux.run_detached` 是抛异常的桩 | 见上表第 2 行，别让它回退成桩 |
| 简报丢了明天的日程 | `run.py` 把「已通知过的明天」过滤掉了 | 见上表第 4 行 |
| WhatsApp 每次重启就掉线 | 旧 Node 进程还连着，第二个连接被判重复 | `entrypoint.sh` 先杀子进程，compose 需 `stop_grace_period: 30s` |
| 设置页保存后 `email.sender` 消失 | `setup_save._merge` 把它删了 | 检查 `_merge` 里没有 `pop("sender")` |
