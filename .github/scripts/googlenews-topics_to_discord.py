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

def replace_brackets(text):
    # 대괄호를 한글 괄호로 변경하는 함수
    return text.replace("[", "〔").replace("]", "〕")
    
def parse_html_description(html_desc):
    # HTML 내용에서 뉴스 기사 정보를 추출하는 함수
    # HTML 엔티티를 디코딩하고, <ol> 태그 내의 <li> 태그를 찾아 뉴스 정보를 추출합니다.
    html_desc = unescape(html_desc)
    items = re.findall(r'<li>(.*?)</li>', html_desc, re.DOTALL)

    news_items = []
    full_content_link = ""  # "전체 콘텐츠 보기" 링크 초기화
    for item in items:
        if 'Google 뉴스에서 전체 콘텐츠 보기' in item:
            full_content_link_match = re.search(r'<a href="(https://news\.google\.com/stories/.*?)"', item)
            if full_content_link_match:
                full_content_link = full_content_link_match.group(1)
            continue  # "전체 콘텐츠 보기" 링크는 뉴스 목록에 추가하지 않음

        # 일반 뉴스 항목 처리
        title_match = re.search(r'<a href="(.*?)".*?>(.*?)</a>', item)
        press_match = re.search(r'<font color="#6f6f6f">(.*?)</font>', item)
        if title_match and press_match:
            link, title_text = title_match.groups()
            title_text = replace_brackets(title_text)  # 대괄호를 한글 괄호로 변경
            press_name = press_match.group(1)
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)
    if full_content_link:
        news_string += f"\n\n▶️ [Google 뉴스에서 전체 콘텐츠 보기](<{full_content_link}>)"

    return news_string

def parse_rss_date(pub_date):
    # RSS 피드의 날짜를 파싱하여 지역 시간대로 변환하는 함수
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

def send_discord_message(webhook_url, message):
    # Discord 웹훅 URL로 메시지를 전송하는 함수
    payload = {"content": message}
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    return response

def main():
    # 메인 함수: Google 뉴스 RSS 피드를 가져오고, 파싱한 후 Discord로 메시지를 전송합니다.
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

# Gist 관련 설정
    gist_id = os.environ.get('GIST_ID_TOPICS')
    gist_token = os.environ.get('GIST_TOKEN')
    gist_url = f"https://api.github.com/gists/{gist_id}"

    # 이전에 게시된 게시물의 ID를 Gist에서 가져옵니다.
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

        title = replace_brackets(title)  # 대괄호를 한글 괄호로 변경
        formatted_date = parse_rss_date(pub_date)

        # Discord에 메시지를 포맷하여 전송합니다.
        discord_message = f"`Google 뉴스 - 주요 뉴스 - 한국 🇰🇷`\n**[{title}](<{link}>)**\n>>> {description}\n📅 {formatted_date}"
        send_discord_message(webhook_url, discord_message)
        posted_guids.append(guid)
        time.sleep(3)  # 뉴스 항목 간에 1초의 딜레이를 추가합니다.

    # 게시된 뉴스 항목의 GUID를 업데이트하여 Gist에 저장합니다.
    updated_guids = '\n'.join(posted_guids)
    gist_files = {'googlenews-topics_posted_guids.txt': {'content': updated_guids}}
    gist_payload = {'files': gist_files}
    gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

if __name__ == "__main__":
    main()
