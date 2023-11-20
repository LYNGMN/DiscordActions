import xml.etree.ElementTree as ET
import requests
from html import unescape
import re
import os
import time
from datetime import datetime
from dateutil import parser
from dateutil.tz import gettz

# RSS 피드를 가져오는 함수
def fetch_rss_feed(url):
    response = requests.get(url)
    return response.content

# HTML 설명을 파싱하여 뉴스 기사 제목과 링크, 언론사명을 추출하는 함수
def parse_html_description(html_desc):
    html_desc = unescape(html_desc)  # HTML 엔티티 디코딩
    items = re.findall(r'<li>(.*?)</li>', html_desc, re.DOTALL)

    news_items = []
    for item in items:
        title_match = re.search(r'<a href="(.*?)".*?>(.*?)</a>', item)
        press_match = re.search(r'<font color="#6f6f6f">(.*?)</font>', item)

        if title_match and press_match:
            link, title_text = title_match.groups()
            # 대괄호 이스케이프 처리
            title_text = title_text.replace("[", "\\[").replace("]", "\\]")
            press_name = press_match.group(1)
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)
    return news_string

# RSS 피드의 날짜를 파싱하는 함수
def parse_rss_date(pub_date):
    dt = parser.parse(pub_date)
    dt_kst = dt.astimezone(gettz('Asia/Seoul'))
    return dt_kst.strftime('%Y년 %m월 %d일 %H:%M:%S')

# Discord에 메시지를 보내는 함수
def send_discord_message(webhook_url, message):
    payload = {"content": message}
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, json=payload, headers=headers)
    return response

# 메인 함수
def main():
    rss_url = "https://news.google.com/rss?q=%ED%8E%B8%EB%91%90%ED%86%B5&hl=ko&gl=KR&ceid=KR:ko"
    rss_data = fetch_rss_feed(rss_url)
    root = ET.fromstring(rss_data)

    # Gist 관련 설정
    gist_id = os.environ.get('GIST_ID_NEWS')
    gist_token = os.environ.get('GIST_TOKEN')
    gist_url = f"https://api.github.com/gists/{gist_id}"

    # Gist에서 이전 게시물 ID 가져오기
    gist_headers = {"Authorization": f"token {gist_token}"}
    gist_response = requests.get(gist_url, headers=gist_headers).json()
    posted_guids = gist_response['files']['posted_guids.txt']['content'].splitlines()

    # Discord 웹훅 설정
    webhook_url = os.environ.get('DISCORD_WEBHOOK_NEWS')

    # 뉴스 항목 처리
    news_items = root.findall('.//item')
    for index, item in enumerate(news_items):
        guid = item.find('guid').text
        title = item.find('title').text
        link = item.find('link').text
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        description = parse_html_description(description_html)

        formatted_date = parse_rss_date(pub_date)
        discord_message = f"`Google 뉴스 - 편두통`\n**[{title}](<{link}>)**\n>>> {description}\n📅 {formatted_date}"
        send_discord_message(webhook_url, discord_message)
        posted_guids.append(guid)
        time.sleep(1)

    # Gist 업데이트
    updated_guids = '\n'.join(posted_guids)
    gist_files = {'posted_guids.txt': {'content': updated_guids}}
    gist_payload = {'files': gist_files}
    gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

if __name__ == "__main__":
    main()
