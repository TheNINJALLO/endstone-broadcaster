# Changelog

## 1.1.1 — 2026-10-27

Fix MCXboxBroadcast build 160 reporting HTTP 404 for older Endstone/BDS NetherNet backends even when their plain status endpoint works.

- Start a loopback HTTP adapter for the helper. When the configured backend rejects a status probe containing query parameters with 404, retry the plain status route and enable compatibility only if it returns valid older NetherNet metadata.
- Preserve modern status queries and refusal responses. Forward SDP offer/answer bytes unchanged and keep HTTPS direct. Stop the adapter with the helper, including failed launches.
- Keep the configured backend address, port, official JAR, and authentication cache intact. No new configuration or public port is required.

Validation: 42 tests cover migration, runtime, lifecycle, modern and legacy signaling routes, and unchanged SDP forwarding. The actual build 160 Java client successfully probed the reported backend through this implementation with its original 26.60 client settings. An authenticated console join still needs to be checked after installing the wheel.

Upgrade: replace the broadcaster wheel with v1.1.1 and restart Endstone. Keep the existing plugin data folder and backend endpoint. Endweave remains responsible for game protocol translation.

## 1.1.0 — 2026-10-27

Update the wrapper for Minecraft 26.60 and MCXboxBroadcast Standalone build 160's NetherNet HTTP relay.

- Require Java 21 or newer. Detect the installed Java version and provision a portable Temurin 21 JRE when PATH or the cached Java 17 runtime is too old.
- Migrate old YAML to config schema 7 with a one-time original-file backup. Use the local backend signaling endpoint, enable NetherNet queries with metadata fallback, rename auto-follow to auto-friend, and remove the old transfer address and ICE port range.
- Preserve current-schema custom endpoints, query settings, webhooks, expiry settings, and authentication cache. Safely serialize server/world names.
- Validate downloaded JARs and release SHA-256 digests when available; reject builds older than 160 for this release.
- Run downloads and startup outside Endstone's main thread. Serialize process changes and prevent an in-flight download from starting a helper after plugin shutdown.
- Keep healthy helpers alive so upstream session rotation works. Restart exited helpers and wait for shutdown before replacing the JAR.
- Test migration and helper lifecycle on Windows/Linux and Python 3.11/3.14 before releasing a wheel.

### Upgrade

Replace the wheel and restart Endstone. The first startup migrates config.yml and saves config.yml.pre-v7.bak. Legacy public transfer destinations are replaced with the local backend address; review remote-address and remote-port if using a separate container/backend.

The backend must support NetherNet and the connecting client's game protocol. Configure transport=nethernet and the backend's public UDP mappings in server.properties or your host panel. This release does not upgrade the Endstone server binary or provide game protocol translation.

### Validation scope

The 31 automated tests cover the wrapper's migration, runtime, update, and lifecycle behavior. Local verification also provisioned Temurin 21, downloaded and verified the real build 160 JAR, confirmed protocol 2225 at runtime, and loaded the generated YAML with upstream's Java ConfigLoader. An authenticated Xbox/console join still requires validation on a running server with its actual network configuration.
