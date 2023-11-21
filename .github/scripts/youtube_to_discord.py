import os
import requests
import html
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import time 

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', '0')

# YouTube Data API를 초기화합니다.
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Discord에 메시지를 게시하는 함수
def post_to_discord(message):
    payload = {"content": message}
    headers = {'Content-Type': 'application/json'}
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload, headers=headers)
    if response.status_code != 204:
        print(f"Discord에 메시지를 게시하는 데 실패했습니다. 상태 코드: {response.status_code}")
        print(response.text)
    else:
        time.sleep(3)  # 메시지 게시 후 3초 대기

# YouTube 동영상 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    max_results = 15 if IS_FIRST_RUN == '1' else 30

    # YouTube에서 동영상을 가져옵니다.
    videos = youtube.search().list(
        channelId=YOUTUBE_CHANNEL_ID,
        order='date',
        type='video',
        part='snippet',
        maxResults=max_results
    ).execute()

    if 'items' not in videos:
        print("동영상을 찾을 수 없습니다.")
        return

    # Gist 설정
    gist_id = os.getenv('GIST_ID_YOUTUBE')
    gist_token = os.getenv('GIST_TOKEN')
    gist_url = f"https://api.github.com/gists/{gist_id}"

    # Gist에서 이전 게시된 GUID 목록 가져오기
    gist_headers = {"Authorization": f"token {gist_token}"}
    gist_response = requests.get(gist_url, headers=gist_headers).json()
    posted_guids = gist_response['files']['youtube_posted_guids.txt']['content'].splitlines()

    # Discord 웹훅 설정
    webhook_url = os.getenv('DISCORD_WEBHOOK_YOUTUBE')

    # 최초 실행 여부 확인
    is_first_run = IS_FIRST_RUN == '1'

    # 최초 실행 시 가져온 동영상 목록을 한 번에 Discord에 게시합니다.
    if is_first_run:
        recent_videos = videos['items'][:15]  # 최근 업데이트된 15개의 동영상 가져오기
        video_list = []
        for video in recent_videos:
            video_title = html.unescape(video['snippet']['title'])
            channel_title = html.unescape(video['snippet']['channelTitle'])
            video_id = video['id']['videoId']
            video_url = f"https://youtu.be/{video_id}"
            message = f"`{channel_title} - YouTube`\n**{video_title}**\n{video_url}"
            video_list.append(message)

        # 최초 실행이므로 가져온 동영상 목록을 Gist에 저장합니다.
        updated_guids = '\n'.join([video['id']['videoId'] for video in recent_videos])
        gist_files = {'youtube_posted_guids.txt': {'content': updated_guids}}
        gist_payload = {'files': gist_files}
        gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

        # 최초 실행 시 가져온 동영상 목록을 한 번에 Discord에 게시합니다.
        summary_message = "최초 실행: 가져온 YouTube 동영상 목록\n\n" + "\n".join(video_list)
        post_to_discord(summary_message)

    # 새로운 영상 확인 및 Discord에 보내기
    for video in reversed(videos['items']):  # 오래된 순서로 게시
        video_id = video['id']['videoId']

        # 이미 게시된 GUID인지 확인
        if video_id in posted_guids and not is_first_run:
            continue  # 중복된 항목은 무시

        video_title = html.unescape(video['snippet']['title'])
        channel_title = html.unescape(video['snippet']['channelTitle'])
        video_url = f"https://youtu.be/{video_id}"
        message = f"`{channel_title} - YouTube`\n**{video_title}**\n{video_url}"
        
        # Discord에 메시지 보내기
        post_to_discord(message)

        # 게시된 GUID 목록에 추가
        posted_guids.append(video_id)
        time.sleep(3)

    # 게시된 GUID 목록을 업데이트하여 Gist에 저장합니다.
    updated_guids = '\n'.join(posted_guids)
    gist_files = {'youtube_posted_guids.txt': {'content': updated_guids}}
    gist_payload = {'files': gist_files}
    gist_update_response = requests.patch(gist_url, json=gist_payload, headers=gist_headers)

# 메인 함수 실행
def main():
    try:
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    main()
