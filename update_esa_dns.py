import os
import time
import urllib.request
import urllib.parse
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

# ---------- 国内三网：三网默认 + 7 大区（每网段最多取 3 个 IP） ----------
DOMESTIC_CARRIERS = [
    ("dianxin", "电信"),
    ("yidong", "移动"),
    ("liantong", "联通"),
]
CARRIER_KEY_BY_NAME = {name: key for key, name in DOMESTIC_CARRIERS}
DOMESTIC_CARRIER_ASN_NUMBERS = {
    "dianxin": {4134, 4812, 4847, 38283},
    "yidong": {9808, 24400, 56040, 56044, 56048},
    "liantong": {4808, 4837, 17621, 17622},
}
DOMESTIC_REGION_PREFERRED_ASN_NUMBERS = {
    # IP66 不提供省份字段，只能把明确带地区属性的 ASN 作为优先项。
    # 未命中这里时，只要仍满足 CN + 运营商，就作为降权候选保留。
    "huabei": {
        "liantong": {4808},
    },
    "huadong": {
        "dianxin": {4812},
        "yidong": {24400},
        "liantong": {17621},
    },
    "huanan": {
        "liantong": {17622},
    },
    "xinan": {
        "dianxin": {38283},
    },
}
DOMESTIC_DEFAULT_LINE_KEYS = [key for key, _ in DOMESTIC_CARRIERS]
DOMESTIC_ROUTE_REGION_KEYS = [
    "huabei",
    "dongbei",
    "xibei",
    "huazhong",
    "huadong",
    "huanan",
    "xinan",
]
DOMESTIC_REGION_LINE_KEYS = [
    f"{region_key}_{carrier_key}"
    for region_key in DOMESTIC_ROUTE_REGION_KEYS
    for carrier_key, _ in DOMESTIC_CARRIERS
]
DOMESTIC_DEFAULT_SOURCE_AREAS = ["北京", "上海", "广东", "四川"]
DOMESTIC_MAX_IPS_PER_SUBNET = 3
DOMESTIC_DEFAULT_MAX_IPS_PER_AREA = 2
GLOBAL_DEFAULT_MAX_IPS_PER_REGION = 2
GLOBAL_DEFAULT_MAX_IPS = 16
IP66_DB_URL = "https://downloads.ip66.dev/db/ip66.mmdb"
IP66_DB_PATH = os.path.join(os.path.dirname(__file__), "ip66.mmdb")
IP66_MAX_QUERY_ROUNDS = int(os.environ.get("IP66_MAX_QUERY_ROUNDS", "5"))
ENABLE_IP66_VALIDATION = os.environ.get("ENABLE_IP66_VALIDATION", "true").lower() not in {"0", "false", "no"}

DOMESTIC_SUBNETS = {
    "huabei": [
        {"area": "北京", "carrier": "电信", "subnet": "219.141.136.0/24"},
        {"area": "北京", "carrier": "移动", "subnet": "221.130.33.0/24"},
        {"area": "北京", "carrier": "联通", "subnet": "202.106.0.0/24"},
    ],
    "dongbei": [
        {"area": "辽宁", "carrier": "电信", "subnet": "219.148.204.0/24"},
        {"area": "辽宁", "carrier": "移动", "subnet": "211.137.32.0/24"},
        {"area": "辽宁", "carrier": "联通", "subnet": "202.96.64.0/24"},
    ],
    "xibei": [
        {"area": "陕西", "carrier": "电信", "subnet": "202.100.4.0/24"},
        {"area": "陕西", "carrier": "移动", "subnet": "211.137.130.0/24"},
        {"area": "陕西", "carrier": "联通", "subnet": "221.11.1.0/24"},
    ],
    "huazhong": [
        {"area": "湖北", "carrier": "电信", "subnet": "202.103.24.0/24"},
        {"area": "湖北", "carrier": "移动", "subnet": "211.137.64.0/24"},
        {"area": "湖北", "carrier": "联通", "subnet": "218.106.127.0/24"},
    ],
    "huadong": [
        {"area": "上海", "carrier": "电信", "subnet": "202.96.209.0/24"},
        {"area": "上海", "carrier": "移动", "subnet": "211.136.112.0/24"},
        {"area": "上海", "carrier": "联通", "subnet": "210.22.70.0/24"},
    ],
    "huanan": [
        {"area": "广东", "carrier": "电信", "subnet": "202.96.128.0/24"},
        {"area": "广东", "carrier": "移动", "subnet": "211.136.192.0/24"},
        {"area": "广东", "carrier": "联通", "subnet": "210.21.1.0/24"},
    ],
    "xinan": [
        {"area": "四川", "carrier": "电信", "subnet": "118.112.0.0/24"},
        {"area": "四川", "carrier": "移动", "subnet": "117.136.64.0/24"},
        {"area": "四川", "carrier": "联通", "subnet": "119.6.0.0/24"},
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

# ---------- 境外线路层级定义 ----------
# 境外指定地域：独立输出
TIER1_KEYS = ["hk", "tw", "jp", "sg"]

# 境外大洲：由多个指定地域均衡混合
TIER2_GROUPS = {
    "asia":     ["hk", "tw", "jp", "kr", "sg", "ph"],      # 亚太
    "oceania":  ["au"],                                       # 大洋洲
    "na":       ["us"],                                       # 北美洲
    "sa":       ["ar", "br"],                                 # 南美洲
    "eu":       ["de", "gb", "tr"],                           # 欧洲
    "af":       ["eg", "za"],                                 # 非洲
}

# 境外默认：由境外大洲均衡混合
TIER3_KEY = "oversea_default"
TIER3_SOURCES = ["asia", "oceania", "na", "sa", "eu", "af"]

# 线路名称映射
LINE_NAME_MAP = {
    "dianxin":          "三网默认-电信",
    "yidong":           "三网默认-移动",
    "liantong":         "三网默认-联通",
    "huabei":           "华北",
    "dongbei":          "东北",
    "xibei":            "西北",
    "huazhong":         "华中",
    "huadong":          "华东",
    "huanan":           "华南",
    "xinan":            "西南",
    "default":          "全网默认",
    # 境外指定地域
    "hk":               "🇭🇰 香港",
    "tw":               "🇹🇼 台湾",
    "jp":               "🇯🇵 日本",
    "sg":               "🇸🇬 新加坡",
    # 境外大洲
    "asia":             "🌏 亚太",
    "oceania":          "🌏 大洋洲",
    "na":               "🌎 北美",
    "sa":               "🌎 南美",
    "eu":               "🌍 欧洲",
    "af":               "🌍 非洲",
    # 境外默认
    "oversea_default":  "🌐 境外默认",
}
for region_key in DOMESTIC_ROUTE_REGION_KEYS:
    for carrier_key, carrier_name in DOMESTIC_CARRIERS:
        LINE_NAME_MAP[f"{region_key}_{carrier_key}"] = f"{LINE_NAME_MAP[region_key]}-{carrier_name}"

# 国内线路 key 集合（保留双栈）
DOMESTIC_LINE_KEYS = set(DOMESTIC_DEFAULT_LINE_KEYS + DOMESTIC_REGION_LINE_KEYS + ["default"])

# 3. 华为云域名记录配置
# 国内线路支持 v4 + v6；境外线路仅支持 v4
DOMAINS_CONFIG = [
    {
        "domain_name": "1949101.xyz",
        "zone_id": "ff8080829a924b9b019df6faf543662f",
        "records": {
            # ---- 三网默认（支持 IPv6） ----
            "dianxin":          {"v4": "ff8080829e0397b9019edc2b797c7e97", "v6": "ff8080829e0397b9019edc2b79407e95"},
            "liantong":         {"v4": "ff8080829e0397b9019edc2b81387ebf", "v6": "ff8080829e0397b9019edc2b80f97ebd"},
            "yidong":           {"v4": "ff8080829e0397b9019edc2b8a037ee9", "v6": "ff8080829e0397b9019edc2b89c37ee7"},
            "default":          {"v4": "ff8080829db652b9019e46b63dab0293", "v6": "ff8080829dbb3f00019e46b5fc7e5a0c"},
            # ---- 国内 7 大区 × 三网（支持 IPv6） ----
            "huabei_dianxin":   {"v4": "ff8080829e0397b9019edc2b80bf7ebb", "v6": "ff8080829e0397b9019edc2b80597eb9"},
            "huabei_yidong":    {"v4": "ff8080829e0397b9019edc2b92347f0f", "v6": "ff8080829e0397b9019edc2b91d67f0d"},
            "huabei_liantong":  {"v4": "ff8080829e0397b9019edc2b89827ee5", "v6": "ff8080829e0397b9019edc2b89237ee2"},
            "dongbei_dianxin":  {"v4": "ff8080829e0397b9019edc2b7f947eb6", "v6": "ff8080829e0397b9019edc2b7f347eb4"},
            "dongbei_yidong":   {"v4": "ff8080829e0397b9019edc2b91117f0a", "v6": "ff8080829e0397b9019edc2b90ae7f07"},
            "dongbei_liantong": {"v4": "ff8080829e0397b9019edc2b88577edf", "v6": "ff8080829e0397b9019edc2b87f27edd"},
            "xibei_dianxin":    {"v4": "ff8080829e0397b9019edc2b7e7c7eb1", "v6": "ff8080829e0397b9019edc2b7e157eaf"},
            "xibei_yidong":     {"v4": "ff8080829e0397b9019edc2b8feb7f04", "v6": "ff8080829e0397b9019edc2b8f8a7f02"},
            "xibei_liantong":   {"v4": "ff8080829e0397b9019edc2b871e7eda", "v6": "ff8080829e0397b9019edc2b86c97ed8"},
            "huazhong_dianxin": {"v4": "ff8080829e0397b9019edc2b7d567eac", "v6": "ff8080829e0397b9019edc2b7cf87eaa"},
            "huazhong_yidong":  {"v4": "ff8080829e0397b9019edc2b8ebd7efd", "v6": "ff8080829e0397b9019edc2b8e607efb"},
            "huazhong_liantong": {"v4": "ff8080829e0397b9019edc2b85fc7ed5", "v6": "ff8080829e0397b9019edc2b858f7ed2"},
            "huadong_dianxin":  {"v4": "ff8080829e0397b9019edc2b7c3d7ea7", "v6": "ff8080829e0397b9019edc2b7be77ea5"},
            "huadong_yidong":   {"v4": "ff8080829e0397b9019edc2b8d9a7ef8", "v6": "ff8080829e0397b9019edc2b8d3a7ef6"},
            "huadong_liantong": {"v4": "ff8080829e0397b9019edc2b84c77ecf", "v6": "ff8080829e0397b9019edc2b84667ecd"},
            "huanan_dianxin":   {"v4": "ff8080829e0397b9019edc2b7b247ea1", "v6": "ff8080829e0397b9019edc2b7ac57e9f"},
            "huanan_yidong":    {"v4": "ff8080829e0397b9019edc2b8c797ef3", "v6": "ff8080829e0397b9019edc2b8c137ef1"},
            "huanan_liantong":  {"v4": "ff8080829e0397b9019edc2b83a07eca", "v6": "ff8080829e0397b9019edc2b83417ec8"},
            "xinan_dianxin":    {"v4": "ff8080829e0397b9019edc2b79ff7e9c", "v6": "ff8080829e0397b9019edc2b79be7e99"},
            "xinan_yidong":     {"v4": "ff8080829e0397b9019edc2b8b4e7eee", "v6": "ff8080829e0397b9019edc2b8aea7eec"},
            "xinan_liantong":   {"v4": "ff8080829e0397b9019edc2b82687ec5", "v6": "ff8080829e0397b9019edc2b82087ec3"},
            # ---- 境外指定地域（仅 IPv4） ----
            "hk":               {"v4": "ff8080829dbb3f00019e46baded45c4c"},
            "tw":               {"v4": "ff8080829db64170019e46baa02f3aab"},
            "jp":               {"v4": "ff8080829db652b9019e46ba535a0394"},
            "sg":               {"v4": "ff8080829e1802e4019e46ba04bd5ac1"},
            # ---- 境外大洲（仅 IPv4） ----
            "asia":             {"v4": "ff8080829dbb31fd019e46b930625ddf"},
            "oceania":          {"v4": "ff8080829dbb31fd019e46b8e22e5dce"},
            "na":               {"v4": "ff8080829e180661019e46b8a307057d"},
            "sa":               {"v4": "ff8080829e180661019e46b85fcd0548"},
            "eu":               {"v4": "ff8080829db652b9019e46b8087102e7"},
            "af":               {"v4": "ff8080829e180661019e46b78f8c042b"},
            # ---- 境外默认（仅 IPv4） ----
            "oversea_default":  {"v4": "ff8080829db652b9019e46b70c5202bd"},
        }
    }
]

# ================= 工具函数 =================

DOH_RESOLVERS = {
    "tencent": {
        "name": "腾讯云 doh.pub",
        "endpoint": "https://doh.pub/dns-query",
    },
    "alidns": {
        "name": "阿里云 dns.alidns.com",
        "endpoint": "https://dns.alidns.com/resolve",
    },
    "google": {
        "name": "Google DoH",
        "endpoint": "https://dns.google/resolve",
    },
}
DOMESTIC_DOH_CHAIN = ["tencent", "alidns", "google"]
OVERSEA_DOH_CHAIN = ["google", "tencent", "alidns"]
DOH_RETRIES_PER_RESOLVER = 2


def is_domestic_ecs_subnet(subnet):
    """
    判断 ECS 网段是否属于国内线路配置。
    不使用 IP 前缀粗判，避免香港等境外网段被误分流到国内 DoH。
    """
    return any(
        subnet == item["subnet"]
        for subnets in DOMESTIC_SUBNETS.values()
        for item in subnets
    )


def load_ip66_reader():
    """
    每次运行尝试下载最新 IP66 MMDB。
    IP66 不含省市字段，只用于校验国家/洲和 ASN 运营商。
    """
    if not ENABLE_IP66_VALIDATION:
        print("ℹ️  IP66 校验已通过 ENABLE_IP66_VALIDATION 关闭。")
        return None

    try:
        import maxminddb
    except ImportError:
        print("⚠️  未安装 maxminddb，跳过 IP66 校验。请执行 pip install -r requirements.txt")
        return None

    try:
        tmp_path = f"{IP66_DB_PATH}.tmp"
        urllib.request.urlretrieve(IP66_DB_URL, tmp_path)
        os.replace(tmp_path, IP66_DB_PATH)
        print(f"📦 IP66 数据库已更新: {IP66_DB_PATH}")
    except Exception as e:
        if os.path.exists(IP66_DB_PATH):
            print(f"⚠️  IP66 数据库下载失败，使用本地缓存: {e}")
        else:
            print(f"⚠️  IP66 数据库下载失败且无本地缓存，跳过 IP 校验: {e}")
            return None

    try:
        return maxminddb.open_database(IP66_DB_PATH)
    except Exception as e:
        print(f"⚠️  IP66 数据库打开失败，跳过 IP 校验: {e}")
        return None


def ip66_get_record(reader, ip):
    if not reader:
        return None
    try:
        return reader.get(ip) or {}
    except Exception:
        return {}


def ip66_country_code(record):
    return ((record or {}).get("country") or {}).get("iso_code", "")


def ip66_asn_org(record):
    record = record or {}
    return (
        record.get("autonomous_system_organization")
        or ((record.get("asn") or {}).get("organization"))
        or ""
    ).upper()


def ip66_asn_number(record):
    record = record or {}
    return record.get("autonomous_system_number") or ((record.get("asn") or {}).get("number"))


def carrier_matches_asn(carrier_key, asn_number, asn_org):
    if asn_number in DOMESTIC_CARRIER_ASN_NUMBERS.get(carrier_key, set()):
        return True

    keywords = {
        "dianxin": ("CHINANET", "CHINA TELECOM", "TELECOM", "CT"),
        "yidong": ("CHINA MOBILE", "CMCC", "CMNET", "MOBILE"),
        "liantong": ("CHINA UNICOM", "UNICOM", "CHINA169", "CNCGROUP", "NETCOM"),
    }
    return any(keyword in asn_org for keyword in keywords.get(carrier_key, ()))


def region_matches_asn(region_key, carrier_key, asn_number):
    return asn_number in (
        DOMESTIC_REGION_PREFERRED_ASN_NUMBERS
        .get(region_key, {})
        .get(carrier_key, set())
    )


def build_domestic_ip_filter(reader, region_key, carrier_key):
    if not reader:
        return None

    def _filter(ip):
        record = ip66_get_record(reader, ip)
        asn_number = ip66_asn_number(record)
        asn_org = ip66_asn_org(record)
        if ip66_country_code(record) != "CN":
            return -1
        if not carrier_matches_asn(carrier_key, asn_number, asn_org):
            return -1
        if region_matches_asn(region_key, carrier_key, asn_number):
            return 2
        return 1

    return _filter


def classify_ip_candidate(ip_filter, ip):
    if not ip_filter:
        return 2

    result = ip_filter(ip)
    if isinstance(result, bool):
        return 2 if result else -1
    try:
        return int(result)
    except (TypeError, ValueError):
        return -1


def resolve_with_ecs(
    domain,
    subnet,
    record_type='A',
    ip_filter=None,
    min_results=1,
    filter_desc="",
    prefer_preferred=False,
    allow_unvalidated_fallback=False,
):
    """
    使用 DoH + ECS 查询 CDN 边缘节点 IP。
    国内网段优先走腾讯云 doh.pub，境外网段优先走 Google DoH。
    任一 DoH 不可达、握手超时或未返回目标记录时，自动切换备用 DoH。
    """
    qtype = "1" if record_type == "A" else "28"
    resolver_chain = DOMESTIC_DOH_CHAIN if is_domestic_ecs_subnet(subnet) else OVERSEA_DOH_CHAIN
    query = urllib.parse.urlencode(
        {
            "name": domain,
            "type": qtype,
            "edns_client_subnet": subnet,
        },
        safe="/",
    )
    errors = []
    candidate_scores = {}
    candidate_order = []
    unvalidated_fallback = []
    unvalidated_seen = set()

    def remember_candidate(ip, score):
        if ip not in candidate_scores:
            candidate_order.append(ip)
            candidate_scores[ip] = score
        elif score > candidate_scores[ip]:
            candidate_scores[ip] = score

    def selected_candidates(min_score=1):
        return [ip for ip in candidate_order if candidate_scores.get(ip, -1) >= min_score]

    for query_round in range(1, IP66_MAX_QUERY_ROUNDS + 1):
        for resolver_key in resolver_chain:
            resolver = DOH_RESOLVERS[resolver_key]
            url = f"{resolver['endpoint']}?{query}"

            for attempt in range(1, DOH_RETRIES_PER_RESOLVER + 1):
                try:
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Accept': 'application/dns-json',
                    })
                    response = urllib.request.urlopen(req, timeout=10)
                    data = json.loads(response.read().decode('utf-8'))

                    ips = []
                    if 'Answer' in data:
                        for answer in data['Answer']:
                            if str(answer['type']) == qtype:
                                ips.append(answer['data'])

                    if ips:
                        valid_count = 0
                        preferred_count = 0
                        for ip in ips:
                            score = classify_ip_candidate(ip_filter, ip)
                            if score >= 1:
                                remember_candidate(ip, score)
                                valid_count += 1
                                if score >= 2:
                                    preferred_count += 1
                            elif allow_unvalidated_fallback and ip not in unvalidated_seen:
                                unvalidated_seen.add(ip)
                                unvalidated_fallback.append(ip)

                        preferred_ips = selected_candidates(2)
                        valid_ips = selected_candidates(1)
                        if prefer_preferred:
                            if len(preferred_ips) >= min_results:
                                return preferred_ips
                        elif len(valid_ips) >= min_results:
                            return valid_ips
                        if ip_filter:
                            errors.append(
                                f"{resolver['name']} 第 {query_round} 轮 {valid_count}/{len(ips)} 个符合 {filter_desc}，其中 {preferred_count} 个优先"
                            )
                        else:
                            errors.append(f"{resolver['name']} 第 {query_round} 轮仅获得 {len(ips)} 个 {record_type} 结果")
                        break

                    errors.append(f"{resolver['name']} 无 {record_type} 结果")
                    break
                except Exception as e:
                    errors.append(f"{resolver['name']} 第 {attempt} 次失败: {e}")
                    if attempt < DOH_RETRIES_PER_RESOLVER:
                        time.sleep(0.3)

        if selected_candidates(1) or unvalidated_fallback:
            time.sleep(0.5)

    tail = "; ".join(errors[-3:])
    preferred_ips = selected_candidates(2)
    valid_ips = selected_candidates(1)
    if prefer_preferred and preferred_ips:
        preferred_seen = set(preferred_ips)
        merged = preferred_ips + [ip for ip in valid_ips if ip not in preferred_seen]
        if len(preferred_ips) < min_results:
            print(f"    [WARN] 使用网段 {subnet} 查询 {record_type} 仅获得 {len(preferred_ips)}/{min_results} 个优先 IP，使用 CN+运营商候选补齐: {tail}")
        return merged
    if valid_ips:
        print(f"    [WARN] 使用网段 {subnet} 查询 {record_type} 仅获得 {len(valid_ips)}/{min_results} 个有效 IP: {tail}")
        return valid_ips
    if allow_unvalidated_fallback and unvalidated_fallback:
        print(f"    [WARN] 使用网段 {subnet} 查询 {record_type} 未获得通过 IP66 的 IP，兜底使用未校验结果: {tail}")
        return unvalidated_fallback

    print(f"    [WARN] 使用网段 {subnet} 查询 {record_type} 失败，所有 DoH 通道均无有效结果: {tail}")
    return []


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
    - 国内三网：保留 IPv4 + IPv6 双栈，每个地区/运营商网段最多 3 个
    - 三网默认：按运营商拆成电信/移动/联通三条，北上广川每地区前 2 个
    - 国内大区：按大区 + 运营商拆分记录
    - 境外所有分组：仅查询 IPv4，不查 IPv6
    - 全网默认：国内 7 大区每区前 2 个，最多 16 个
    """
    print(f"🔍 正在通过智能分流 DoH + ECS 获取 {TARGET_DOMAIN} 的真实边缘节点 IP...\n")
    ip66_reader = load_ip66_reader()

    # ---------- 阶段一：查询国内三网大区 ----------
    print("=" * 55)
    print("📌 阶段一：国内三网大区（IPv4 + IPv6 双栈）")
    print("=" * 55)

    line_results = {}
    domestic_default_results = {
        carrier_key: {area: {"v4": [], "v6": []} for area in DOMESTIC_DEFAULT_SOURCE_AREAS}
        for carrier_key in DOMESTIC_DEFAULT_LINE_KEYS
    }

    for region_key in DOMESTIC_ROUTE_REGION_KEYS:
        entries = DOMESTIC_SUBNETS[region_key]
        region_name = LINE_NAME_MAP.get(region_key, region_key)
        print(f"  📡 正在查询 [{region_name}] ...")

        for item in entries:
            area = item["area"]
            carrier = item["carrier"]
            carrier_key = CARRIER_KEY_BY_NAME[carrier]
            subnet = item["subnet"]
            line_key = f"{region_key}_{carrier_key}"
            ip_filter = build_domestic_ip_filter(ip66_reader, region_key, carrier_key)
            filter_desc = f"CN/{carrier}/省份ASN优先"

            v4_res = resolve_with_ecs(
                TARGET_DOMAIN,
                subnet,
                'A',
                ip_filter=ip_filter,
                min_results=DOMESTIC_MAX_IPS_PER_SUBNET,
                filter_desc=filter_desc,
                prefer_preferred=True,
                allow_unvalidated_fallback=True,
            )
            v4_limited = []
            if v4_res:
                v4_limited = v4_res[:DOMESTIC_MAX_IPS_PER_SUBNET]

            v6_res = resolve_with_ecs(
                TARGET_DOMAIN,
                subnet,
                'AAAA',
                min_results=DOMESTIC_MAX_IPS_PER_SUBNET,
            )
            v6_limited = []
            if v6_res:
                v6_limited = v6_res[:DOMESTIC_MAX_IPS_PER_SUBNET]

            line_results[line_key] = {
                "v4": list(dict.fromkeys(v4_limited)),
                "v6": list(dict.fromkeys(v6_limited)),
            }

            if area in DOMESTIC_DEFAULT_SOURCE_AREAS:
                domestic_default_results[carrier_key][area]["v4"].extend(v4_limited)
                domestic_default_results[carrier_key][area]["v6"].extend(v6_limited)

            print(f"     ✅ [{region_name}-{carrier}] IPv4 {len(v4_limited)} 个, IPv6 {len(v6_limited)} 个")
            time.sleep(0.2)

    for carrier_key, carrier_name in DOMESTIC_CARRIERS:
        default_v4 = build_china_default(domestic_default_results, carrier_key, "v4")
        default_v6 = build_china_default(domestic_default_results, carrier_key, "v6")
        line_results[carrier_key] = {"v4": default_v4, "v6": default_v6}
        print(f"  ✅ [三网默认-{carrier_name}] IPv4 {len(default_v4)} 个, IPv6 {len(default_v6)} 个（北上广川每地区最多2）")


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
            v4_res = resolve_with_ecs(
                TARGET_DOMAIN,
                subnet,
                'A',
                min_results=1,
            )
            all_v4.extend(v4_res)
            if all_v4:
                break
            time.sleep(0.2)

        all_v4 = list(dict.fromkeys(all_v4))
        region_ips[region_key] = all_v4
        print(f"     ✅ [{region_name}] IPv4 {len(all_v4)} 个")

    # ---------- 阶段三：构建境外分层线路 ----------
    print(f"\n{'=' * 55}")
    print("📌 阶段三：构建境外分层线路（均衡轮询）")
    print("=" * 55)

    # --- 境外指定地域：直接使用对应地区 IP，上限 50 ---
    print("\n  🏷️  境外指定地域：")
    for key in TIER1_KEYS:
        ips = region_ips.get(key, [])[:MAX_RECORDS_PER_SET]
        line_results[key] = {"v4": ips, "v6": []}
        name = LINE_NAME_MAP.get(key, key)
        print(f"     {name}: IPv4 {len(ips)} 个")

    # --- 境外大洲：从多个指定地域均衡轮询 ---
    print("\n  🏷️  境外大洲：")
    tier2_ips = {}  # 保存境外大洲结果，供境外默认使用
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

    # --- 境外默认：从境外大洲均衡轮询 ---
    print("\n  🏷️  境外默认：")
    tier3_ip_groups = {}
    for gk in TIER3_SOURCES:
        if tier2_ips.get(gk):
            tier3_ip_groups[gk] = tier2_ips[gk]

    oversea_default = round_robin_merge(tier3_ip_groups)
    line_results[TIER3_KEY] = {"v4": oversea_default, "v6": []}
    name = LINE_NAME_MAP.get(TIER3_KEY, TIER3_KEY)
    print(f"     {name}: IPv4 {len(oversea_default)} 个")

    # ---------- 阶段四：构建全网默认（国内大区均衡） ----------
    print(f"\n{'=' * 55}")
    print("📌 阶段四：全网默认（国内大区均衡，IPv4 + IPv6）")
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
        DOMESTIC_DEFAULT_LINE_KEYS
        + DOMESTIC_REGION_LINE_KEYS
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
        if key in DOMESTIC_LINE_KEYS:
            note = "双栈"
        elif key in OVERSEA_SUBNETS or key in TIER2_GROUPS or key == TIER3_KEY:
            note = "仅IPv4"
        print(f"  {name:<14} {v4c:>6}  {v6c:>6}  {note}")

    return line_results


def build_china_default(domestic_default_results, carrier_key, ip_version):
    """三网默认：指定运营商从北上广川每地区取前 2 个，最多 8 个。"""
    result = []
    for area in DOMESTIC_DEFAULT_SOURCE_AREAS:
        result.extend(
            domestic_default_results
            .get(carrier_key, {})
            .get(area, {})
            .get(ip_version, [])[:DOMESTIC_DEFAULT_MAX_IPS_PER_AREA]
        )
    return list(dict.fromkeys(result))[:len(DOMESTIC_DEFAULT_SOURCE_AREAS) * DOMESTIC_DEFAULT_MAX_IPS_PER_AREA]


def build_balanced_default(line_results, ip_version):
    """全网默认：从国内 7 大区各取前 2 个，最多 16 个。"""
    result = []
    for region_key in DOMESTIC_ROUTE_REGION_KEYS:
        region_groups = {
            carrier_key: line_results.get(f"{region_key}_{carrier_key}", {}).get(ip_version, [])
            for carrier_key, _ in DOMESTIC_CARRIERS
        }
        result.extend(round_robin_merge(region_groups, max_total=GLOBAL_DEFAULT_MAX_IPS_PER_REGION))
    return list(dict.fromkeys(result))[:GLOBAL_DEFAULT_MAX_IPS]


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
        DOMESTIC_DEFAULT_LINE_KEYS
        + DOMESTIC_REGION_LINE_KEYS
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

    # 1. 通过智能分流 DoH + ECS 获取各线路 IP
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
        DOMESTIC_DEFAULT_LINE_KEYS
        + DOMESTIC_REGION_LINE_KEYS
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
