---
name: endnote
description: 为长时间实验接入 endnote 邮箱提醒，配置完成、失败、心跳失联、运行超时和指标阈值通知。用户提到 endnote、实验结束发邮件或实验中断提醒时使用。
---

# endnote

end 的时候 note 一下。使用公共通知 API 为用户的实验配置邮件提醒。
默认端点 https://am.matterswarm.com/endnote，用户提供的 ENDNOTE_URL 优先。
服务部署在授权的 4090 workstation；此技能不授予任何 SSH 或服务器维护权限。

## 接入

使用本技能的 scripts/endnote.py（标准库，无安装依赖），或用户项目中的 endnote.client SDK。
优先复用 ENDNOTE_API_KEY 或用户自己的 ~/.config/endnote/credentials.json；
密钥仅通过 HTTPS 发送，不放进命令行参数、聊天、日志或 Git。
没有账号时让用户在服务网页验证自己的收件邮箱，或使用 request-code / verify。
向用户实际发送邮件前需有其对收件邮箱及通知任务的授权；不猜测邮箱。
服务只发往账号已验证邮箱，无法指定未经验证的第三方地址。

配置用户需要的触发条件。完成、失败和 300 秒无心跳为适合长实验的默认；
设置运行时长或指标规则时依据真实任务需求，不编造收敛阈值。
通知模板支持 $name $status $reason $message $metrics $time，纯文本。
每条指标规则命中后提醒一次，不执行用户提供的代码或表达式。

把已授权的实验命令包起来：
python scripts/endnote.py run --name "experiment" -- python train.py

包装器在其执行机器运行原实验，不把命令发送给服务器。
遵守用户已选定的计算机器；远程实验应把客户端放到该机器运行，不能默默在控制机启动。
在 Windows 上非交互子进程必须隐藏窗口；本脚本已设置 CREATE_NO_WINDOW。
如果用户已经运行了实验，不重启或重复启动它；在原代码或外部监控流程中接入事件 API。

指标提醒需要训练代码显式调用 metric，包装器不会解析日志。
自动心跳只说明上报进程活着；要检测无进展，应在关键步骤上报心跳或指标。
保留实验原退出码，不用通知异常掩盖实验异常，不发送可能包含秘密的完整 traceback。

## 验证

记录非秘密的任务 ID，检查自己的任务详情和通知状态。
结束事件应是 succeeded / failed；API 成功仅证明接收事件。
通知 pending 表示待发，sent 表示 SMTP 接受，dead 表示重试耗尽。
重试事件必须保持相同 event_id，避免重复通知；不无界重试。
不要声称 sent 就代表用户已收到邮件，或声称提醒接口能避免实验中断。

## 边界

服务和实验若都在 4090，整机掉线时它自身不能及时发信。独立外部监控另行配置。
不要为了这个技能修改 SSH、DNS、防火墙、别的服务或获取服务器凭据。
发布和服务器维护依照该项目 AGENTS.md 以及另行授权的 yun 工作流。
