# Discord Actions

Discord Actions is a GitHub Actions project that collects information from various platforms and automatically posts it on Discord.

## Currently Supported Platforms

- **YouTube**: Receive notifications of new videos from specific YouTube channels.
- **Google News**: Receive notifications of topic news and specific keyword news.

## Upcoming Platform Support

Discord Actions is actively developing support for the following platforms:

- **RSS**: Receive notifications of new content from RSS feeds.
- **Reddit**: Receive notifications of new posts from specific subreddits.
- **Twitter**: Receive notifications of new tweets from specific Twitter accounts or specific hashtags.
- **Bluesky**: Receive notifications of new posts from specific Bluesky accounts.
- **Mastodon**: Receive notifications of new posts from specific Mastodon accounts.
- **Instagram**: Receive notifications of new posts from specific Instagram accounts.
- **Weather Underground**: Receive weather forecasts for your chosen location.

## How to Use

1. Fork [this repository](https://github.com/LYNGMN/DiscordActions/fork) or Use [this template](https://github.com/new?template_name=DiscordActions&template_owner=LYNGMN).
2. Access the settings of the forked repository, go to `Secrets and variables` > [`Actions`](https://github.com/LYNGMN/DiscordActions/settings/secrets/actions).  
Click the [`New repository secret`](https://github.com/LYNGMN/DiscordActions/settings/secrets/actions/new) button to configure environment variables suitable for the platform you want to use.  
   (e.g., For YouTube to Discord use, set DISCORD_YOUTUBE_WEBHOOK, YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID, IS_FIRST_RUN)
4. Go to [`Actions`](https://github.com/LYNGMN/DiscordActions/actions) and click on the workflow for the platform you want to use.  
   (e.g., [YouTube to Discord Notification](https://github.com/LYNGMN/DiscordActions/actions/workflows/youtube_to_discord.yml))  
6. Manually press the `[Run workflow]` button to check if it's working properly.
7. The setup is complete. The GitHub Actions workflow will operate periodically at the set time  
   (default: every 30 minutes).

## Contributing

If you are interested in contributing to this project, please follow these steps:
- If there is a platform that needs additional support, please post it in [`Discussions`](https://github.com/LYNGMN/DiscordActions/discussions). It's helpful if you can be specific about how it's used.
- If there is an issue with the operation, please post it in [`Issues`](https://github.com/LYNGMN/DiscordActions/issues).

## License

This project is distributed under the MIT License. For more details, refer to the [license file](LICENSE).

*Read this in other languages: [한국어](README_KR.md)*
