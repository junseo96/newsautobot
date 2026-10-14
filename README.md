# Newsautobot

Snapshot of the Newsflow V12 project and connected US grid observatory sources, exported on 2026-10-15 (Asia/Seoul).

## Projects

- `outputs/rss-news-monitor`: incremental industry news collection, editorial review, duplicate guard, Telegram receipts/ACK, and grid bridge.
- `outputs/telegram-forwarder`: Telegram setup, text formatting and verified delivery scripts.
- `integrations/us-grid-observatory`: dashboard application, API endpoints, schema, public research datasets and build tooling.

Current operating policy: `outputs/rss-news-monitor/PROTOCOL.md` and `V12-POLICY.md`. Older version documents are retained for reference, not as current execution instructions.

## Restore and deployment

The news service can run automatically through GitHub Actions using the Docker worker in [`deploy/cloud`](deploy/cloud/README.md). Scheduled runs preserve encrypted operational state between runners, while a separate verification workflow tests the image. GitHub scheduling can be delayed and has gaps between runs; it is not a continuously available server. The dashboard remains a separate application.

Scheduling starts disabled. Import the original operational history and configure Gmail OAuth, model API access, Telegram, DART and dashboard credentials in Actions before activation. Startup verifies the restored databases and historical receipt evidence; it refuses to start with missing state. Missing or failed checkpoints block automatic recovery instead of reverting to older delivery history. The repository does not contain production credentials or operational history.

Read the project README files and `V12-OPERATIONS.md` before installation. Some historical documents and scripts contain machine-specific paths; review these for the new host. Sites deployment configuration and runtime bindings are intentionally not exported and must be provisioned separately.

## Data and security

API keys, protected credential stores, Gmail bodies, operational databases, receipts, logs, build caches and local account configuration are excluded. No full chat transcript is included. Public dashboard datasets already present in the source tree are retained where safe; downloaded binary/raw source files are excluded from this initial source snapshot.

For resuming an existing channel, transfer delivery history and databases through a separate protected backup. Starting from an empty database can lose duplicate protection. Never commit credentials or operational mail data, including encrypted local secrets.

No production files or scheduled tasks are changed by this export.
