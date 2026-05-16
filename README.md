# Endstone Broadcaster

A Python wrapper plugin for Endstone that bridges your Bedrock server to Xbox Live using the `MCXboxBroadcast` standalone application. This plugin completely automates the installation, configuration, and lifecycle of the Broadcaster jar, making it totally seamless to deploy on both local Windows machines and Linux Pterodactyl panels.

## Features

- **Universal JRE Provisioning**: Automatically detects if your system (Windows/Linux/macOS, x64/ARM) lacks a Java installation (common in Pterodactyl Docker containers) and downloads a portable OpenJDK 17 Eclipse Temurin JRE just for the plugin to use!
- **Zero-Touch Configuration**: Automatically rips your `server-name`, `level-name`, and `server-port` right out of your root `server.properties` file.
- **Dynamic IP Resolution**: Auto-detects your server's public IPv4 address via `api.ipify.org` so Xbox players connect to the right IP.
- **Console Passthrough**: Securely intercepts the Java output and pipes it directly into your beautiful Endstone server console. It neatly boxes the Microsoft Device Auth URLs so you never miss a login prompt.

## Setup Instructions

1. **Download the Plugin**:
   Head to the [Releases](https://github.com/TheN1NJ4LL0/endstone-broadcaster/releases) page and download the latest `.whl` file.

2. **Install to Endstone**:
   Upload the `.whl` to your server and run:
   ```bash
   pip install endstone_broadcaster-1.0.3-py3-none-any.whl
   ```

3. **Authentication**:
   Start your server. Keep an eye on your console. The plugin will print a Microsoft authentication link and a device code.
   - Go to the provided URL (usually `https://microsoft.com/link`) on any device.
   - Enter the code shown in the console.
   - Login with the Microsoft/Xbox account you want to use as the "bot" account.

4. **Add the Bot as a Friend**:
   On your actual Xbox account, send a friend request to the bot account. The bot will automatically accept it. 
   When the server is online, the bot will show up on your Xbox friends list playing "Minecraft". Join their session to instantly connect to your server!

## Configuration

If you want to manually modify the Broadcaster config (e.g., adding Discord/Slack webhooks or tuning the friend-expiration rules), you can find the generated configuration at:
`plugins/broadcaster/config.yml`

*Note: The plugin will always force-sync your `host-name`, `world-name`, `ip`, and `port` to match your active Endstone server properties every time the server boots, ensuring your friends can always connect!*
