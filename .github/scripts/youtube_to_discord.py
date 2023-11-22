import os
import requests
<<<<<<< HEAD
import datetime
import time
import html
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from github import Github  # PyGithub 라이브러리 추가
=======
from googleapiclient.discovery import build
from datetime import datetime, timedelta
>>>>>>> 8912564e4860cfd32792d2016546dff99e604559

# 환경 변수 설정
# YouTube API, Discord 웹훅 URL, YouTube 채널 ID, GitHub Gist 정보를 불러옵니다.
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_YOUTUBE_WEBHOOK')
<<<<<<< HEAD
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')  # GIST 관리를 위한 GitHub 토큰
GIST_ID = os.getenv('GIST_ID')  # 동영상 ID를 저장할 GIST ID
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', '0')

# YouTube Data API와 GitHub를 초기화합니다.
=======
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
GIST_ID = os.getenv('GIST_ID_YOUTUBE')
GIST_TOKEN = os.getenv('GIST_TOKEN')
IS_FIRST_RUN = os.getenv('IS_FIRST_RUN', '0')  # 기본값은 '0'

# YouTube API 클라이언트 초기화
>>>>>>> 8912564e4860cfd32792d2016546dff99e604559
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

# GitHub Gist에서 게시된 video_id 목록을 가져오는 함수
def get_posted_video_ids():
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    response = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
    if response.status_code != 200:
        print("Gist를 가져오는 데 실패했습니다.")
        return []
    return response.json()['files'].get('posted_videos.txt', {}).get('content', '').split('\n')

# video_id를 Gist에 추가하는 함수
def update_gist(video_id):
    headers = {"Authorization": f"token {GIST_TOKEN}"}
    content = "\n".join(get_posted_video_ids() + [video_id])
    data = {"files": {"posted_videos.txt": {"content": content}}}
    response = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=data)
    if response.status_code != 200:
        print("Gist를 업데이트하는 데 실패했습니다.")

# YouTube 동영상을 가져오고 Discord에 게시하는 함수
def fetch_and_post_videos():
    posted_ids = get_posted_video_ids()
    now = datetime.utcnow()
    max_results = 15 if IS_FIRST_RUN == '1' else 30
    posted_video_ids = get_posted_videos() if IS_FIRST_RUN != '1' else []

<<<<<<< HEAD
    # YouTube에서 동영상을 가져옵니다.
=======
    # YouTube API를 사용하여 동영상을 가져옵니다.
    # 최초 실행 시 15개, 그렇지 않을 경우 30개의 동영상을 가져옵니다.
>>>>>>> 8912564e4860cfd32792d2016546dff99e604559
    videos = youtube.search().list(
        channelId=YOUTUBE_CHANNEL_ID,
        order='date',
        type='video',
        part='snippet',
        maxResults=max_results
    ).execute()

<<<<<<< HEAD
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
=======
    for item in videos.get('items', []):
        video_id = item['id']['videoId']
        video_published_at = datetime.strptime(item['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ')

        # 최초 실행이 아니고 1시간 이내에 업로드된 영상만 확인합니다.
        if IS_FIRST_RUN == '0' and (now - video_published_at) > timedelta(hours=1):
            continue

        # 새로운 동영상을 Discord에 게시하고 Gist에 video_id를 추가합니다.
        if video_id not in posted_ids:
            video_title = item['snippet']['title']
            video_url = f"https://youtu.be/{video_id}"
            message = f"New Video Posted: {video_title}\n{video_url}"
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
            update_gist(video_id)
            print(f"Posted and saved video: {video_title}")

# 메인 함수
>>>>>>> 8912564e4860cfd32792d2016546dff99e604559
def main():
    try:
        fetch_and_post_videos()
    except Exception as e:
        print(f"Error: {e}")

# Python 스크립트가 직접 실행될 때만 main 함수를 실행합니다.
if __name__ == "__main__":
    main()
