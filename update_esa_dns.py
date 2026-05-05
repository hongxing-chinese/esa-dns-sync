import os
import time
import urllib.request
import json
from datetime import datetime
from dotenv import load_dotenv
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkdns.v2 import DnsClient, UpdateRecordSetRequest, UpdateRecordSetReq

# 加载 .env 环境变量
load_dotenv()
if not os.environ.get("HUAWEI_AK"):
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ================= 配置区域 =================

# 1. 从环境变量读取配置
AK = os.environ.get("HUAWEI_AK", "")
SK = os.environ.get("HUAWEI_SK", "")
HUAWEI_REGION = os.environ.get("HUAWEI_REGION", "ap-southeast-1")
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL_ESA", "")
TARGET_DOMAIN = os.environ.get("TARGET_DOMAIN", "www.aliyun.com")

# 2. 各地区各运营商的真实 IP 网段 (ECS Client Subnets)
# 每个线路包含 4 个地区，按顺序：上海、北京、广东、四川
SUBNETS = {
    "dianxin": [
        "101.224.0.0/24",  # 上海电信
        "106.120.0.0/24",  # 北京电信
        "113.116.0.0/24",  # 广东电信
        "118.112.0.0/24"   # 四川电信
    ],
    "liantong": [
        "112.64.0.0/24",   # 上海联通
        "123.112.0.0/24",  # 北京联通
        "120.80.0.0/24",   # 广东联通
        "119.6.0.0/24"     # 四川联通
    ],
    "yidong": [
        "223.166.0.0/24",  # 上海移动
        "221.130.0.0/24",  # 北京移动
        "120.196.0.0/24",  # 广东移动
        "117.136.64.0/24"  # 四川移动
    ],
    "oversea": [
        "8.8.8.0/24",      # Google
        "1.1.1.0/24"       # Cloudflare
    ]
}

# 地区名称映射（与 SUBNETS 顺序对应）
REGION_NAMES = ["上海", "北京", "广东", "四川"]

LINE_NAME_MAP = {
    "dianxin": "电信",
    "liantong": "联通",
    "yidong": "移动",
    "oversea": "海外",
    "default": "全网默认"
}

# 3. 华为云域名记录配置
# 每个线路支持 v4(IPv4 A记录) 和 v6(IPv6 AAAA记录)
DOMAINS_CONFIG = [
    {
        "domain_name": "1949101.xyz",
        "zone_id": "ff8080829a924b9b019df6faf543662f",
        "records": {
            "dianxin":  {"v4": "ff8080829db64170019df6fe14676380", "v6": "ff8080829dbb43ac019df6fdd868518a"},
            "liantong": {"v4": "ff8080829a924782019df6fee8bc661a", "v6": "ff8080829a9255d4019df6fe93ac010f"},
            "yidong":   {"v4": "ff8080829db64d69019df6ff90962674", "v6": "ff8080829a923d9f019df6ff492c34cd"},
            "oversea":  {"v4": "ff8080829a9255d4019df6fcc2f27f08", "v6": "ff8080829a92427d019df6fb944c24cf"},
            "default":  {"v4": "ff8080829a92427d019df6fd792c2564", "v6": "ff8080829dbb31fd019df6fd49e75cbe"}
        }
    }
]

# ================= 核心代码 =================

def resolve_with_ecs(domain, subnet, record_type='A'):
    """
    使用 Google DoH API，带上伪造的子网 IP 进行查询
    """
    qtype = "1" if record_type == "A" else "28"
    url = f"https://dns.google/resolve?name={domain}&type={qtype}&edns_client_subnet={subnet}"

    ips = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))

        if 'Answer' in data:
            for answer in data['Answer']:
                if str(answer['type']) == qtype:
                    ips.append(answer['data'])
    except Exception as e:
        print(f"    ⚠️  使用网段 {subnet} 查询 {record_type} 失败: {e}")

    return ips


def fetch_all_ips():
    """
    遍历所有线路和网段抓取 IP，返回聚合结果
    国内三网每条线路最多保留 20 个 IP（每地区 5 个），海外全部保留
    全网默认取三网均衡组合（运营商均衡 + 地区均衡）
    """
    print(f"🔍 正在通过 Google DoH + ECS 获取 {TARGET_DOMAIN} 的真实边缘节点 IP...\n")
    line_results = {}

    for line, subnets in SUBNETS.items():
        line_name = LINE_NAME_MAP.get(line, line)
        print(f"  📡 正在查询 [{line_name}] 线路...")

        # 按地区分别收集 IP（保持地区信息）
        region_v4 = {}  # {region_name: [ips]}
        region_v6 = {}

        for idx, subnet in enumerate(subnets):
            region_name = REGION_NAMES[idx] if idx < len(REGION_NAMES) else f"地区{idx+1}"

            v4_res = resolve_with_ecs(TARGET_DOMAIN, subnet, 'A')
            if v4_res:
                region_v4[region_name] = v4_res

            v6_res = resolve_with_ecs(TARGET_DOMAIN, subnet, 'AAAA')
            if v6_res:
                region_v6[region_name] = v6_res

            time.sleep(0.2)

        # 国内三网：每地区最多保留 5 个，然后合并
        if line in ["dianxin", "liantong", "yidong"]:
            v4_list = []
            v6_list = []
            for region in REGION_NAMES:
                if region in region_v4:
                    v4_list.extend(region_v4[region][:5])
                if region in region_v6:
                    v6_list.extend(region_v6[region][:5])
            limit_hint = " (每地区最多5)"
        else:
            # 海外：全部保留
            v4_list = []
            v6_list = []
            for region, ips in region_v4.items():
                v4_list.extend(ips)
            for region, ips in region_v6.items():
                v6_list.extend(ips)
            limit_hint = ""

        # 去重
        v4_list = list(dict.fromkeys(v4_list))
        v6_list = list(dict.fromkeys(v6_list))

        line_results[line] = {
            "v4": v4_list,
            "v6": v6_list
        }

        v4_count = len(v4_list)
        v6_count = len(v6_list)
        print(f"     ✅ [{line_name}] 合并去重后: IPv4 {v4_count} 个{limit_hint}, IPv6 {v6_count} 个{limit_hint if v6_count > 0 else ''}")

    # 全网默认：三网均衡组合（运营商均衡 + 地区均衡）
    def build_balanced_default(ip_version):
        """从三网 IP 中按地区轮询抽取，确保运营商和地区比例都相当"""
        dianxin_ips = line_results["dianxin"][ip_version]
        liantong_ips = line_results["liantong"][ip_version]
        yidong_ips = line_results["yidong"][ip_version]

        networks = {
            "电信": dianxin_ips,
            "联通": liantong_ips,
            "移动": yidong_ips
        }
        active_networks = sum(1 for ips in networks.values() if ips)

        if active_networks == 0:
            return []

        # 每网基础配额
        base_count = 50 // active_networks
        result = []

        # 第一轮：每网按地区轮询取 base_count 个
        # 单线路 IP 已按地区顺序排列（上海->北京->广东->四川），每地区最多5个
        for net_name, ips in networks.items():
            taken = 0
            round_idx = 0
            while taken < base_count and round_idx < 5:
                # 按地区轮询：上海(round_idx), 北京(round_idx), 广东(round_idx), 四川(round_idx)
                for region_offset in [0, 5, 10, 15]:
                    idx = region_offset + round_idx
                    if idx < len(ips) and taken < base_count:
                        result.append(ips[idx])
                        taken += 1
                round_idx += 1

        # 第二轮：剩余名额轮询补充
        remaining = 50 - len(result)
        idx = 0
        while remaining > 0 and idx < 100:
            added = False
            for net_name, ips in networks.items():
                already_taken = sum(1 for ip in result if ip in ips)
                if already_taken < len(ips):
                    result.append(ips[already_taken])
                    remaining -= 1
                    added = True
                    if remaining == 0:
                        break
            if not added:
                break
            idx += 1

        return list(dict.fromkeys(result))[:50]

    default_v4 = build_balanced_default("v4")
    default_v6 = build_balanced_default("v6")

    line_results["default"] = {
        "v4": default_v4,
        "v6": default_v6
    }
    print(f"     ✅ [全网默认] 三网均衡: IPv4 {len(default_v4)} 个, IPv6 {len(default_v6)} 个\n")

    return line_results


def update_huawei_dns(client, domain_config, line_key, ip_type, ip_list):
    """更新单条解析记录，返回结果字典"""
    domain_name = domain_config["domain_name"]
    zone_id = domain_config["zone_id"]
    recordset_id = domain_config["records"].get(line_key, {}).get(ip_type)
    line_name = LINE_NAME_MAP.get(line_key, line_key)
    ip_version = "IPv4" if ip_type == "v4" else "IPv6"

    result = {
        "domain": domain_name,
        "line": line_name,
        "ip_version": ip_version,
        "status": "跳过",
        "ips": ip_list,
        "error": ""
    }

    if not recordset_id or "RS_ID" in recordset_id or "你的" in recordset_id:
        print(f"  ⏭️  [{domain_name}] [{line_name}] {ip_version} 未配置 recordset_id，跳过。")
        result["error"] = "未配置 recordset_id"
        return result

    if not ip_list:
        print(f"  ⏭️  [{domain_name}] [{line_name}] {ip_version} IP 列表为空，跳过更新以免清空记录。")
        result["error"] = "IP 列表为空"
        return result

    try:
        request = UpdateRecordSetRequest()
        request.zone_id = zone_id
        request.recordset_id = recordset_id
        request.body = UpdateRecordSetReq(
            records=ip_list,
            ttl=300
        )
        client.update_record_set(request)
        result["status"] = "成功"
        print(f"  ✅ [{domain_name}] - [{line_name}] {ip_version} 更新成功! IP: {ip_list}")
    except Exception as e:
        result["status"] = "失败"
        result["error"] = str(e)
        print(f"  ❌ [{domain_name}] - [{line_name}] {ip_version} 更新失败! 错误: {e}")

    return result


def send_feishu_notification(line_results, all_results):
    """发送飞书机器人通知"""
    if not FEISHU_WEBHOOK_URL:
        print("\n未配置 FEISHU_WEBHOOK_URL_ESA，跳过飞书通知。")
        return

    success_count = sum(1 for r in all_results if r["status"] == "成功")
    skip_count = sum(1 for r in all_results if r["status"] == "跳过")
    fail_count = sum(1 for r in all_results if r["status"] == "失败")

    # 构建各线路 IP 获取情况摘要
    summary_lines = []
    for line in ["dianxin", "liantong", "yidong", "oversea", "default"]:
        if line in line_results:
            line_name = LINE_NAME_MAP.get(line, line)
            v4_count = len(line_results[line]["v4"])
            v6_count = len(line_results[line]["v6"])
            summary_lines.append(f"{line_name}: IPv4 {v4_count} 个, IPv6 {v6_count} 个")

    summary_text = "\n".join(summary_lines)

    # 构建更新详情
    detail_lines = []
    for r in all_results:
        if r["status"] == "成功":
            detail_lines.append(f"✅ {r['domain']} [{r['line']}] {r['ip_version']} -> {', '.join(r['ips'])}")
        elif r["status"] == "失败":
            detail_lines.append(f"❌ {r['domain']} [{r['line']}] {r['ip_version']} - {r['error']}")
        else:
            detail_lines.append(f"⏭️ {r['domain']} [{r['line']}] {r['ip_version']} - {r['error']}")

    detail_text = "\n".join(detail_lines) if detail_lines else "无记录"

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "ESA 边缘节点变更",
                    "content": [
                        [
                            {"tag": "text", "text": f"目标域名：{TARGET_DOMAIN}\n"}
                        ],
                        [
                            {"tag": "text", "text": f"IP 获取概况：\n{summary_text}\n"}
                        ],
                        [
                            {"tag": "text", "text": f"执行结果：成功 {success_count} 条，跳过 {skip_count} 条，失败 {fail_count} 条\n"}
                        ],
                        [
                            {"tag": "text", "text": "域名更新详情：\n"}
                        ],
                        [
                            {"tag": "text", "text": detail_text}
                        ]
                    ]
                }
            }
        }
    }

    max_retries = 5
    retry_delay = 120  # 2分钟

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                FEISHU_WEBHOOK_URL,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            response = urllib.request.urlopen(req, timeout=10)
            resp_data = json.loads(response.read().decode('utf-8'))

            if resp_data.get("code") == 0:
                print("\n📨 飞书通知发送成功")
                return
            elif resp_data.get("code") == 11232:
                print(f"\n⚠️ 飞书通知触发频率限制 (11232)，第 {attempt}/{max_retries} 次尝试")
                if attempt < max_retries:
                    print(f"   等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    print(f"   已达最大重试次数，放弃发送。")
                    return
            else:
                print(f"\n⚠️ 飞书通知发送失败: {resp_data}")
                return

        except Exception as e:
            print(f"\n⚠️ 飞书通知发送异常 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                print(f"   等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"   已达最大重试次数，放弃发送。")
                return


def main():
    if not AK or not SK:
        print("错误：未配置 HUAWEI_AK 或 HUAWEI_SK，请检查 .env 文件")
        return

    # 1. 通过 Google DoH + ECS 获取各线路 IP
    line_results = fetch_all_ips()

    # 2. 初始化华为云 SDK 客户端
    credentials = BasicCredentials(AK, SK)
    client = DnsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(DnsRegion.value_of(HUAWEI_REGION)) \
        .build()

    # 3. 遍历域名配置更新所有记录
    all_results = []
    for domain in DOMAINS_CONFIG:
        print(f"🚀 开始同步域名: {domain['domain_name']}")

        for line_key in ["dianxin", "liantong", "yidong", "oversea", "default"]:
            if line_key not in line_results:
                continue

            ids = domain["records"].get(line_key, {})
            ips = line_results[line_key]

            # 更新 IPv4
            if ids.get("v4"):
                result = update_huawei_dns(client, domain, line_key, "v4", ips["v4"])
                all_results.append(result)

            # 更新 IPv6
            if ids.get("v6"):
                result = update_huawei_dns(client, domain, line_key, "v6", ips["v6"])
                all_results.append(result)

        print("-" * 40)

    # 4. 发送飞书通知
    send_feishu_notification(line_results, all_results)


if __name__ == "__main__":
    main()
