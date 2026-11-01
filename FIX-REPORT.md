# Endstone Broadcaster schema 9 compatibility fix

Local candidate: **1.1.2rc1**, November 1, 2026. Based on main commit `96941d6e316801ea8853d3847cbacc11bd1e4979`.

## Cause and fix

The wrapper accepted only config versions 0–7 while its unrestricted updater downloaded upstream build 162, which migrates config.yml to schema 9. The wrapper then rejected the migrated file.

This candidate supports known build/schema pairs: 160/7, 161/8 and 162/9. It separates legacy (<7) endpoint migration from newer schema upgrades, preserving custom schema 7/8 backend addresses, ports and query/fallback choices. Explicit IPv6 settings are preserved; schema 8+ defaults IPv6 false; schema 9 removes obsolete web-query-fallback. Config backups use the target schema suffix and do not overwrite existing backups. Repeated synchronization is idempotent.

Downloads are bounded to reviewed builds through 162. A future latest release falls back to official release 162 rather than silently introducing an unknown schema. Older cached known builds receive their matching schema; newer configs are never downgraded. Unknown cached builds are refused, and an installed newer build is not automatically downgraded. An available build 162 upgrade repairs a schema-9 config paired with an older cached build.

Updates validate the proposed config before stopping the helper. JAR, version marker and config snapshots are restored together on ordinary installation failures. If rollback fails, recovery copies are retained, an error identifies their directory, and restarts/updates are blocked, including a newly created manager. This is caught-error recovery, not a power-loss transactional guarantee.

## Verification

- Linux, Python 3.12: 67 tests passed against source.
- Same 67 tests passed against the extracted final wheel payload.
- Independent review reran 67 tests, Ruff and git diff whitespace checks successfully.
- Ruff lint passed; wheel build passed; ZIP integrity passed; every packaged Python module matched source bytes.
- Tests cover legacy migration, schema 7/8/9 preferences, cached builds, future schema/build handling, repeated startup config, invalid config/downloads, updater/stop behavior, rollback and rollback failure, existing signaling adapter, Java selection and process lifecycle.
- Live Endstone/JVM/Xbox authentication, actual players, Windows and physical server runtime were **not tested**. Tests mock external downloads/processes; no upstream JAR was executed.
- Cached JAR identity still trusts the paired jar_version.txt (existing behavior). It is not an embedded-version or cryptographic attestation of arbitrary cached files. Do not replace the JAR without its matching marker.

## Install and rollback

1. Back up the old wheel and the **complete plugin data folder** before changing anything.
2. Stop Endstone during an operator-approved maintenance window.
3. Remove the old broadcaster wheel from plugins/ and install the supplied 1.1.2rc1 wheel. Do not leave two broadcaster versions active.
4. Preserve the plugin data folder, especially config.yml and account cache. Do not manually reset config-version to 7.
5. Start Endstone. When GitHub is reachable, the helper selects reviewed build 162. Verify its console reports build 162, config-version remains 9, and the intended remote address/port remain unchanged. Verify Xbox friend visibility and an actual player join.
6. Rollback requires stopping Endstone and restoring the old wheel **plus its matching full data-folder backup**. Old wrapper 1.1.1 cannot read schema 9; restoring only that wheel is insufficient.
7. If an incomplete rollback is reported, leave the helper stopped, inspect the retained broadcaster-update-* directory, restore its matching files with the server stopped, then move that recovery directory outside the plugin data folder before restarting. Retain a backup while investigating the underlying disk/access error.

No GitHub push, tag, release, production deployment, server restart or credential change was performed. This is a locally built review candidate.

## Upstream evidence

- Schema 7: https://github.com/MCXboxBroadcast/Broadcaster/commit/3600197739ac509c1301e8cbcbfc87581bbbc88e
- Schema 8: https://github.com/MCXboxBroadcast/Broadcaster/commit/4f82a01227631dea51bdddd1405d62334e62fd51
- Schema 9: https://github.com/MCXboxBroadcast/Broadcaster/commit/26a864760d51f2d615bc11b18b7b706a683d9539
- Build 162: https://github.com/MCXboxBroadcast/Broadcaster/releases/tag/162
