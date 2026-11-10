# 后端 MVP（可直接跑）

FastAPI + yt-dlp + ffmpeg + 可选 faster-whisper。已实现：链接识别、公众号解析、B站/抖音等 yt-dlp 解析、字幕优先、音频转写、清洗、结构卡、额度、签到、分片上传、简单上传。

## 启动

```powershell
cd E:\轻抖复刻\06-代码\server
$env:MOCK_ASR = "1"          # 没有 GPU/ASR 时先占位
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8788
```

打开 http://127.0.0.1:8788/docs 看接口文档。

## 已验证（2026-11-04 实测）

| 用例 | 结果 |
|---|---|
| `GET /api/health` | 200，yt-dlp 2026.08.19 |
| 公众号文章（本地 fixture）→ 任务 → 结果 | done，5 句，结构卡 79 分 |
| 上传 3 秒 mp3（分片 12,734 字节）→ 任务 → 结果 | done，分片偏移正确 |
| B 站真实链接 `BV1GJ411x7h7` | done，标题正确，音频下载 + 转写链路通 |
| 额度 / 签到 | 用尽后 429；签到 +1 后恢复 |

原始输出见 `tests/`（smoke.py / smoke_media.py / smoke_link.py）。

## 真实 ASR

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper
$env:MOCK_ASR = "0"
```

首次会下载模型（small ≈ 500MB）。生产建议：
- 中文短视频：火山/阿里云端 ASR，按量计费；
- 隐私/敏感内容：本地 faster-whisper；
- 两者都失败时，前端降级为"仅出字幕/稍后重试"。

## 导出与素材库

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks/{id}/export?fmt=txt\|md\|srt\|docx\|xlsx\|json` | 单条导出 |
| POST | `/api/export/batch` | `{ids, fmt, zip}`，最多 100 条 |
| GET | `/api/tasks?q=&platform=&fav=1&tag=` | 搜索 / 筛选 / 分页 |
| PATCH | `/api/tasks/{id}` | 标题 / 收藏 / 标签 |
| GET | `/api/task-tags` | 标签云 |

docx / xlsx 由 `app/exporters.py` 直接写 OOXML，不依赖 python-docx / openpyxl。
验证：`tests/smoke_export.py`（50 项）。

## 目录

```
app/
  main.py            接口
  pipeline.py        任务编排
  platforms.py       链接识别
  structure.py       结构卡
  text.py            清洗分段
  exporters.py       导出（TXT/MD/SRT/DOCX/XLSX/JSON/ZIP）
  asr.py             ASR 适配层
  db.py              SQLite（生产换 PostgreSQL）
  resolvers/
    article.py       公众号
    media.py         yt-dlp 封装 + VTT 解析
tests/               冒烟脚本与 fixture
```

## 登录

- 小程序：`wx.login` → `POST /api/auth/wechat` → 服务端 `jscode2session` → 30 天 HMAC token
- APP：同一接口，`platform="app"`，配 `WX_APP_APPID/WX_APP_SECRET`
- 所有业务接口：`Authorization: Bearer <token>`
- `GET /api/auth/me` 查当前身份
- `POST /api/dev/login` 仅 `DEV_MODE=1`，本地拿测试 token

`X-User-Id` 只在 `DEV_MODE=1` 时接受，生产必须关。

## 上线前必须补

1. PostgreSQL + Redis 队列，替换进程内 `asyncio.create_task`。
2. 内容安全接口（msgSecCheck / mediaCheckAsync）。
3. 微信商户号/证书（代码已接 v3 下单、回调验签、幂等入账，缺真实商户配置）。
4. SSRF 防护（域名白名单 + 内网 IP 拒绝）。
5. 解析成功率监控与平台级熔断。
6. OSS 生命周期 24h 自动删除。

## 已知限制

- 抖音/快手/小红书需要签名与 Cookie 池，当前未内置（yt-dlp 对其支持不稳定）。
- 视频号无公开链接，必须上传。
- `MOCK_ASR=1` 时上传音频返回占位文本，仅用于验证链路。

## BYOK 接口（2026-11-04 新增）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/features` | 每个功能的免费次数与剩余 |
| GET | `/api/keys` | 掩码密钥 + 服务商预设 |
| POST | `/api/keys` | 保存（默认先测试；`skip_test=true` 可跳过） |
| POST | `/api/keys/{id}/test` | 重新测试 |
| DELETE | `/api/keys/{id}` | 删除 |

实测：
- 保存 DeepSeek Key 返回 `****abcd`，明文不回传
- 2 次免费后第 3 次返回 `402 TRIAL_ENDED`
- 删除后列表为空
- 任务失败自动退回本次消耗（免费次数或额度）
- 签到只增加当日上限，`used` 不会出现负数

密钥存储：**AES-256-GCM**（随机 12 字节 nonce，密文带 `gcm1:` 前缀）；主密钥在 `data/master.key` 或 `BYOK_MASTER_KEY`。旧 Fernet 密文保留解密兼容。
生产必须改成 KMS/环境变量，并给 `data/master.key` 做权限隔离。


## 托管额度与支付（2026-11-04 新增）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/products` | 6 个 SKU |
| GET | `/api/wallet` | 余额、会员到期、订单 |
| POST | `/api/orders` | 下单；`DEV_MODE=1` 返回 mock |
| POST | `/api/orders/{id}/mock-pay` | 开发模式模拟支付 |
| POST | `/api/redeem` | 兑换码 |
| POST | `/api/pay/notify/wechat` | 微信 v3 回调：验签 + AES-GCM 解密 + 幂等 |
| POST | `/api/dev/redeem` | 开发模式生成测试码 |

实测（`tests/smoke_billing.py`）：

- 买 30 次 → 余额 30；重复回调仍为 30（幂等）
- 兑换码 → 30 次；同码第二次 `CODE_USED`
- 买 BYOK 月卡 → `plan=pro`，写入到期时间
- 额度任务失败 → 余额自动退回

支付配置见 `07-部署/.env.example`；未配置时自动降级为兑换码，不影响其他功能。

## 火山引擎 ASR（2026-11-04 新增）

1. 在密钥页选“火山引擎”，填 `AppID:AccessToken:Cluster`（Cluster 默认 `volc_auc_common`）。
2. 服务端自动用 ffmpeg 转 16k 单声道 wav。
3. 生成 1 小时有效的签名音频 URL 给火山拉取（需配 `PUBLIC_BASE_URL`）。
4. 提交 `/api/v1/auc/submit`，轮询 `/api/v1/auc/query`，解析 `utterances` 时间轴。

本地已用假服务商跑通提交/轮询/时间轴：`tests/smoke_volc.py` → `VOLC_PASS`。
真实环境只需配 `PUBLIC_BASE_URL=https://api.你的域名.com` 和火山 Key。

## 链接跑通率测试

```powershell
# 编辑 tests/links.json（或 links.template.csv 填 60 条）
.\venv\Scripts\python.exe tests\link_matrix.py --timeout 180
```

输出 `links_result.json` / `links_result.csv`，按平台统计 success/total。
每条链接用独立测试用户，避免 2 次免费额度干扰。

## 平台 Cookie

把 Netscape 格式的 Cookie 放到 `data/cookies/{platform}.txt`（如 `douyin.txt`、`xiaohongshu.txt`），
yt-dlp 会自动带上；没有 Cookie 时抖音/小红书成功率会明显偏低。


## 管理后台（2026-11-04 新增）

启动时设置：

```powershell
$env:ADMIN_PASSWORD = "换成长密码"
$env:ADMIN_SECRET = "换成长随机串"
```

打开 http://127.0.0.1:8788/admin

| 页面 | 能做什么 |
|---|---|
| 概览 | 用户数、今日任务、成功率、累计收入 |
| 功能额度 | 全局默认 + 4 个功能分别设置免费次数 |
| 用户 | 搜索用户、+3 次、+30 额度、看详情 |
| 兑换码 | 生成/查看兑换码 |
| 审计日志 | 谁在什么时候改了什么 |

接口都在 `/api/admin/*`，两种凭证都收：

- 网页：`ADMIN_PASSWORD` 换的 12 小时 admin token
- 手机：已登录用户 token + `ADMIN_USER_IDS` / `admins` 白名单

`ADMIN_PASSWORD` 为空只是关掉网页密码登录，手机端仍可用名单进入。
生产建议再加 IP 白名单 / 2FA。

实测：`tests/smoke_admin.py` → `ADMIN_PASS`
（4 个功能配置、用户补偿 +3、加额度 +30、开会员 30 天、兑换码、审计日志全部通过）
