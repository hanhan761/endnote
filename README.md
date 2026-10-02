# endnote

**end 的时候 note 一下。** 为长时间实验提供条件触发的邮箱通知，运行在授权的 4090 工作站。

公开入口：https://am.matterswarm.com/endnote/
源码：https://github.com/hanhan761/endnote

## 快速使用

1. 打开网页，验证自己的收件邮箱，并安全保存账号密钥。重新验证相同邮箱会替换账号密钥。
2. 下载仓库，设置 ENDNOTE_API_KEY（或用 CLI 验证后保存到自己的私有配置目录）。
3. 在仓库根目录运行：

~~~bash
python -m endnote.client run --name "train" -- python train.py
~~~

包装器每 60 秒发送心跳，进程正常结束时报告 succeeded，非零退出时报告 failed。
服务默认 300 秒未收到心跳就提醒。实验命令在本机或你选择的计算机运行，API 不执行实验。

把 SDK 放进训练代码：

~~~python
from endnote.client import Client

with Client().experiment(
    "模型训练",
    runtime_timeout=7200,
    rules=[{"metric": "loss", "op": "lt", "value": 0.01}],
    subject="[endnote] $name · $reason",
    body="状态：$status\n说明：$message\n指标：$metrics",
) as run:
    for epoch in range(100):
        loss = train_one_epoch()  # 替换为你的训练代码
        run.metric(epoch=epoch, loss=loss)
~~~

客户端优先使用 ENDNOTE_URL / ENDNOTE_API_KEY；也可从 ~/.config/endnote/credentials.json 读取。
账号密钥只能通过 HTTPS 发往你信任的服务。SDK 禁止鉴权请求跟随重定向。
CLI 验证流程：

~~~bash
python -m endnote.client request-code --email you@example.com
python -m endnote.client verify --email you@example.com
~~~

verify 会在交互输入验证码后，将账号密钥保存到用户配置目录，密钥不会输出到终端。
Windows 上应保证该目录仅由自己的账户访问。

## 触发规则

| 条件 | 行为 |
|---|---|
| succeeded / failed | 每个实验终态提醒一次 |
| heartbeat_timeout | 每次失联提醒一次，收到新心跳后重新布防；两次提醒至少间隔 15 分钟 |
| runtime_timeout | 达到运行时长后提醒一次，不终止实验 |
| 指标阈值 | 每条规则命中时提醒一次；支持 gt / gte / lt / lte / eq |

邮件主题和正文可使用 $name、$status、$reason、$message、$metrics、$time，字面美元符用 $$。
正文为纯文本，不执行模板表达式或用户代码。通知收件人固定为该账号已验证的邮箱；
需要不同收件邮箱时，验证对应邮箱并使用其账号密钥。

心跳只证明上报进程存活，不证明训练取得进展。卡住的循环可以继续有自动心跳，
需在关键步骤主动上报指标，或直接接入事件 API 并在取得进展时发送心跳。
不会监控服务器上的任意文件、PID、日志，也不会自动重启实验。

## HTTP API

基地址：https://am.matterswarm.com/endnote

| 方法与路径 | 鉴权 | 功能 |
|---|---|---|
| POST /v1/auth/request | 无 | 请求邮箱验证，JSON: email |
| POST /v1/auth/verify | 无 | 提交 email、code，返回一次性展示的账号 api_key |
| POST /v1/auth/rotate | 账号密钥 | 替换账号密钥，原账号密钥立即失效 |
| POST /v1/tasks | 账号密钥 | 创建实验，返回 id 和仅展示一次的 task_key |
| GET /v1/tasks | 账号密钥 | 列出自己的实验 |
| GET /v1/tasks/{id} | 账号密钥 | 查看条件、指标和通知投递状态 |
| DELETE /v1/tasks/{id} | 账号密钥 | 删除实验及待发送通知，撤销实验密钥 |
| POST /v1/tasks/{id}/events | 对应实验密钥或账号密钥 | 上报实验状态、心跳、指标 |
| GET /health | 无 | 服务及邮件工作器健康状态 |

鉴权头：Authorization: Bearer YOUR_KEY。密钥不得放入 URL。

创建实验的 JSON：

~~~json
{
  "name": "train",
  "heartbeat_timeout": 300,
  "runtime_timeout": 7200,
  "notify_on": ["succeeded", "failed", "heartbeat_timeout", "runtime_timeout"],
  "rules": [{"metric": "loss", "op": "lt", "value": 0.01}],
  "subject": "[endnote] $name · $reason",
  "body": "状态：$status\n说明：$message\n指标：$metrics"
}
~~~

创建后立即计时。上报事件：

~~~json
{
  "event_id": "a-unique-id-per-event",
  "type": "metric",
  "message": "epoch 10",
  "metrics": {"epoch": 10, "loss": 0.005}
}
~~~

事件类型：heartbeat / metric / succeeded / failed / cancelled。
任何有效事件均更新心跳。终态不允许回到 running。相同 event_id 的重试不会重复触发通知，
每个实验保留最近 1000 个事件 ID；终态事件的 ID 因终态不可追加而持续保留。
事件按服务器接收顺序处理，不接受客户端时间戳来回写过去的状态。

## 安全与容量边界

- 4090 上服务只监听 127.0.0.1:8380，公网流量经现有 Cloudflare Tunnel / HTTPS。
- 独立 systemd DynamicUser、可写状态目录、只读程序、禁止提权、内存及进程上限。
- 账号隔离；实验密钥只能上报其对应实验，不能查询账号或其他实验。
- 密钥只存 SHA-256 摘要；验证码为 256 位随机值，15 分钟有效，仅一次可用。
- API 最多 16 KiB 请求体、32 个请求线程；拒绝跨域、邮件头注入、非有限数值和可执行规则。
- 默认每账号 20 个运行实验、200 个总实验；全站 500 个账号、10000 个实验。
- 默认每天全站 300 次 SMTP 发送尝试、每账号 30 次；每次重试也计费配额。超限的邮件待发送。
- 邮箱验证每邮箱每小时 3 次、每 IP 每小时 5 次、全站每天 60 次。
- 活跃邮件队列最多 2000 条；队列满时，触发内容先存入持久化延后表，释放容量后再入队。
  阈值命中的瞬时指标会保留，任务详情可查看 deferred_notifications。
- 指标值与消息由调用方提交，不应包含密码、密钥或未授权的个人数据。自动失败消息只发送异常类型。
- 正常结束的实验及通知记录保留 30 天；运行实验需自己结束或删除。
- 运行服务没有 SSH、文件访问、任务执行或用户指定出站 URL 的 API。
- 使用现有 SMTP 的凭据最小副本；独立凭据文件不包含教学平台或其他服务的秘密。
- 不开放用户自选发件人、SMTP 地址、附件或任意收件人，以避免开放邮件中继。
- 公开注册可通过 ENDNOTE_SIGNUP_ENABLED=false 停用，不影响现有实验。
- API key 轮换仅撤销账号密钥，已签发实验密钥持续有效；撤销实验密钥请删除对应实验。

**边界**：本服务是提醒系统，不保证实验不中断。若 4090 本身断电、断网或服务停止，
邮件只能在恢复后继续处理。需要及时检测整台 4090 故障时，应配置另一台机器上的外部监控。
SMTP 投递具有至少一次尝试语义：SMTP 已接受但数据库落盘前崩溃，重试可能导致重复邮件；
固定 Message-ID 有助于接收方识别重复，但不保证去重。sent 代表 SMTP 接受，不保证收件箱送达。

## 本地开发

Python 3.10+，运行时无第三方依赖。

~~~bash
python -m unittest discover -s tests -v
python -m endnote.server
~~~

访问 http://127.0.0.1:8380/endnote/ 。默认关闭注册和真实邮件。
启用邮件时，用 ENDNOTE_SMTP_FILE 指向不在仓库内的 SMTP JSON 凭据，
并设置 ENDNOTE_MAIL_ENABLED=true、ENDNOTE_SIGNUP_ENABLED=true。

部署、凭据隔离和回滚见 [deploy/README.md](deploy/README.md)。
邮件 TLS 使用 Python smtplib 的 SMTP_SSL / STARTTLS；
文档：https://docs.python.org/3/library/smtplib.html

## Codex 技能

把 skills/endnote 复制到自己的 ~/.codex/skills/endnote，随后使用 $endnote。
技能内含独立 CLI，可从任意目录接入这个接口。技能不会获得服务器登录权。
