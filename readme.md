# Task Notifier

在远程服务器上执行命令，任务完成后发送邮件通知。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填入 SMTP 凭证
cp config.yaml.example config.yaml
# vim config.yaml

# 运行任务
python task_notifier.py -o "python main.py" -n "任务名"

# 后台运行（不怕 SSH 断开）
python task_notifier.py --daemon -o "python main.py" -n "任务名"
```

## 配置

编辑 `config.yaml`，填入 SMTP 信息、收件邮箱等。

## 使用示例

```bash
# 执行命令
notifier -o "bash train.sh" -n "模型训练"

# 执行脚本
notifier --script train.sh -n "训练"

# 指定收件人
notifier -o "make all" -n "编译" --to "admin@example.com"

# 附加文件
notifier -o "python report.py" -n "报表" --attach "output/*.csv"
```

## Docker

```bash
docker build -t task-notifier .
docker run --rm \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/logs:/app/logs \
  task-notifier -o "python main.py" -n "任务"
```
