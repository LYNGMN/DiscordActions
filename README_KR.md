# Discord Actions

Discord Actions는 다양한 플랫폼에서 정보를 수집하고 디스코드에 자동으로 작성하는 GitHub Actions 프로젝트입니다.

## 현재 지원하는 플랫폼

- **YouTube**: 특정 YouTube 채널의 새 동영상의 알림을 받습니다.
- **Google News**: 대한민국 주요 뉴스, 특정 키워드 뉴스의 알림을 받습니다.

## 지원 예정된 플랫폼

Discord Actions는 다음 플랫폼에 대한 지원을 활발하게 개발 중입니다:

- **RSS**: RSS피드에서 새 콘텐츠 알림을 받습니다.
- **Reddit**: 특정 서브레딧에서 새 게시물 알림을 받습니다.
- **Twitter**: 특정 트위터 계정 또는 특정 해시태그에서 새 트윗 알림을 받습니다.
- **Bluesky**: 특정 블루스카이 계정에서 새 포스트 알림을 받습니다.
- **Mastodon**: 특정 마스토돈 계정에서 새 포스트 알림을 받습니다.
- **Instagram**: 특정 인스타그램 계정에서 새 게시물 알림을 받습니다.
- **Weather Underground**: 원하는 위치에 대한 날씨 예보를 받습니다.

## 사용 방법

1. 이 저장소를 포크합니다.
2. 포크한 저장소의 Secrets에 작동을 원하는 플랫폼에 적합한 환경 변수를 설정합니다.  
(예: 유튜브 사용 시, DISCORD_YOUTUBUE_WEBHOOK, YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID, IS_FIRST_RUN)
3. [`Actions`](https://github.com/LYNGMN/DiscordActions/actions)로 이동하여 사용할 플랫폼의 워크플로우를 클릭합니다.  
(예: [YouTube to Discord Notification](https://github.com/LYNGMN/DiscordActions/actions/workflows/youtube_to_discord.yml))  
4. 제대로 작동하는지 수동으로 `[Run workflow]` 버튼을 눌러 작동하여 확인합니다.  
5. 설정이 완료되었습니다. 설정한 작동시간 (기본값: 30분마다) GitHub Actions 워크플로우가 주기적으로 작동합니다.

## 기여

이 프로젝트에 관심을 가지시고 기여하고 싶다면 다음을 따라주세요.
- 추가 지원이 필요한 플랫폼이 있다면 [`Discussions`](https://github.com/LYNGMN/DiscordActions/discussions)에 작성해주세요. 어떻게 사용하는지 구체적으로 적어주시면 좋습니다.  
- 작동에 오류가 있다면 [`Issues`](https://github.com/LYNGMN/DiscordActions/issues)에 작성해주세요.

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [라이선스 파일](LICENSE)을 참조하세요.
