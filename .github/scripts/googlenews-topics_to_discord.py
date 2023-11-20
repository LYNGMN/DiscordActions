import xml.etree.ElementTree as ET
import requests
from html import unescape
import re
import os
import time
from datetime import datetime
from dateutil import parser
from dateutil.tz import gettz

def fetch_rss_feed(url):
    # 주어진 URL에서 RSS 피드를 가져옵니다.
    response = requests.get(url)
    return response.content

def parse_html_description(html_desc):
    # HTML 내용에서 특정 태그를 파싱하여 뉴스 기사 정보를 추출합니다.
    # HTML 엔티티를 디코딩합니다.
    html_desc = unescape(html_desc)

    # <ol> 태그 내의 모든 <li> 태그를 찾습니다.
    items = re.findall(r'<li>(.*?)</li>', html_desc, re.DOTALL)

    news_items = []
    full_content_link = None
    for item in items:
        # "Google 뉴스에서 전체 콘텐츠 보기" 링크를 처리합니다.
        if 'Google 뉴스에서 전체 콘텐츠 보기' in item:
            full_content_link_match = re.search(r'<a href="(https://news\.google\.com/stories/.*?)"', item)
            if full_content_link_match:
                full_content_link = full_content_link_match.group(1)
            continue  # 이 항목은 뉴스 목록에 추가하지 않습니다.

        # 일반 뉴스 항목을 처리합니다.
        title_match = re.search(r'<a href="(.*?)".*?>(.*?)</a>', item)
        press_match = re.search(r'<font color="#6f6f6f">(.*?)</font>', item)
        if title_match and press_match:
            link, title_text = title_match.groups()
            # 대괄호를 이스케이프 처리합니다.
            title_text = title_text.replace("[", "\\[").replace("]", "\\]")
            press_name = press_match.group(1)
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)

    # "Google 뉴스에서 전체 콘텐츠 보기" 링크를 추가합니다.
    if full_content_link:
        news_string += f"\n\n▶️ [Google 뉴스에서 전체 콘텐츠 보기](<{full_content_link}>)"

    return news_string

def parse_rss_date(pub_date):
    # RSS 피드의 날짜를 파싱하여 지역 시간대로 변환합니다.
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

def send_discord_message(webhook_url, message):
    # Discord 웹훅 URL로 메시지를 전송합니다.
    payload = {"content": message}
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    return response

def main():
    # 메인 함수: RSS 피드를 가져오고, 파싱한 다음 Discord로 메시지를 전송합니다.
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    # Gist 관련 설정
    gist_id = os.environ.get('GIST_ID_TOPICS')
    gist_token = os.environ.get('GIST_TOKEN')
    gist_url = f"https://api.github.com/gists/{gist_id}"

    # Gist에서 이전 게시물 ID를 가져옵니다.
    gist_headers = {"Authorization": f"token {gist_token}"}
    gist_response = requests.get(gist_url, headers=gist_headers).json()
    posted_guids = gist_response['files']['googlenews-topics_posted_guids.txt']['content'].splitlines()

    webhook_url = os.environ.get('DISCORD_WEBHOOK_TOPICS')

    # 뉴스 항목을 처리합니다.
    news_items = root.findall('.//item')
    for index, item in enumerate(news_items):
        guid = item.find('guid').text
        title = item.find('title').text
        link = item.find('link').text
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        description = parse_html_description(description_html)
        formatted_date = parse_rss_date(pub_date)
        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**[{title}](<{link}>)**\n>>> {description}\n📅 {formatted_date}"
        send_discord_message(webhook_url, discord_message)
        posted_guids.append(guid)
        time.sleep(1)  # 뉴스 항목 간에 1초의 딜레이를 추가합니다.

    # Gist를 업데이트합니다.
    updated_guids = '\n'.join(posted_guids)
    gist_files = {'googlenews-topics_posted_guids.txt': {'content': updated_guids}}
    gist_payload = {'files': gist_files}
    gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

if __name__ == "__main__":
    main()
