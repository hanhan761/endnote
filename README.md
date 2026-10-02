# endnote

![endnote 功能概览：实验通过 Python SDK 或 HTTP API 上报状态，按完成、失败、失联、超时和指标条件触发邮箱通知](docs/images/endnote-overview.png)

**end 的时候 note 一下。**

endnote 是一个面向长时间实验和后台任务的邮件提醒接口。你的程序上报状态、心跳或指标，endnote 在条件满足时向你验证过的邮箱发通知，帮助你及时知道任务完成、失败或失联。

**[打开网页开始使用](https://am.matterswarm.com/endnote/)** · [Python 客户端](endnote/client.py) · [HTTP API](#http-api) · [Codex 技能](#codex-技能)

## 可以提醒什么？

| 你关心的情况 | 提醒条件 |
| --- | --- |
| 实验结束了 | 程序报告成功或失败 |
| 进程突然退出、机器断网了 | 超过指定时间未收到心跳 |
| 实验运行得太久了 | 达到你设定的运行时长 |
| 指标达到目标或出现异常了 | 例如 loss < 0.01、temperature > 80 |

你可以自定义邮件标题和正文。使用公开接口不需要自己部署服务器或配置发件邮箱；你只需要一个收件邮箱，以及能访问 HTTPS 的实验程序。

## 快速开始

Python 客户端需要 **Python 3.10 或更新版本**，没有第三方运行依赖。

### 1. 获取客户端

~~~bash
git clone https://github.com/hanhan761/endnote.git
cd endnote
~~~

### 2. 验证你的收件邮箱

在仓库根目录运行，把示例邮箱替换为自己的邮箱：

~~~bash
python -m endnote.client request-code --email you@example.com
python -m endnote.client verify --email you@example.com
~~~

第二条命令会提示你输入邮件中的完整验证码，并将账号密钥保存到自己的用户配置目录。后续客户端会自动读取，不需要每次输入密钥。

也可以在[网页](https://am.matterswarm.com/endnote/)验证邮箱、领取账号密钥，再通过 ENDNOTE_API_KEY 环境变量交给客户端。不要把真实密钥写进代码、提交到 Git 或放进 URL。

> 验证码 15 分钟内有效，以最新一封为准。重新验证同一个邮箱会替换原账号密钥；已创建实验的独立密钥仍然有效。

### 3. 给任务加上提醒

先运行一个十秒钟的小任务，检查接入：

~~~bash
python -m endnote.client run --name "我的第一个任务" -- python -c "import time; time.sleep(10)"
~~~

任务结束后，endnote 会将完成通知加入邮件发送队列。查看实验状态：

~~~bash
python -m endnote.client list
~~~

接入真实实验时，将最后的命令换成你的实验命令：

~~~bash
python -m endnote.client run --name "模型训练" -- python /path/to/train.py
~~~

包装器默认每 60 秒发送一次心跳，300 秒未收到心跳则触发失联提醒；正常退出报告成功，非零退出报告失败。实验在你运行命令的计算机上执行，endnote 接口只接收通知事件。

命令在当前工作目录运行。如果实验依赖自己的项目目录，请在该目录调用仓库内的独立脚本：

~~~bash
python /path/to/endnote/skills/endnote/scripts/endnote.py run --name "模型训练" -- python train.py
~~~

这里的 /path/to/... 是示例路径，请换成你自己的实际路径。

## 在 Python 代码里按指标提醒

在能够导入 endnote 的项目中使用 SDK：可以在本仓库根目录运行示例，或将仓库中的 endnote 目录复制到你的实验项目。

下面的代码模拟上报训练指标；实际接入时，把模拟循环替换为自己的训练代码：

~~~python
import time
from endnote.client import Client

with Client().experiment(
    "模型训练",
    heartbeat_timeout=300,
    heartbeat_interval=60,
    runtime_timeout=7200,
    rules=[{"metric": "loss", "op": "lt", "value": 0.01}],
    subject="[endnote] $name · $reason",
    body="实验：$name\n状态：$status\n说明：$message\n指标：$metrics",
) as run:
    for epoch in range(8):
        time.sleep(1)
        loss = 0.5 ** (epoch + 1)  # 示例值，替换为实际指标
        run.metric(epoch=epoch, loss=loss)
~~~

进入上下文时创建实验并开始自动心跳；正常离开报告成功，发生异常报告失败。指标需要你的代码主动上报，客户端不会自动解析日志。

规则支持 gt、gte、lt、lte、eq，分别表示大于、大于等于、小于、小于等于、等于。每个实验最多配置 10 条规则，每条命中后提醒一次。

**自动心跳只证明上报进程仍然存活，不能证明训练正在取得进展。** 如果你要检测循环卡住，应在实际完成关键步骤后上报心跳，并配置合适的运行超时条件。

## 自定义通知

在网页创建实验，或通过 SDK / HTTP API 设置以下字段：

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| name | 实验名称，必填 | — |
| notify_on | 要启用的状态和超时提醒 | 成功、失败、失联、运行超时 |
| heartbeat_timeout | 失联阈值，单位秒，范围 30–86400 | 300 |
| runtime_timeout | 运行时长阈值，单位秒，范围 30–2592000 | 不启用 |
| rules | 指标阈值规则 | 无 |
| subject | 邮件标题，必须为单行 | [endnote] $name · $reason |
| body | 纯文本邮件正文 | 实验名称、状态、触发原因等 |

邮件模板支持这些变量：

| 变量 | 内容 |
| --- | --- |
| $name | 实验名称 |
| $status | 实验当前状态 |
| $reason | 触发提醒的条件 |
| $message | 你上报的说明 |
| $metrics | 你上报的指标 |
| $time | 触发时间，UTC |

要显示字面美元符，写成 $$。模板只替换文字，不执行表达式或代码。

通知只发送到当前账号验证过的邮箱。使用另一个收件邮箱时，验证那个邮箱并使用对应账号；用户不能冒用别人的收件地址或任意修改发件人。

## HTTP API

任何能发送 HTTPS JSON 请求的语言都可以接入，不必使用 Python。

**基地址：** https://am.matterswarm.com/endnote

鉴权头为 Authorization: Bearer YOUR_KEY。需要 POST 请求时，设置 Content-Type: application/json。

有两种密钥：

- **账号密钥**：创建、列出、查看和删除自己的实验。
- **实验密钥**：只允许上报对应实验的事件，适合放在实验脚本中。

### 创建实验

用账号密钥调用 POST /v1/tasks：

~~~json
{
  "name": "模型训练",
  "heartbeat_timeout": 300,
  "runtime_timeout": 7200,
  "notify_on": ["succeeded", "failed", "heartbeat_timeout", "runtime_timeout"],
  "rules": [{"metric": "loss", "op": "lt", "value": 0.01}]
}
~~~

返回示例：

~~~json
{
  "id": "0123456789abcdef0123456789abcdef",
  "task_key": "en_task_YOUR_TASK_KEY",
  "status": "running",
  "heartbeat_timeout": 300
}
~~~

请保存实验 ID 和实验密钥；密钥只在创建时返回。**创建后立即开始计时**，请及时接入心跳。

### 上报状态、心跳和指标

用对应实验密钥调用 POST /v1/tasks/{id}/events。

心跳：

~~~json
{"event_id": "heartbeat-001", "type": "heartbeat"}
~~~

指标：

~~~json
{
  "event_id": "epoch-010",
  "type": "metric",
  "message": "第 10 轮训练完成",
  "metrics": {"epoch": 10, "loss": 0.005}
}
~~~

成功结束：

~~~json
{"event_id": "finished-001", "type": "succeeded", "message": "训练完成"}
~~~

失败结束时将 type 换成 failed；取消时使用 cancelled。取消会结束监控，默认不发邮件。

任何有效的新事件都会更新心跳。成功、失败或取消后，实验不能恢复为运行状态；重跑请创建新实验。

**同一事件重试时沿用原 event_id，不同事件使用不同 ID。** 服务保留每个实验最近 1000 个事件 ID，识别到重试后不会再次触发通知。重试不更新心跳。

### 接口列表

| 方法与路径 | 鉴权 | 用途 |
| --- | --- | --- |
| POST /v1/auth/request | 无 | 提交 email，请求验证码 |
| POST /v1/auth/verify | 无 | 提交 email、code，领取账号 api_key |
| POST /v1/auth/rotate | 账号密钥 | 替换账号密钥，旧账号密钥立即失效 |
| POST /v1/tasks | 账号密钥 | 创建实验 |
| GET /v1/tasks | 账号密钥 | 列出自己的实验 |
| GET /v1/tasks/{id} | 账号密钥 | 查看实验条件、指标和通知状态 |
| DELETE /v1/tasks/{id} | 账号密钥 | 删除实验与待发通知，撤销实验密钥 |
| POST /v1/tasks/{id}/events | 对应实验密钥或账号密钥 | 上报事件 |
| GET /health | 无 | 查看服务健康状态 |

常见错误：

| HTTP 状态 | 含义与处理 |
| --- | --- |
| 400 | 参数、验证码或事件格式不正确 |
| 401 / 403 | 密钥无效、权限不足或请求来自不允许的网页来源 |
| 404 | 实验不存在，或不属于当前账号 |
| 409 | 实验已经结束，不能继续上报新事件 |
| 413 | 请求体超过 16 KiB |
| 429 | 达到限额，稍后再试 |
| 503 | 注册暂时关闭或服务暂不可用 |

API 不开放跨域浏览器调用。Python、命令行或自己的后端可以直接接入。

## 查看通知是否发出

网页中的实验详情，或 GET /v1/tasks/{id}，会显示通知记录：

| 状态 | 含义 |
| --- | --- |
| pending | 等待发送或等待重试 |
| sent | 邮件服务器已接受 |
| dead | 重试耗尽，未确认成功发送 |
| expired | 验证邮件已过期 |
| cancelled | 验证通知已被替换或取消 |

队列暂满时，触发内容仍会持久保存，任务详情中的 deferred_notifications 可查看尚待入队的提醒。达到邮件发送配额后，待发通知会延后。

sent 不代表邮件一定进入收件箱。没有收到时，请检查垃圾邮件目录，再查看通知状态。极少数情况下，发送后的重试可能产生重复邮件。

## 使用限制与隐私

公开服务当前默认限额：

- 每个账号同时运行最多 20 个实验，总计保留最多 200 个。
- 每个账号每天最多 30 次邮件发送尝试，全站每天最多 300 次；失败重试也计入次数。
- 每个邮箱每小时最多请求 3 次验证码，每个 IP 每小时最多 5 次。
- 成功或失败时各提醒一次；运行超时提醒一次；每条指标规则命中后提醒一次。
- 每次失联提醒一次，新心跳恢复后重新布防；两次失联提醒至少间隔 15 分钟。
- 已结束的实验和通知记录保留 30 天；仍在运行的实验请主动结束或删除。

提交的实验名称、说明和指标会用于保存状态及生成邮件，请勿包含密码、访问令牌或未经授权的个人信息。账号之间的实验隔离，实验密钥不能读取其他实验。

endnote 是提醒服务，**不会替你执行、终止、恢复或自动重启实验**。实验程序、网络或提醒服务发生故障时，通知可能延迟；提醒服务本身不可用时，要依赖独立的外部监控来及时发现。

## Codex 技能

把仓库中的 [skills/endnote](skills/endnote) 复制到自己的 ~/.codex/skills/endnote，即可使用 $endnote 为实验接入提醒。

技能使用同一套公开 API，不需要服务器登录权限。

## 自行部署与参与开发

希望自行托管服务，请阅读 [部署文档](deploy/README.md)。运行时需要 Python 3.10+ 和自己的 SMTP 配置。

开发检查：

~~~bash
python -m unittest discover -s tests -v
~~~

项目采用 [MIT 许可证](LICENSE)。
