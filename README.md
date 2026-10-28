<!-- endstone-professional-header:start -->
<p align="center">
  <img src="docs/assets/banner.svg" width="100%" alt="Endstone Broadcaster &mdash; A wrapper plugin for MCXboxBroadcast to broadcast your server to Xbox Live">
</p>

<p align="center">
  <a href="https://github.com/TheNINJALLO/endstone-broadcaster/actions/workflows/wheel-release.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/TheNINJALLO/endstone-broadcaster/wheel-release.yml?branch=main&amp;style=for-the-badge&amp;logo=githubactions&amp;logoColor=white&amp;label=Build"></a>
  <a href="https://github.com/TheNINJALLO/endstone-broadcaster/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/TheNINJALLO/endstone-broadcaster?display_name=tag&amp;style=for-the-badge&amp;label=Release"></a>
</p>

<p align="center">
  <img alt="Endstone 0.11.14" src="https://img.shields.io/badge/Endstone-0.11.14-52b7a8?style=flat-square">
  <img alt="API 0.11" src="https://img.shields.io/badge/API-0.11-63b8ff?style=flat-square">
  <img alt="Minecraft 26.60" src="https://img.shields.io/badge/Minecraft-26.60-8b7dff?style=flat-square">
  <img alt="Python >=3.11" src="https://img.shields.io/badge/Python-%3E=3.11-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
</p>

<p align="center">
  <strong>A wrapper plugin for MCXboxBroadcast to broadcast your server to Xbox Live.</strong>
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> &bull;
  <a href="#how-to-use">How to use</a> &bull;
  <a href="#commands-and-permissions">Commands</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="https://github.com/TheNINJALLO/endstone-broadcaster/releases">Releases</a>
</p>

## Overview

Endstone Broadcaster runs MCXboxBroadcast Standalone beside your Bedrock server so friends of the authenticated Xbox account can discover and join it. Version **1.1.0** targets Minecraft **26.60**, MCXboxBroadcast **build 160 or newer**, and its new NetherNet relay.

## What it does

- Provisions Java **21** when the Java on PATH or a cached runtime is too old.
- Downloads the latest Standalone JAR at startup and checks again every 12 hours. Downloads are checked before replacing the installed JAR, including SHA-256 when GitHub supplies a digest.
- Migrates old configuration to upstream schema **7**, keeping a copy at `config.yml.pre-v7.bak`.
- Queries the backend over NetherNet for live session details, with configured metadata as a fallback.
- Passes authentication and status messages to the Endstone console.
- Runs setup outside the server thread and restarts the helper if it exits. Healthy helpers keep running; upstream handles session rotation.

## Compatibility

| Component | Requirement |
|---|---|
| Endstone API | `0.11` (`endstone>=0.11.9,<0.12`; current stable release: `0.11.14`) |
| Minecraft / advertised Xbox session | **26.60**, protocol **2225** in upstream build 160 |
| Backend | NetherNet HTTP signaling and support for the connecting client's game protocol |
| MCXboxBroadcast Standalone | **160+**; downloaded automatically |
| Java | **21+**; portable Temurin 21 JRE installed if needed |
| Python | **3.11+**; automatic tar extraction on Linux/macOS needs **3.11.8+** |
| Plugin release | **v1.1.0** |

Updating this wrapper updates the broadcaster, not the Endstone server binary or its game protocol. Endstone 0.11.14 is paired with BDS 1.26.52.3; use a server release or a protocol translator that accepts 26.60 clients as well as enabling NetherNet. Check the [Endstone releases](https://github.com/EndstoneMC/endstone/releases) and your translator's compatibility before upgrading the server.

## Install

Download the release wheel:

```bash
gh release download v1.1.0 --repo TheNINJALLO/endstone-broadcaster --pattern "*.whl"
```

1. Stop Endstone and replace the old broadcaster wheel in `plugins/` with the new wheel.
2. Ensure the backend uses `transport=nethernet` in `server.properties`. Restart the backend after changing its transport.
3. Start Endstone. Setup downloads need access to GitHub and, if necessary, Adoptium. Authentication and broadcasting need access to Microsoft/Xbox services.
4. Follow the Microsoft sign-in URL and device code printed in the console. Existing cached accounts are reused.
5. Add the authenticated broadcaster account as an Xbox friend, then join its Minecraft session.

The plugin data folder contains `config.yml`, `endstone-broadcaster.jar`, `jar_version.txt`, the optional `jre-21/` runtime, and upstream's `cache/`. Keep this folder when upgrading to retain authentication and player history.

## How NetherNet works in 26.60

[Upstream build 160](https://github.com/MCXboxBroadcast/Broadcaster/releases/tag/160) removes the old transfer proxy. It relays Xbox session negotiation to the backend's HTTP signaling endpoint, gathers the client's ICE candidates, and sends the backend's answer back to the client. Game traffic then flows directly between the client and backend over WebRTC.

`session.remote-address` and `session.remote-port` identify the backend **as reached by the helper**. A helper running beside Endstone normally uses `127.0.0.1` and the server port. A specific `server-ip` binding is used when present; wildcard bindings are translated to loopback. Public IP lookup is no longer needed.

The backend must return a valid response from `GET /v1/join` and accept the negotiated WebRTC connection from external players. The helper needs TCP access to the signaling endpoint; players need access to the backend's configured UDP gameplay ports. Configure the backend's public ICE candidates and any NAT/port mappings in the backend or hosting panel. The wrapper does not configure these mappings.

For BDS, `server-udp-ports` belongs in `server.properties`. It is separate from the broadcaster's removed `ice-port-range` option. Merely seeing a session in the friends list does not verify external UDP reachability. See the [Mojang NetherNet guide](https://mojang.github.io/bedrock-protocol-docs/guides/nether-net-onboarding-guide/) and [Cloudburst/Geyser transport explanation](https://opencollaboration.dev/articles/nethernet).

## Configuration

The generated `config.yml` uses upstream schema 7. This is the core session section:

```yaml
session:
  remote-address: 127.0.0.1
  remote-port: '19132'
  update-interval: 30
  query-server: true
  web-query-fallback: false
  config-fallback: true
  hide-old-sessions: true
  session-info:
    host-name: Endstone Server
    world-name: World
    game-mode: Survival
    players: 0
    max-players: 20
friend-sync:
  update-interval: 60
  auto-friend: true
  initial-invite: true
  expiry:
    enabled: true
    days: 15
    check: 1800
notifications:
  enabled: false
debug-mode: false
suppress-session-update-message: true
config-version: 7
```

During an upgrade from an older schema:

- `session-info.ip` and `port` are removed. The old public transfer destination is replaced with the local backend signaling endpoint.
- `query-server` and `config-fallback` are enabled so the helper uses live backend metadata and tolerates a backend still starting.
- `auto-follow` becomes `auto-friend`; `auto-unfollow` and `ice-port-range` are removed.
- Notification settings, expiry rules, debug choices, and other custom values are preserved. YAML formatting and comments are normalized; the original file is backed up before migration.

After migration, explicit schema 7 backend addresses, ports, query choices, and session rotation settings are retained. The host and world fallback names still follow `server-name` and `level-name` from `server.properties`. New configs also use its game mode and maximum player count as fallbacks. Stop Endstone before editing the file and start it again afterward.

If the helper runs in a different container/network namespace, set the schema 7 `remote-address` and `remote-port` to the address reachable from that container. Upstream also accepts `auto` for loopback and port 19132 in Standalone mode. Session and friend-sync update intervals must each be at least 20 seconds.

Malformed YAML, invalid endpoints/intervals, and future schema versions stop helper startup with an error instead of overwriting the file.

## Commands and permissions

There are no Endstone commands or permissions. The helper starts and stops with the plugin. Authentication and errors appear in the server console.

## Development and releases

```bash
python -m pip install pytest PyYAML ruff build
python -m ruff check src tests
python -m pytest -q
python -m build --wheel
```

[CI](.github/workflows/wheel-release.yml) runs the migration, Java selection, download validation, and process lifecycle tests on Windows and Linux with Python 3.11 and 3.14 before building the wheel. A `v*` tag publishes the wheel to its GitHub release. See [the changelog](CHANGELOG.md) for upgrade details.

Runtime credentials, account caches, logs, and server data must stay outside source control.
<!-- endstone-professional-header:end -->
