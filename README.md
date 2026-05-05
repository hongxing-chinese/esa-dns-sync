# ESA DNS Sync

通过 Google DoH (DNS-over-HTTPS) + ECS (EDNS Client Subnet) 技术，伪装成不同地区运营商的真实用户网段，向目标 CDN 域名查询最优边缘节点 IP，并自动更新到华为云 DNS 解析的 Python 脚本。

## 原理简介

阿里云等 CDN 会根据用户所在网段返回最近的边缘节点。本项目利用 Google 公共 DNS 的 ECS 扩展协议，在查询请求中附加伪造的子网信息（如「北京联通 123.112.0.0/24」），从而获取对应线路的真实边缘节点 IP，再将其写入华为云 DNS 的分线路解析记录。

支持的线路：
- 电信（IPv4 + IPv6）
- 联通（IPv4 + IPv6）
- 移动（IPv4 + IPv6）
- 海外（IPv4 + IPv6）
- 全网默认（IPv4 + IPv6，三网均衡组合）

## 项目结构

```
.
├── update_esa_dns.py   # 主脚本
├── .env                # 环境变量配置文件（需自行创建）
├── .env.example        # 环境变量模板
├── requirements.txt    # Python 依赖
└── README.md           # 本文件
```

## 快速开始

### 1. 环境准备

```bash
cd /home/esa-dns-sync
source venv/bin/activate
```

如果尚未安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
nano .env
```

编辑 `.env` 文件：

```env
# 华为云 API 密钥
HUAWEI_AK=你的AccessKey
HUAWEI_SK=你的SecretKey

# DNS 服务区域
HUAWEI_REGION=ap-southeast-1

# 飞书自定义机器人 Webhook 地址
FEISHU_WEBHOOK_URL_ESA=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxx

# 要查询的目标 CDN 域名
TARGET_DOMAIN=www.aliyun.com
```

#### 获取华为云密钥

1. 登录 [华为云控制台](https://console.huaweicloud.com/)
2. 右上角头像 -> 我的凭证 -> 访问密钥 -> 创建
3. 保存 AK 和 SK

#### 获取飞书 Webhook 地址

1. 打开飞书电脑端，进入目标群聊
2. 群设置 -> 添加机器人 -> 自定义机器人
3. 安全设置：**只勾选「自定义关键词」**，输入关键词：`ESA 边缘节点变更`
4. 复制 Webhook 地址填入 `.env` 的 `FEISHU_WEBHOOK_URL_ESA`

### 3. 配置域名解析记录

在 `update_esa_dns.py` 的 `DOMAINS_CONFIG` 中配置你的域名信息。每个线路需要提前在华为云 DNS 控制台创建好 A/AAAA 记录，然后通过浏览器 F12 抓包获取 `zone_id` 和 `recordset_id`。

```python
DOMAINS_CONFIG = [
    {
        "domain_name": "你的域名.com",
        "zone_id": "ff8080xxxxxxxxxxxxxxxx",
        "records": {
            "dianxin":  {"v4": "电信IPv4_recordset_id", "v6": "电信IPv6_recordset_id"},
            "liantong": {"v4": "联通IPv4_recordset_id", "v6": "联通IPv6_recordset_id"},
            "yidong":   {"v4": "移动IPv4_recordset_id", "v6": "移动IPv6_recordset_id"},
            "oversea":  {"v4": "海外IPv4_recordset_id", "v6": "海外IPv6_recordset_id"},
            "default":  {"v4": "默认IPv4_recordset_id", "v6": "默认IPv6_recordset_id"}
        }
    }
]
```

### 4. 测试运行

```bash
cd /home/esa-dns-sync
source ./venv/bin/activate
python update_esa_dns.py
```

正常输出示例：

```
🔍 正在通过 Google DoH + ECS 获取 www.aliyun.com 的真实边缘节点 IP...

  📡 正在查询 [电信] 线路...
     ✅ [电信] 合并去重后: IPv4 3 个 (每地区最多5), IPv6 2 个 (每地区最多5)
  📡 正在查询 [联通] 线路...
     ✅ [联通] 合并去重后: IPv4 4 个 (每地区最多5), IPv6 2 个 (每地区最多5)
  ...
     ✅ [全网默认] 三网均衡: IPv4 8 个, IPv6 5 个

🚀 开始同步域名: example.com
  ✅ [example.com] - [电信] IPv4 更新成功! IP: ['1.2.3.4', ...]
  ✅ [example.com] - [电信] IPv6 更新成功! IP: ['2400:3200::1', ...]
  ...
📨 飞书通知发送成功
```

## 部署到云服务器（Linux）

### 1. 上传项目

将项目上传到 `/home/esa-dns-sync` 目录：

```bash
cd /home
git clone <你的仓库地址> esa-dns-sync
cd esa-dns-sync
```

### 2. 在服务器上创建 .env

```bash
cd /home/esa-dns-sync
cp .env.example .env
nano .env
# 填入你的 AK、SK、Webhook 地址
```

### 3. 添加定时任务（每天 00:45 执行）

```bash
crontab -e
```

添加以下行：

```cron
45 0 * * * cd /home/esa-dns-sync && /home/esa-dns-sync/venv/bin/python /home/esa-dns-sync/update_esa_dns.py >> /home/esa-dns-sync/run.log 2>&1
```

查看执行日志：

```bash
tail -f /home/esa-dns-sync/run.log
```

## 查询网段配置

默认配置的网段覆盖了中国主要地区三大运营商及海外节点：

| 线路 | 网段示例 | 归属地 |
|------|---------|--------|
| 电信 | 101.224.0.0/24 | 上海 |
| 电信 | 106.120.0.0/24 | 北京 |
| 联通 | 112.64.0.0/24 | 上海 |
| 联通 | 123.112.0.0/24 | 北京 |
| 移动 | 223.166.0.0/24 | 上海 |
| 移动 | 221.130.0.0/24 | 北京 |
| 海外 | 8.8.8.0/24 | 美国 Google |
| 海外 | 1.1.1.0/24 | 美国 Cloudflare |

如需增加或修改网段，编辑 `update_esa_dns.py` 中的 `SUBNETS` 字典即可。

## 注意事项

- `.env` 文件包含敏感信息，**切勿提交到 Git**
- 项目已配置 `.gitignore`，默认忽略 `.env` 和日志文件
- 若某线路未查询到 IP（极少见），脚本会自动跳过该线路，不会清空现有记录
- Google DoH 有请求频率限制，脚本已内置 0.2s 查询间隔
- 如需停止定时任务，执行 `crontab -e` 删除对应行即可
