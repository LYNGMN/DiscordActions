import os
import requests
import datetime
import time
import html
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from github import Github  # PyGithub 라이브러리 추가

# 환경 변수에서 필요한 정보를 가져옵니다.
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')  # GIST 관리를 위한 GitHub 토큰
GIST_ID = os.getenv('GIST_ID')  # 동영상 ID를 저장할 GIST ID
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', '0')

# YouTube Data API와 GitHub를 초기화합니다.
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
github = Github(GITHUB_TOKEN)

# GIST에서 동영상 ID 목록을 가져오는 함수
def get_posted_videos():
    gist = github.get_gist(GIST_ID)
    return gist.files["posted_videos.txt"].content.split('\n')

# GIST에 동영상 ID를 추가하는 함수
def update_posted_videos(video_ids):
    gist = github.get_gist(GIST_ID)
    current_content = gist.files["posted_videos.txt"].content
    updated_content = current_content + '\n'.join(video_ids)
    gist.edit(files={"posted_videos.txt": github.InputFileContent(updated_content)})

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
    posted_video_ids = get_posted_videos() if IS_FIRST_RUN != '1' else []

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

    new_video_ids = []

    for video in reversed(videos['items']):  # 오래된 순서로 처리
        video_id = video['id']['videoId']

        # 동영상이 이미 게시된 경우 건너뜁니다.
        if video_id in posted_video_ids:
            continue

        video_title = html.unescape(video['snippet']['title'])
        channel_title = html.unescape(video['snippet']['channelTitle'])
        video_url = f"https://youtu.be/{video_id}"
        message = f"`{channel_title} - YouTube`\n**{video_title}**\n{video_url}"
        post_to_discord(message)
        new_video_ids.append(video_id)

    # 새로운 동영상 ID를 GIST에 업데이트합니다.
    if new_video_ids:
        update_posted_videos(new_video_ids)

# 메인 함수 실행
def main():
    try:
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    main()
