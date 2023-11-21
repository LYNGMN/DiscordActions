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
    # HTML 엔티티 디코딩
    html_desc = unescape(html_desc)

    # <ol> 태그 내의 모든 <li> 태그 파싱
    items = re.findall(r'<li>(.*?)</li>', html_desc, re.DOTALL)

    news_items = []
    for item in items:
        # 뉴스 제목, 링크, 언론사명 추출
        title_match = re.search(r'<a href="(.*?)".*?>(.*?)</a>', item)
        press_match = re.search(r'<font color="#6f6f6f">(.*?)</font>', item)
        if title_match and press_match:
            link, title_text = title_match.groups()
            title_text = replace_brackets(title_text)  # 대괄호를 한글 괄호로 변경
            press_name = press_match.group(1)
            news_item = f"- [{title_text}](<{link}>) | {press_name}"
            news_items.append(news_item)

    news_string = '\n'.join(news_items)
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
    posted_guids = gist_response['files']['googlenews_posted_guids.txt']['content'].splitlines()

    # Discord 웹훅 설정
    webhook_url = os.environ.get('DISCORD_WEBHOOK_NEWS')

    # 뉴스 항목 처리
    news_items = root.findall('.//item')
    for index, item in enumerate(news_items):
        guid = item.find('guid').text

        # 이미 게시된 GUID인지 확인
        if guid in posted_guids:
            continue  # 중복된 항목은 무시

        title = item.find('title').text
        title = replace_brackets(title)  # 대괄호를 한글 괄호로 변경
        link = item.find('link').text
        pub_date = item.find('pubDate').text
        description_html = item.find('description').text
        description = parse_html_description(description_html)

        formatted_date = parse_rss_date(pub_date)

        # Discord에 메시지를 포맷하여 전송
        discord_message = f"`Google 뉴스 - 편두통`\n**[{title}](<{link}>)**\n>>> {description}\n📅 {formatted_date}"
        send_discord_message(webhook_url, discord_message)

        # 게시된 GUID 목록에 추가
        posted_guids.append(guid)
        time.sleep(3)

    # Gist 업데이트
    updated_guids = '\n'.join(posted_guids)
    gist_files = {'googlenews_posted_guids.txt': {'content': updated_guids}}
    gist_payload = {'files': gist_files}
    gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

if __name__ == "__main__":
    main()