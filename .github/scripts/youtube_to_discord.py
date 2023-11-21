import os
import requests
import html
from googleapiclient.discovery import build
from datetime import datetime, timedelta

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

    # 최초 실행일 경우 모든 동영상을 가져옵니다.
    if IS_FIRST_RUN == '1':
        video_list = []
        for video in reversed(videos['items']):  # 오래된 순서로 게시
            video_title = html.unescape(video['snippet']['title'])
            channel_title = html.unescape(video['snippet']['channelTitle'])
            video_id = video['id']['videoId']
            video_url = f"https://youtu.be/{video_id}"
            message = f"`{channel_title} - YouTube`\n**{video_title}**\n{video_url}"
            post_to_discord(message)
            video_list.append(f"{channel_title}: {video_title}")

        # 최초 실행일 경우 가져온 동영상 목록을 한 번에 Discord에 게시합니다.
        summary_message = "최초 실행: 가져온 YouTube 동영상 목록\n\n" + "\n".join(video_list)
        post_to_discord(summary_message)
    else:
        # 최초 실행이 아닐 경우, 지난 30분 이내에 업로드된 동영상만 필터링합니다.
        current_time = datetime.utcnow()
        filtered_videos = [video for video in videos['items'] if (
            current_time - datetime.strptime(video['snippet']['publishedAt'], '%Y-%m-%dT%H:%M:%SZ')) <= timedelta(minutes=30)]


        if filtered_videos:
            for video in filtered_videos:  # 오래된 순서로 게시
                video_title = html.unescape(video['snippet']['title'])
                channel_title = html.unescape(video['snippet']['channelTitle'])
                video_id = video['id']['videoId']
                video_url = f"https://youtu.be/{video_id}"
                message = f"`{channel_title} - YouTube`\n**{video_title}**\n{video_url}"
                post_to_discord(message)
        else:
            print("30분 이내에 업로드된 동영상이 없습니다.")

# 메인 함수 실행
def main():
    try:
        fetch_and_post_videos()
    except Exception as e:
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    main()
