"""Public HTML crawler: requests + BeautifulSoup only; no API."""
import json, re, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

START_URL = "https://vacancy.zaritalk.com/region/%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C-%EC%A4%91%EA%B5%AC"
OUTPUT = Path("docs/data.json")
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; StudentHousingResearch/1.0)", "Accept-Language":"ko-KR,ko;q=0.9"}
def clean(s): return re.sub(r"\\s+", " ", s or "").strip()
def money(s):
    s=s.replace(",","").strip(); total=0
    if "억" in s:
        a,_,s=s.partition("억"); total=int(a or 0)*10000
    s=s.replace("만","").strip()
    if s.isdigit(): total+=int(s)
    return total or None
def main():
    response=requests.get(START_URL,headers=HEADERS,timeout=25)
    print("HTTP",response.status_code,"URL",response.url)
    response.raise_for_status()
    if "text/html" not in response.headers.get("Content-Type",""):
        raise RuntimeError("HTML이 아닌 응답입니다. API로 대체하지 않고 중단합니다.")
    soup=BeautifulSoup(response.content,"html.parser")
    page_text=clean(soup.get_text(" ",strip=True))
    if not any(x in page_text for x in ("매물","전세","월세")):
        raise RuntimeError("받은 HTML에서 매물 텍스트를 찾지 못했습니다.")
    records=[]; seen=set()
    for a in soup.select("a[href]"):
        title=clean(a.get_text(" ",strip=True))
        if not title or not any(x in title for x in ("전세","월세")): continue
        if not any(x in title for x in ("원룸","투룸","빌라","다세대","연립")): continue
        typ="전세" if "전세" in title else "월세"
        m=re.search(r"(?:전세|월세)\\s*([0-9,억만]+)(?:\\s*/\\s*([0-9,]+))?",title)
        if not m: continue
        dep=money(m.group(1)); mon=money(m.group(2) or "0") if typ=="월세" else 0
        if dep is None: continue
        link=urljoin(response.url,a.get("href",""))
        if link in seen: continue
        seen.add(link)
        dong=re.search(r"서울\\s*중구\\s*([^\\s,]+)",title)
        kind=next((x for x in ("원룸","투룸","빌라","다세대","연립") if x in title),"")
        area=re.search(r"([0-9]+(?:\\.[0-9]+)?)\\s*평",title)
        records.append({"sido":"서울특별시","sigungu":"중구","neighborhood":dong.group(1) if dong else "",
          "rent_type":typ,"housing_type":kind,"deposit_manwon":dep,"monthly_rent_manwon":mon or 0,
          "area_m2":round(float(area.group(1))*3.3058,1) if area else None,"building":"공개 매물",
          "listing_title":title[:240],"listing_url":link,"source_url":response.url,
          "collected_at":datetime.now().astimezone().isoformat(timespec="seconds")})
    time.sleep(1)
    if not records:
        raise RuntimeError("HTML 요청은 됐지만 매물 카드 구조를 추출하지 못했습니다. 가짜 데이터나 API로 대체하지 않았습니다.")
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    doc={"source":"자리톡 공개 지역별 매물 페이지","source_url":START_URL,
      "collection_method":"requests + BeautifulSoup HTML 크롤링 (API 미사용)",
      "updated_at":datetime.now().astimezone().date().isoformat(),"count":len(records),
      "records":records,"note":"공개 HTML에 노출된 정보만 수집합니다. 게시일이 노출되지 않으면 최신 등록일은 보장할 수 없습니다."}
    OUTPUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    print("수집 완료:",len(records),"건")
if __name__=="__main__": main()
