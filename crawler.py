"""당근부동산 공개 지도 페이지 HTML에서 매물 SSR 데이터를 읽는 크롤러.
별도 매물 API 호출 없이, 페이지 HTML 안에 포함된 window.RELAY_STORE를 파싱합니다.
"""
import json, re, time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources.txt"
OUTPUT = ROOT / "docs" / "data.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    print(f"HTTP {r.status_code}: {r.url}")
    r.raise_for_status()
    return r.text

def extract_store(html):
    # Current page embeds a JSON-escaped Relay store string.
    m = re.search(r'window\\.RELAY_STORE\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"', html)
    if m:
        try:
            return json.loads(json.loads('"' + m.group(1) + '"'))
        except (ValueError, TypeError):
            pass
    # Fallback for a direct object literal.
    pos = html.find("window.RELAY_STORE")
    if pos < 0:
        return None
    start = html.find("{", html.find("=", pos))
    if start < 0:
        return None
    depth, quoted, escaped = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if quoted:
            if escaped: escaped = False
            elif ch == "\\\\": escaped = True
            elif ch == '"': quoted = False
        else:
            if ch == '"': quoted = True
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try: return json.loads(html[start:i+1])
                    except ValueError: return None
    return None

def deref(store, value):
    if isinstance(value, dict) and "__ref" in value:
        return store.get(value["__ref"])
    return value

def refs(store, node, key):
    value = node.get(key)
    if isinstance(value, dict) and "__refs" in value:
        return [store[x] for x in value["__refs"] if x in store]
    if isinstance(value, dict) and "__ref" in value:
        return [store[value["__ref"]]] if value["__ref"] in store else []
    if isinstance(value, list):
        return [store[x["__ref"]] for x in value if isinstance(x, dict) and x.get("__ref") in store]
    return []

def money(v):
    try: return int(float(v)) if v is not None else None
    except (TypeError, ValueError): return None

def parse_store(store, region_label, source_url, collected_at):
    out = []
    for card in store.values():
        if not isinstance(card, dict) or card.get("__typename") != "ArticleFeedCard":
            continue
        article = deref(store, card.get("article"))
        if not isinstance(article, dict) or article.get("__typename") != "Article":
            continue
        aid = article.get("originalId")
        area = article.get("area")
        try: area = float(area) if area not in (None, "") else None
        except (TypeError, ValueError): area = None
        sales_obj = deref(store, article.get("salesTypeV3"))
        housing = sales_obj.get("type") if isinstance(sales_obj, dict) else ""
        title = str(article.get("title") or article.get("articleName") or "")
        # trade values are in 만원: deposit=보증금, monthlyPay=월세, price=매매가
        for trade in refs(store, article, "trades"):
            typename = trade.get("__typename", "")
            if typename == "BorrowTrade":
                kind, deposit, monthly = "전세", money(trade.get("deposit")), 0
            elif typename == "MonthTrade":
                kind, deposit, monthly = "월세", money(trade.get("deposit")), money(trade.get("monthlyPay"))
            else:
                continue
            if deposit is None or (kind == "월세" and monthly is None):
                continue
            out.append({
                "sido": region_label.split()[0] if region_label.split() else "",
                "sigungu": region_label.split()[1] if len(region_label.split()) > 1 else "",
                "neighborhood": region_label.split()[2] if len(region_label.split()) > 2 else "",
                "rent_type": kind, "housing_type": housing or "주택",
                "deposit_manwon": deposit, "monthly_rent_manwon": monthly,
                "area_m2": area, "building": title[:100] or "주택 매물",
                "listing_title": title or f"{region_label} {kind} 매물",
                "listing_url": f"https://realty.daangn.com/articles/{aid}" if aid else source_url,
                "source_url": source_url, "collected_at": collected_at
            })
    return out

def main():
    if not SOURCES.exists():
        raise SystemExit("sources.txt 파일이 없습니다.")
    # Each line: URL | province district neighborhood
    sources = []
    for line in SOURCES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        bits = [x.strip() for x in line.split("|", 1)]
        sources.append((bits[0], bits[1] if len(bits) > 1 else ""))
    if not sources: raise SystemExit("sources.txt에 공개 HTML 페이지 주소가 없습니다.")
    records, seen, failures = [], set(), []
    for url, region in sources:
        try:
            html = fetch(url)
            store = extract_store(html)
            if not store:
                failures.append({"url": url, "error": "HTML에서 window.RELAY_STORE를 찾지 못함"})
                print("  RELAY_STORE 없음: 페이지 구조 변경 또는 접근 차단 가능")
                continue
            rows = parse_store(store, region, url, datetime.now().astimezone().isoformat(timespec="seconds"))
            count_before = len(records)
            for row in rows:
                key = (row["listing_url"], row["rent_type"], row["deposit_manwon"], row["monthly_rent_manwon"])
                if key not in seen:
                    seen.add(key); records.append(row)
            print(f"  {region}: {len(records)-count_before}건")
            if not rows: failures.append({"url": url, "error": "HTML은 읽었지만 전세·월세 매물이 없음"})
            time.sleep(1.5)
        except requests.RequestException as e:
            failures.append({"url": url, "error": str(e)[:200]})
            print("  요청 실패:", str(e)[:160])
    if not records:
        raise SystemExit("실제 매물 0건: 기존 docs/data.json은 유지했습니다. Actions 로그의 HTTP 상태와 RELAY_STORE 메시지를 확인하세요.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "source": "당근부동산 공개 HTML",
        "source_urls": [x[0] for x in sources],
        "collection_method": "requests로 공개 지도 페이지 HTML을 가져와 window.RELAY_STORE를 파싱",
        "updated_at": datetime.now().astimezone().date().isoformat(),
        "count": len(records), "records": records, "failures": failures,
        "note": "등록된 지역 페이지에서 HTML에 포함된 실제 전세·월세 매물만 수집했습니다. 전국 전체를 망라하지 않으며, 방문 전 원문에서 거래 가능 여부를 확인하세요."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: 실제 매물 {len(records)}건")

if __name__ == "__main__":
    main()
