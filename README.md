# ESA DNS Sync

通过智能分流 DoH (DNS-over-HTTPS) + ECS (EDNS Client Subnet) 技术，伪装成不同地区运营商的真实用户家宽网段，向目标 CDN 域名查询最优边缘节点 IP，并自动更新到华为云 DNS 解析的 Python 脚本。

## 原理简介

阿里云等 CDN 会根据用户所在网段返回最近的边缘节点。本项目利用公共 DNS 的 ECS 扩展协议，在查询请求中附加伪造的子网信息，从而获取对应线路的真实边缘节点 IP，再将其写入华为云 DNS 的分线路解析记录。国内三网网段优先走腾讯云 `doh.pub`，境外网段优先走 Google `dns.google`；任一 DoH 不可达、握手超时或未返回目标记录时，会自动 fallback 到备用 DoH（腾讯云 `doh.pub` / 阿里云 `dns.alidns.com` / Google `dns.google`）。

### 线路层级

线路从大到小分为四层：**全网默认** 是最大范畴；下一层是 **境外默认** 和 **三网默认**；再下一层是 **境外大洲** 和 **境内大区**；最后一层是 **境外指定地域** 和 **境内大区下的三运营商**。大洲、默认和全网默认层会采用 **均衡轮询** 控制来源比例，所有记录集严格限制在 **50 条** 以内。

| 层级 | 境外线路 | 境内线路 |
|------|----------|----------|
| 全网默认 | - | `default` |
| 默认层 | `oversea_default` | `dianxin` / `yidong` / `liantong` |
| 区域层 | `asia` / `oceania` / `na` / `sa` / `eu` / `af` | 华北 / 东北 / 西北 / 华中 / 华东 / 华南 / 西南 |
| 末级线路 | `hk` / `tw` / `jp` / `sg` | 华北-电信 / 华北-移动 / 华北-联通 等 |

### IPv4 / IPv6 策略

| 分组 | IPv4 | IPv6 | 说明 |
|------|:----:|:----:|------|
| 国内三网默认 + 7 大区三网 | ✅ | ✅ | 三网默认拆成电信/移动/联通 3 条；大区拆成 7×3 条，每网段最多 3 个 IP |
| 全网默认 | ✅ | ✅ | 国内大区均衡双栈，每大区最多 2 个 IP |
| 境外默认/大洲/指定地域 | ✅ | ❌ | 阿里云 ESA 境外节点不提供 IPv6 |

## 支持的线路

| 层级 | 线路 Key | 名称 | 来源 |
|------|----------|------|------|
| 全网默认 | `default` | 全网默认 | 7 大区各取前 2 个，最多 16 个 |
| 默认层 | `oversea_default` | 境外默认 | 全部境外大洲均衡混合 |
| 默认层 | `dianxin` / `yidong` / `liantong` | 三网默认 | 北上广川每运营商每地区前 2 个 |
| 大洲层 | `asia` / `oceania` / `na` / `sa` / `eu` / `af` | 境外大洲 | 多个境外地域均衡 |
| 大区层 | 华北/东北/西北/华中/华东/华南/西南 | 境内大区 | 大区本身不单独配置默认记录 |
| 指定地域层 | `hk` / `tw` / `jp` / `sg` | 境外指定地域 | 香港/台湾/日本/新加坡 |
| 运营商层 | `huabei_dianxin` / `huabei_yidong` / `huabei_liantong` 等 | 境内大区运营商 | 每个大区下电信/移动/联通各一条 |

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
            # ---- 三网默认（IPv4 + IPv6） ----
            "dianxin":          {"v4": "三网默认电信IPv4_ID", "v6": "三网默认电信IPv6_ID"},
            "yidong":           {"v4": "三网默认移动IPv4_ID", "v6": "三网默认移动IPv6_ID"},
            "liantong":         {"v4": "三网默认联通IPv4_ID", "v6": "三网默认联通IPv6_ID"},
            "default":          {"v4": "默认IPv4_ID", "v6": "默认IPv6_ID"},
            # ---- 国内 7 大区 × 三网（IPv4 + IPv6） ----
            "huabei_dianxin":   {"v4": "华北电信IPv4_ID", "v6": "华北电信IPv6_ID"},
            "huabei_yidong":    {"v4": "华北移动IPv4_ID", "v6": "华北移动IPv6_ID"},
            "huabei_liantong":  {"v4": "华北联通IPv4_ID", "v6": "华北联通IPv6_ID"},
            "dongbei_dianxin":  {"v4": "东北电信IPv4_ID", "v6": "东北电信IPv6_ID"},
            "dongbei_yidong":   {"v4": "东北移动IPv4_ID", "v6": "东北移动IPv6_ID"},
            "dongbei_liantong": {"v4": "东北联通IPv4_ID", "v6": "东北联通IPv6_ID"},
            "xibei_dianxin":    {"v4": "西北电信IPv4_ID", "v6": "西北电信IPv6_ID"},
            "xibei_yidong":     {"v4": "西北移动IPv4_ID", "v6": "西北移动IPv6_ID"},
            "xibei_liantong":   {"v4": "西北联通IPv4_ID", "v6": "西北联通IPv6_ID"},
            "huazhong_dianxin": {"v4": "华中电信IPv4_ID", "v6": "华中电信IPv6_ID"},
            "huazhong_yidong":  {"v4": "华中移动IPv4_ID", "v6": "华中移动IPv6_ID"},
            "huazhong_liantong": {"v4": "华中联通IPv4_ID", "v6": "华中联通IPv6_ID"},
            "huadong_dianxin":  {"v4": "华东电信IPv4_ID", "v6": "华东电信IPv6_ID"},
            "huadong_yidong":   {"v4": "华东移动IPv4_ID", "v6": "华东移动IPv6_ID"},
            "huadong_liantong": {"v4": "华东联通IPv4_ID", "v6": "华东联通IPv6_ID"},
            "huanan_dianxin":   {"v4": "华南电信IPv4_ID", "v6": "华南电信IPv6_ID"},
            "huanan_yidong":    {"v4": "华南移动IPv4_ID", "v6": "华南移动IPv6_ID"},
            "huanan_liantong":  {"v4": "华南联通IPv4_ID", "v6": "华南联通IPv6_ID"},
            "xinan_dianxin":    {"v4": "西南电信IPv4_ID", "v6": "西南电信IPv6_ID"},
            "xinan_yidong":     {"v4": "西南移动IPv4_ID", "v6": "西南移动IPv6_ID"},
            "xinan_liantong":   {"v4": "西南联通IPv4_ID", "v6": "西南联通IPv6_ID"},
            # ---- 境外指定地域（仅 IPv4） ----
            "hk":               {"v4": "香港_ID"},
            "tw":               {"v4": "台湾_ID"},
            "jp":               {"v4": "日本_ID"},
            "sg":               {"v4": "新加坡_ID"},
            # ---- 境外大洲（仅 IPv4） ----
            "asia":             {"v4": "亚太_ID"},
            "oceania":          {"v4": "大洋洲_ID"},
            "na":               {"v4": "北美_ID"},
            "sa":               {"v4": "南美_ID"},
            "eu":               {"v4": "欧洲_ID"},
            "af":               {"v4": "非洲_ID"},
            # ---- 境外默认（仅 IPv4） ----
            "oversea_default":  {"v4": "境外默认_ID"},
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
🔍 正在通过智能分流 DoH + ECS 获取 www.aliyun.com 的真实边缘节点 IP...

=======================================================
📌 阶段一：国内三网大区（IPv4 + IPv6 双栈）
=======================================================
  📡 正在查询 [华北] ...
     ✅ [华北-电信] IPv4 3 个, IPv6 3 个
     ✅ [华北-移动] IPv4 3 个, IPv6 3 个
     ✅ [华北-联通] IPv4 3 个, IPv6 3 个
  📡 正在查询 [东北] ...
     ✅ [东北-电信] IPv4 3 个, IPv6 3 个
  ...
  ✅ [三网默认-电信] IPv4 8 个, IPv6 8 个（北上广川每地区最多2）
  ✅ [三网默认-移动] IPv4 8 个, IPv6 8 个（北上广川每地区最多2）
  ✅ [三网默认-联通] IPv4 8 个, IPv6 8 个（北上广川每地区最多2）

=======================================================
📌 阶段二：境外各地区家宽网段（仅 IPv4）
=======================================================
  📡 正在查询 [🇭🇰 香港] ...
     ✅ [🇭🇰 香港] IPv4 9 个
  📡 正在查询 [🇺🇸 美国] ...
     ✅ [🇺🇸 美国] IPv4 28 个
  ...

=======================================================
📌 阶段三：构建境外分层线路（均衡轮询）
=======================================================

  🏷️  境外指定地域：
     🇭🇰 香港: IPv4 9 个
     🇹🇼 台湾: IPv4 3 个
     🇯🇵 日本: IPv4 3 个
     🇸🇬 新加坡: IPv4 6 个

  🏷️  境外大洲：
     🌏 亚太 (hk+tw+jp+kr+sg+ph): IPv4 26 个
     🌏 大洋洲 (au): IPv4 16 个
     🌎 北美 (us): IPv4 28 个
     🌎 南美 (ar+br): IPv4 4 个
     🌍 欧洲 (de+gb+tr): IPv4 7 个
     🌍 非洲 (eg+za): IPv4 5 个

  🏷️  境外默认：
     🌐 境外默认: IPv4 50 个

=======================================================
📌 阶段四：全网默认（国内大区均衡，IPv4 + IPv6）
=======================================================
  ✅ 全网默认: IPv4 14 个, IPv6 14 个

=======================================================
📊 全部线路 IP 获取汇总
=======================================================
  线路               IPv4    IPv6  备注
  ────────────── ──────  ──────  ────────────────────
  三网默认-电信             8       8  双栈
  三网默认-移动             8       8  双栈
  三网默认-联通             8       8  双栈
  华北-电信               3       3  双栈
  华北-移动               3       3  双栈
  华北-联通               3       3  双栈
  ...
  🇭🇰 香港               9       0  仅IPv4
  🇹🇼 台湾               3       0  仅IPv4
  🇯🇵 日本               3       0  仅IPv4
  🇸🇬 新加坡              6       0  仅IPv4
  🌏 亚太               26       0  仅IPv4
  🌏 大洋洲              16       0  仅IPv4
  🌎 北美               28       0  仅IPv4
  🌎 南美                4       0  仅IPv4
  🌍 欧洲                7       0  仅IPv4
  🌍 非洲                5       0  仅IPv4
  🌐 境外默认             50       0  仅IPv4
  全网默认               14      14  双栈

🚀 开始同步域名: example.com
  ✅ [example.com] - [华北-联通] IPv4 更新成功! IP: ['202.106.x.x', ...]
  ...
📨 飞书通知发送成功
```

## 部署到云服务器（Linux）

### 1. 上传项目

将项目上传到 `/home/esa-dns-sync` 目录：

```bash
cd /home
git clone https://github.com/hongxing-chinese/esa-dns-sync
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

脚本使用真实家宽网段模拟用户请求，覆盖 15 个境外地区 + 国内三网默认和 7 个大区。

### 国内三网默认 + 7 大区

每个大区按电信、移动、联通拆成三条独立记录，IPv4/IPv6 每条记录最多保留 3 个 IP。三网默认使用 `dianxin`、`yidong`、`liantong` 三条记录，分别从北京、上海、广东、四川每地区取前 2 个 IP，单运营商最多 8 个；`default` 从华北、东北、西北、华中、华东、华南、西南各取前 2 个 IP，最多 16 个。

| 分组 | 地区 | 电信 | 移动 | 联通 |
|------|------|------|------|------|
| `huabei` | 北京 | 219.141.136.0/24 | 221.130.33.0/24 | 202.106.0.0/24 |
| `dongbei` | 辽宁 | 219.148.204.0/24 | 211.137.32.0/24 | 202.96.64.0/24 |
| `xibei` | 陕西 | 202.100.4.0/24 | 211.137.130.0/24 | 221.11.1.0/24 |
| `huazhong` | 湖北 | 202.103.24.0/24 | 211.137.64.0/24 | 218.106.127.0/24 |
| `huadong` | 上海 | 202.96.209.0/24 | 211.136.112.0/24 | 210.22.70.0/24 |
| `huanan` | 广东 | 202.96.128.0/24 | 211.136.192.0/24 | 210.21.1.0/24 |
| `xinan` | 四川 | 118.112.0.0/24 | 117.136.64.0/24 | 119.6.0.0/24 |

### 境外家宽网段（15 个地区）

| 地区 | Key | 网段 | ISP |
|------|-----|------|-----|
| 中国香港 | `hk` | 112.118.0.0/24, 118.140.0.0/24 | PCCW 电讯盈科, HKBN 香港宽频 |
| 中国台湾 | `tw` | 114.32.0.0/24 | HiNet 中华电信 |
| 日本 | `jp` | 153.156.0.0/24 | NTT OCN |
| 韩国首尔 | `kr` | 121.128.0.0/24 | KT 韩国电信 |
| 新加坡 | `sg` | 116.14.0.0/24 | Singtel |
| 菲律宾 | `ph` | 119.93.0.0/24 | PLDT |
| 澳大利亚 | `au` | 120.144.0.0/24 | Telstra |
| 美国 | `us` | 71.212.0.0/24, 73.162.0.0/24, 104.175.0.0/24 | Comcast (西雅图+硅谷), Spectrum (洛杉矶) |
| 阿根廷 | `ar` | 181.88.0.0/24 | Telecom Argentina |
| 巴西 | `br` | 177.100.0.0/24 | Vivo / Telefonica |
| 德国 | `de` | 80.146.0.0/24 | Deutsche Telekom |
| 英国 | `gb` | 86.132.0.0/24 | BT 英国电信 |
| 土耳其 | `tr` | 88.224.0.0/24 | Turk Telekom |
| 埃及 | `eg` | 41.128.0.0/24 | TE Data |
| 南非 | `za` | 105.232.0.0/24 | Telkom SA |

如需增加或修改网段，编辑 `update_esa_dns.py` 中的 `OVERSEA_SUBNETS` 或 `DOMESTIC_SUBNETS` 字典即可。

## 注意事项

- `.env` 文件包含敏感信息，**切勿提交到 Git**
- 项目已配置 `.gitignore`，默认忽略 `.env` 和日志文件
- 若某线路未查询到 IP（极少见），脚本会自动跳过该线路，不会清空现有记录
- 每条记录集严格限制最多 **50 个 IP**（华为云上限），超出时自动截断；国内大区每条运营商记录最多 3 个，三网默认每条运营商记录最多 8 个，`default` 最多 16 个
- 境外分组仅使用 IPv4，因阿里云 ESA 境外节点不提供 IPv6
- DoH 公共接口有请求频率限制，脚本已内置 0.2s 查询间隔；国内网段优先使用腾讯云 `doh.pub`，境外网段优先使用 Google `dns.google`，失败时自动切换备用 DoH
- 如需停止定时任务，执行 `crontab -e` 删除对应行即可
