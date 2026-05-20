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

# ---------- 国内三网：每线路 4 地区（上海、北京、广东、四川） ----------
DOMESTIC_SUBNETS = {
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
}

# ---------- 境外：按地区细分的真实家宽网段 ----------
OVERSEA_SUBNETS = {
    # 亚太地区
    "hk":       ["112.118.0.0/24", "118.140.0.0/24"],     # 中国香港 (PCCW + HKBN)
    "tw":       ["114.32.0.0/24"],                         # 中国台湾 (HiNet 中华电信)
    "jp":       ["153.156.0.0/24"],                         # 日本东京 (NTT OCN)
    "kr":       ["121.128.0.0/24"],                         # 韩国首尔 (KT)
    "sg":       ["116.14.0.0/24"],                          # 新加坡 (Singtel)
    "ph":       ["119.93.0.0/24"],                          # 菲律宾马尼拉 (PLDT)
    "au":       ["120.144.0.0/24"],                         # 澳大利亚悉尼 (Telstra)
    # 美洲地区
    "us":       ["71.212.0.0/24", "73.162.0.0/24", "104.175.0.0/24"],  # 美国 (Comcast 西雅图 + 硅谷 + Spectrum 洛杉矶)
    "ar":       ["181.88.0.0/24"],                          # 阿根廷 (Telecom Argentina)
    "br":       ["177.100.0.0/24"],                         # 巴西圣保罗 (Vivo)
    # 欧洲、中东与非洲 (EMEA)
    "de":       ["80.146.0.0/24"],                          # 德国法兰克福 (Deutsche Telekom)
    "gb":       ["86.132.0.0/24"],                          # 英国伦敦 (BT)
    "tr":       ["88.224.0.0/24"],                          # 土耳其 (Turk Telekom)
    "eg":       ["41.128.0.0/24"],                          # 埃及开罗 (TE Data)
    "za":       ["105.232.0.0/24"],                         # 南非 (Telkom SA)
}

# ---------- 三级境外路由分组定义 ----------
# 第一级：特定直连组（独立输出）
TIER1_KEYS = ["hk", "tw", "jp", "sg"]

# 第二级：大洲解析组（由多个地区均衡混合）
TIER2_GROUPS = {
    "asia":     ["hk", "tw", "jp", "kr", "sg", "ph"],      # 亚太
    "oceania":  ["au"],                                       # 大洋洲
    "na":       ["us"],                                       # 北美洲
    "sa":       ["ar", "br"],                                 # 南美洲
    "eu":       ["de", "gb", "tr"],                           # 欧洲
    "af":       ["eg", "za"],                                 # 非洲
}

# 第三级：境外全局兜底组（由第二级各组均衡混合）
TIER3_KEY = "oversea_default"
TIER3_SOURCES = ["asia", "oceania", "na", "sa", "eu", "af"]

# 线路名称映射
LINE_NAME_MAP = {
    "dianxin":          "电信",
    "liantong":         "联通",
    "yidong":           "移动",
    "default":          "全网默认",
    # 第一级
    "hk":               "🇭🇰 香港",
    "tw":               "🇹🇼 台湾",
    "jp":               "🇯🇵 日本",
    "sg":               "🇸🇬 新加坡",
    # 第二级
    "asia":             "🌏 亚太",
    "oceania":          "🌏 大洋洲",
    "na":               "🌎 北美",
    "sa":               "🌎 南美",
    "eu":               "🌍 欧洲",
    "af":               "🌍 非洲",
    # 第三级
    "oversea_default":  "🌐 境外兜底",
}

# 国内线路 key 集合（保留双栈）
DOMESTIC_LINE_KEYS = {"dianxin", "liantong", "yidong", "default"}

# 3. 华为云域名记录配置
# 国内线路支持 v4 + v6；境外线路仅支持 v4
DOMAINS_CONFIG = [
    {
        "domain_name": "1949101.xyz",
        "zone_id": "ff8080829a924b9b019df6faf543662f",
        "records": {
            # ---- 国内三网（保留 IPv6） ----
            "dianxin":          {"v4": "ff8080829e17ffac019e46bc1e663e2e", "v6": "ff8080829e0397b9019e46bbe06a236b"},
            "liantong":         {"v4": "ff8080829e180661019e46bca6540a53", "v6": "ff8080829e180661019e46bc6cc30a35"},
            "yidong":           {"v4": "ff8080829dbb31fd019e46bd3eaa5f22", "v6": "ff8080829dbb46c8019e46bcef760c30"},
            "default":          {"v4": "ff8080829db652b9019e46b63dab0293", "v6": "ff8080829dbb3f00019e46b5fc7e5a0c"},
            # ---- 第一级：特定直连（仅 IPv4） ----
            "hk":               {"v4": "ff8080829dbb3f00019e46baded45c4c"},
            "tw":               {"v4": "ff8080829db64170019e46baa02f3aab"},
            "jp":               {"v4": "ff8080829db652b9019e46ba535a0394"},
            "sg":               {"v4": "ff8080829e1802e4019e46ba04bd5ac1"},
            # ---- 第二级：大洲解析组（仅 IPv4） ----
            "asia":             {"v4": "ff8080829dbb31fd019e46b930625ddf"},
            "oceania":          {"v4": "ff8080829dbb31fd019e46b8e22e5dce"},
            "na":               {"v4": "ff8080829e180661019e46b8a307057d"},
            "sa":               {"v4": "ff8080829e180661019e46b85fcd0548"},
            "eu":               {"v4": "ff8080829db652b9019e46b8087102e7"},
            "af":               {"v4": "ff8080829e180661019e46b78f8c042b"},
            # ---- 第三级：境外全局兜底（仅 IPv4） ----
            "oversea_default":  {"v4": "ff8080829db652b9019e46b70c5202bd"},
        }
    }
]

# ================= 工具函数 =================


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


MAX_RECORDS_PER_SET = 50  # 华为云单条记录集上限


def round_robin_merge(ip_groups, max_total=MAX_RECORDS_PER_SET):
    """
    均衡轮询合并：从多个 IP 组中轮流抽取，确保各组比例均衡。
    - ip_groups: dict[str, list[str]]  {组名: [ip列表]}
    - max_total: 最大总数限制，默认 50（华为云上限）
    返回去重后的合并列表。
    """
    indices = {k: 0 for k in ip_groups}
    result = []
    seen = set()

    active = True
    while active:
        active = False
        for group_key, ips in ip_groups.items():
            idx = indices[group_key]
            while idx < len(ips) and ips[idx] in seen:
                idx += 1
            if idx < len(ips):
                ip = ips[idx]
                seen.add(ip)
                result.append(ip)
                indices[group_key] = idx + 1
                active = True
                if len(result) >= max_total:
                    return result

    return result


# ================= 核心逻辑 =================


def fetch_all_ips():
    """
    遍历所有线路和网段抓取 IP，返回聚合结果。
    - 国内三网：保留 IPv4 + IPv6 双栈，每地区最多 5 个
    - 境外所有分组：仅查询 IPv4，不查 IPv6
    - 全网默认：三网均衡组合
    """
    print(f"🔍 正在通过 Google DoH + ECS 获取 {TARGET_DOMAIN} 的真实边缘节点 IP...\n")

    # ---------- 阶段一：查询国内三网 ----------
    print("=" * 55)
    print("📌 阶段一：国内三网（IPv4 + IPv6 双栈）")
    print("=" * 55)

    line_results = {}
    domestic_region_names = ["上海", "北京", "广东", "四川"]

    for line, subnets in DOMESTIC_SUBNETS.items():
        line_name = LINE_NAME_MAP.get(line, line)
        print(f"  📡 正在查询 [{line_name}] ...")

        region_v4 = {}
        region_v6 = {}

        for idx, subnet in enumerate(subnets):
            region_name = domestic_region_names[idx] if idx < len(domestic_region_names) else f"地区{idx+1}"

            v4_res = resolve_with_ecs(TARGET_DOMAIN, subnet, 'A')
            if v4_res:
                region_v4[region_name] = v4_res

            v6_res = resolve_with_ecs(TARGET_DOMAIN, subnet, 'AAAA')
            if v6_res:
                region_v6[region_name] = v6_res

            time.sleep(0.2)

        # 每地区最多 5 个，按地区顺序合并
        v4_list = []
        v6_list = []
        for region in domestic_region_names:
            if region in region_v4:
                v4_list.extend(region_v4[region][:5])
            if region in region_v6:
                v6_list.extend(region_v6[region][:5])

        v4_list = list(dict.fromkeys(v4_list))
        v6_list = list(dict.fromkeys(v6_list))

        line_results[line] = {"v4": v4_list, "v6": v6_list}
        print(f"     ✅ [{line_name}] IPv4 {len(v4_list)} 个, IPv6 {len(v6_list)} 个（每地区最多5）")

    # ---------- 阶段二：查询境外各地区（仅 IPv4） ----------
    print(f"\n{'=' * 55}")
    print("📌 阶段二：境外各地区家宽网段（仅 IPv4）")
    print("=" * 55)

    region_ips = {}  # {地区key: [ipv4列表]}

    for region_key, subnets in OVERSEA_SUBNETS.items():
        region_name = LINE_NAME_MAP.get(region_key, region_key)
        print(f"  📡 正在查询 [{region_name}] ...")

        all_v4 = []
        for subnet in subnets:
            v4_res = resolve_with_ecs(TARGET_DOMAIN, subnet, 'A')
            all_v4.extend(v4_res)
            time.sleep(0.2)

        all_v4 = list(dict.fromkeys(all_v4))
        region_ips[region_key] = all_v4
        print(f"     ✅ [{region_name}] IPv4 {len(all_v4)} 个")

    # ---------- 阶段三：构建三级路由分组 ----------
    print(f"\n{'=' * 55}")
    print("📌 阶段三：构建三级境外路由分组（均衡轮询）")
    print("=" * 55)

    # --- 第一级：特定直连组（直接使用对应地区 IP，上限 50） ---
    print("\n  🏷️  第一级 — 特定直连组：")
    for key in TIER1_KEYS:
        ips = region_ips.get(key, [])[:MAX_RECORDS_PER_SET]
        line_results[key] = {"v4": ips, "v6": []}
        name = LINE_NAME_MAP.get(key, key)
        print(f"     {name}: IPv4 {len(ips)} 个")

    # --- 第二级：大洲解析组（从多个地区均衡轮询） ---
    print("\n  🏷️  第二级 — 大洲解析组：")
    tier2_ips = {}  # 保存第二级结果，供第三级使用
    for group_key, source_keys in TIER2_GROUPS.items():
        ip_groups = {}
        for sk in source_keys:
            if region_ips.get(sk):
                ip_groups[sk] = region_ips[sk]

        merged = round_robin_merge(ip_groups)
        tier2_ips[group_key] = merged
        line_results[group_key] = {"v4": merged, "v6": []}

        name = LINE_NAME_MAP.get(group_key, group_key)
        sources_desc = "+".join(source_keys)
        print(f"     {name} ({sources_desc}): IPv4 {len(merged)} 个")

    # --- 第三级：境外全局兜底组（从第二级各组均衡轮询） ---
    print("\n  🏷️  第三级 — 境外全局兜底组：")
    tier3_ip_groups = {}
    for gk in TIER3_SOURCES:
        if tier2_ips.get(gk):
            tier3_ip_groups[gk] = tier2_ips[gk]

    oversea_default = round_robin_merge(tier3_ip_groups)
    line_results[TIER3_KEY] = {"v4": oversea_default, "v6": []}
    name = LINE_NAME_MAP.get(TIER3_KEY, TIER3_KEY)
    print(f"     {name}: IPv4 {len(oversea_default)} 个")

    # ---------- 阶段四：构建全网默认（国内三网均衡） ----------
    print(f"\n{'=' * 55}")
    print("📌 阶段四：全网默认（国内三网均衡，IPv4 + IPv6）")
    print("=" * 55)

    default_v4 = build_balanced_default(line_results, "v4")
    default_v6 = build_balanced_default(line_results, "v6")
    line_results["default"] = {"v4": default_v4, "v6": default_v6}
    print(f"  ✅ 全网默认: IPv4 {len(default_v4)} 个, IPv6 {len(default_v6)} 个")

    # ---------- 汇总 ----------
    print(f"\n{'=' * 55}")
    print("📊 全部线路 IP 获取汇总")
    print("=" * 55)
    print(f"  {'线路':<14} {'IPv4':>6}  {'IPv6':>6}  {'备注'}")
    print(f"  {'─'*14} {'─'*6}  {'─'*6}  {'─'*20}")

    summary_order = (
        ["dianxin", "liantong", "yidong"]
        + TIER1_KEYS
        + list(TIER2_GROUPS.keys())
        + [TIER3_KEY, "default"]
    )
    for key in summary_order:
        if key not in line_results:
            continue
        name = LINE_NAME_MAP.get(key, key)
        v4c = len(line_results[key]["v4"])
        v6c = len(line_results[key]["v6"])
        note = ""
        if key in {"dianxin", "liantong", "yidong", "default"}:
            note = "双栈"
        elif key in OVERSEA_SUBNETS or key in TIER2_GROUPS or key == TIER3_KEY:
            note = "仅IPv4"
        print(f"  {name:<14} {v4c:>6}  {v6c:>6}  {note}")

    return line_results


def build_balanced_default(line_results, ip_version):
    """从国内三网 IP 中按地区轮询抽取，确保运营商和地区比例都相当"""
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

    base_count = 50 // active_networks
    result = []

    # 第一轮：每网按地区轮询取 base_count 个
    for net_name, ips in networks.items():
        taken = 0
        round_idx = 0
        while taken < base_count and round_idx < 5:
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


# ================= 华为云 DNS 更新 =================


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


# ================= 飞书通知 =================


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
    summary_order = (
        ["dianxin", "liantong", "yidong"]
        + TIER1_KEYS
        + list(TIER2_GROUPS.keys())
        + [TIER3_KEY, "default"]
    )
    for line in summary_order:
        if line in line_results:
            line_name = LINE_NAME_MAP.get(line, line)
            v4_count = len(line_results[line]["v4"])
            v6_count = len(line_results[line]["v6"])
            if line in DOMESTIC_LINE_KEYS:
                summary_lines.append(f"{line_name}: IPv4 {v4_count} 个, IPv6 {v6_count} 个")
            else:
                summary_lines.append(f"{line_name}: IPv4 {v4_count} 个")

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


# ================= 入口 =================


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

    # 构建更新顺序：国内（双栈） -> 境外（仅v4）
    update_order = (
        ["dianxin", "liantong", "yidong"]
        + TIER1_KEYS
        + list(TIER2_GROUPS.keys())
        + [TIER3_KEY, "default"]
    )

    for domain in DOMAINS_CONFIG:
        print(f"\n🚀 开始同步域名: {domain['domain_name']}")

        for line_key in update_order:
            if line_key not in line_results:
                continue

            ids = domain["records"].get(line_key, {})
            ips = line_results[line_key]

            # 更新 IPv4（所有线路都有）
            if ids.get("v4"):
                result = update_huawei_dns(client, domain, line_key, "v4", ips["v4"])
                all_results.append(result)

            # 更新 IPv6（仅国内线路）
            if line_key in DOMESTIC_LINE_KEYS and ids.get("v6"):
                result = update_huawei_dns(client, domain, line_key, "v6", ips["v6"])
                all_results.append(result)

        print("-" * 40)

    # 4. 发送飞书通知
    send_feishu_notification(line_results, all_results)


if __name__ == "__main__":
    main()
