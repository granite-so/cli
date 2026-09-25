# Granite CLI

Deploy and operate applications on [Granite](https://granite.so) from the terminal — a declarative
YAML manifest, managed Postgres/MySQL/Redis, S3 storage, live logs, shells into running pods and
port forwarding, all scriptable and all with `--json`.

```bash
novps apps apply my-api -f novps.yaml --wait
```

> **Naming.** The platform is **Granite** (dashboard: [dashboard.granite.so](https://dashboard.granite.so)).
> The CLI binary is still `novps`, the manifest file is `novps.yaml`, and personal access tokens
> start with `nvps_`.

**Contents** · [Quick start](#quick-start) · [Deploy with Claude Code](#deploy-with-claude-code) ·
[Installation](#installation) · [Authentication](#authentication) · [Deploying applications](#deploying-applications) ·
[Command reference](#command-reference) · [Using the CLI from scripts and agents](#using-the-cli-from-scripts-and-agents) ·
[Configuration](#configuration)

---

## Quick start

From a repository with a `Dockerfile` to a public URL:

```bash
# 1. Install
curl https://cli.granite.so | sh

# 2. Authenticate with a Personal Access Token from the Granite dashboard
novps auth login

# 3. Describe the app
cat > novps.yaml <<'YAML'
envs:
  - key: LOG_LEVEL
    value: info

resources:
  - name: api
    type: web-app
    source_type: github
    source:
      type: github
      repository: owner/repo
      branch: main
      source_dir: ./
      build_command: docker build .
    config:
      port: "8080"
      restart_policy: always
    replicas:
      type: sm
      count: 1
YAML

# 4. Deploy and wait for the URL
novps apps apply my-api -f novps.yaml --wait
```

`--wait` polls the deployment and prints the endpoints when it succeeds:

```
Application created: my-api (0f3c…)
  - api: created
Deployment: 8a21…
deployment status: building
deployment status: deploying
Deployment succeeded.

Endpoints:
  api (web-app):
    public:  https://my-api-api.granite.app
    private: api.my-api.svc.cluster.local
```

Already have an app in the dashboard? Export it and take it from there:

```bash
novps apps export my-api -o novps.yaml
```

---

## Deploy with Claude Code

There is an official Claude Code skill that drives this CLI:
**[granite-so/claude-skill](https://github.com/granite-so/claude-skill)**.

Say *"deploy this to Granite"* or *"tail the prod logs"* and the agent inspects the repository
(git remotes, CI workflows, compose files, framework layout), proposes a `novps.yaml`, resolves
registry credentials, and runs the right commands.

```bash
# Project-level skill
mkdir -p .claude/skills
git clone https://github.com/granite-so/claude-skill .claude/skills/novps

# Or user-level, for all projects
mkdir -p ~/.claude/skills
git clone https://github.com/granite-so/claude-skill ~/.claude/skills/novps
```

The install directory must be named `novps` — Claude Code uses the directory name as the skill name.
Requires this CLI at **v0.3.0 or later**. The skill works in Claude Code and in any Claude Agent SDK
harness that loads skills.

If you drive the CLI from your own agent instead, see
[Using the CLI from scripts and agents](#using-the-cli-from-scripts-and-agents).

---

## Installation

```bash
curl https://cli.granite.so | sh
```

This downloads the binary for your platform and installs it to `~/.local/bin` or `/usr/local/bin`.
To choose the directory:

```bash
NOVPS_INSTALL_DIR=~/bin curl https://cli.granite.so | sh
```

### From source

Requires Python 3.12+.

```bash
pip install .          # or: pip install -e .  for development
```

### Supported platforms

| OS | Architecture | Binary |
|----|-------------|--------|
| Linux | x86_64 | `novps-linux-x86_64` |
| Linux | arm64 | `novps-linux-arm64` |
| macOS | x86_64 | `novps-darwin-x86_64` |
| macOS | arm64 (Apple Silicon) | `novps-darwin-arm64` |

Check what you have with `novps version`.

---

## Authentication

Create a Personal Access Token in the [Granite web dashboard](https://dashboard.granite.so), then:

```bash
novps auth login
# Enter your token when prompted (nvps_...)

novps auth login --token "$GRANITE_TOKEN"   # non-interactive, for CI
novps auth status                            # show current auth status
novps auth logout                            # remove saved token
```

The token is validated with a test API call before it is saved to `~/.novps/config.json`.

### Multi-project setup

Every command accepts `--project` (`-p`) to work with several projects side by side:

```bash
novps auth login --project=staging
novps apps list --project=staging
```

---

## Deploying applications

### The manifest

`novps.yaml` describes one application. The application **name is the CLI argument**, not a field in
the file — the same manifest can create `my-api-staging` and `my-api-prod`.

```yaml
envs:                          # app-level env, merged into every resource
  - key: LOG_LEVEL
    value: info
  - key: DB_URL
    value: ${DB_URL}           # substituted locally from the shell env or --env-file

resources:
  - name: api                  # unique within the app; matches resources across applies
    type: web-app              # web-app | worker | cron-job
    source_type: docker        # docker | github
    source:
      type: docker
      name: ghcr.io/owner/repo
      tag: ${IMAGE_TAG}
      credentials: ''          # see "Registry credentials" below
    config:
      port: "8080"             # web-app: HTTP port the app listens on
      restart_policy: always   # always | on-failure | never
    replicas:
      type: sm                 # xs | sm | md | lg | xl (plan-limited)
      count: 2
    envs: []                   # resource-level env; overrides app-level on conflict
    volumes:
      - path: /var/lib/app     # at most one volume per resource
```

`config` fields by resource type:

| Field | Applies to | Notes |
|---|---|---|
| `port` | web-app | HTTP port, as a string |
| `command` | worker, cron-job | Startup command override |
| `schedule` | cron-job | Cron expression, e.g. `*/5 * * * *` |
| `allow_overlapping` | cron-job | Whether runs may overlap |
| `internal_ports` | any | Extra exposed ports; also the allow-list for `port-forward` |
| `restart_policy` | any | `always` (default), `on-failure`, `never` |

Volumes are positional: **omitting** the `volumes` key leaves an existing volume untouched, while
`volumes: []` **detaches** it. Resizing and deleting volumes is dashboard-only.

Managed databases are not declared in the manifest — create them with `novps databases create` and
wire the connection string in through `envs` and `--env-file`.

### `${VAR}` substitution

Values like `${DB_URL}` are resolved by the CLI before the manifest is sent, so secrets stay out of
the committed file. Sources, later wins:

1. the file passed to `--env-file`
2. the shell environment

An undefined variable is an error, not an empty string. Commit `novps.yaml`, gitignore `.env`.

```bash
IMAGE_TAG=$(git rev-parse --short HEAD) novps apps apply my-api -f novps.yaml --wait
novps apps apply my-api -f novps.yaml --env-file .env.production --wait
```

Note that `${VAR}` is substituted **locally**. A `$VAR` reference without braces is left alone and
resolved by Granite from the app's own environment variables at deploy time.

### Docker mode vs GitHub mode

| | `source_type: docker` | `source_type: github` |
|---|---|---|
| Who builds | your CI | Granite, on each deploy |
| Needs | a registry the image is pushed to | the [Granite GitHub App](https://github.com/apps/granite-so/installations/new) installed on the repo |
| Deploy trigger | `apps apply` / `resources set-image` + `deploy` | a push to `branch` |
| Monorepos | one image per service, independent deploys | a push rebuilds **every** resource on that repo+branch — `source_dir` scopes the build context, not the trigger |

If your CI already builds and pushes an image, prefer Docker mode — GitHub mode would rebuild it a
second time. Check the GitHub integration with `novps github list`; an empty list means it is not
set up, and the CLI cannot fix that (dashboard and GitHub only).

### Applying

```bash
novps apps apply my-api -f novps.yaml                  # create or update
novps apps apply my-api -f novps.yaml --wait           # ...and wait for the deployment
novps apps apply my-api -f novps.yaml --dry-run        # parse and validate only, no API call
novps apps apply my-api -f novps.yaml --prune          # delete resources missing from the manifest
novps apps apply my-api -f novps.yaml --env-file .env
novps apps apply my-api -f novps.yaml --wait --json    # machine-readable, incl. endpoints
```

`apply` is idempotent and matches resources by `name`. With `--wait` the command exits non-zero if
the deployment does not reach `success`, which makes it usable as a CI gate directly.

### Shipping a new image

For an app already deployed in Docker mode, a release is two commands:

```bash
novps resources set-image <resource_id> --tag 1.4.2
novps resources deploy <resource_id>
```

### Registry credentials

Private images need `user:password` (or the UUID of credentials already stored for that image).

**The `credentials` field in the manifest is only read when a resource is created.** On later
applies it is ignored — that is deliberate, so a committed file never has to carry a secret. Leave
it as `''` and set credentials through the CLI, reading them from the environment so they stay out
of shell history:

```bash
novps resources set-image <resource_id> --docker-credentials "$DOCKER_USER:$DOCKER_TOKEN"
novps resources update    <resource_id> --tag 1.4.2 --docker-credentials "$DOCKER_USER:$DOCKER_TOKEN"
novps resources set-image <resource_id> --docker-credentials ""   # remove stored credentials
```

`apps export` always writes `credentials: ''` — stored secrets are never returned.

---

## Command reference

### Applications

```bash
novps apps list                                  # List all applications
novps apps resources <app_id>                    # List resources for an app

novps apps apply <app_name> -f novps.yaml        # Create or update from a manifest
novps apps export <app_name> [-o novps.yaml]     # Export as an apply-compatible manifest
novps apps export <app_name> --include-secrets   # Include env values (needs apps.show-secrets)
novps apps deploy <app_id>                       # Trigger a manual deployment
novps apps update <app_id> --name "New name" [--description "..."]
novps apps delete <app_id> [--force]             # Soft delete; prompts to type DELETE
```

### Resources

```bash
novps resources get <resource_id>                # Show resource details
novps resources logs <resource_id>               # View logs
novps resources logs <resource_id> -f            # Follow log output
novps resources logs <resource_id> -n 500        # Last 500 lines
novps resources logs <resource_id> --since 30m --search "error"
novps resources connect <resource_id>            # Interactive shell in the running pod

novps resources deploy <resource_id>             # Trigger a manual deployment
novps resources scale <resource_id> -r sm:2      # Replica size:count
novps resources set-image <resource_id> --image registry.example.com/team/api --tag 1.4.2
novps resources set-env <resource_id> KEY=VALUE OTHER=value      # Merge with existing
novps resources set-env <resource_id> KEY=VALUE --replace        # Replace all env vars
novps resources delete <resource_id> [--force]   # Soft delete; prompts to type DELETE
```

`resources update` is the general form behind `scale`, `set-image` and `set-env`, and can change
several things at once:

```bash
novps resources update <resource_id> \
    --image ghcr.io/owner/repo --tag 1.4.2 \
    --replicas sm:3 --port 8080 --command "python -m app.worker" \
    --schedule "*/5 * * * *" -e LOG_LEVEL=debug
novps resources update <resource_id> --tag 1.4.2 --no-deploy     # Change config, deploy later
```

### Secrets

```bash
novps secrets list <app_id>                    # List secret keys (values masked)
novps secrets list <app_id> --with-values      # Include secret values
novps secrets list <app_id> -r <resource_id>   # Resource-level secrets
novps secrets get <app_id> DATABASE_URL        # Get a single secret value
```

### Databases

```bash
novps databases list                                  # List databases
novps databases get <id>                              # Show details (table)
novps databases get <id> --show-password              # Include password + DATABASE_URL
novps databases get <id> --format env --show-password # Print as DB_HOST=, DATABASE_URL=, etc.
novps databases get <id> --format json

novps databases create --engine postgres --size sm    # engine: postgres|mysql|redis, size: xs..xl
novps databases create --engine postgres --size sm --postgres-version 16 --count 1
novps databases create --engine mysql --size sm --mysql-version 8.0
novps databases create --engine postgres --size sm --wait   # Wait (with spinner) until ready

novps databases resize <id> --size lg [--count 2]     # Upscale only
novps databases delete <id> [--force]                 # Prompts to type DELETE
novps databases allow-apps <id> --app <uuid> --app <uuid>   # Restrict inbound; no --app clears
```

Supported engines are `postgres`, `mysql` and `redis`; node sizes `xs`, `sm`, `md`, `lg`, `xl`;
node count 1–3. `--wait` prints the connection details once the database is ready.

#### Read-only replica (postgres)

```bash
novps databases replica create <db_id> --size sm
novps databases replica resize <db_id> --size md
novps databases replica delete <db_id>
```

#### Backups (postgres)

```bash
novps databases backups list <db_id>
novps databases backups create <db_id>
novps databases backups delete <db_id> <backup_id> [--force]
```

#### Connection pools (postgres)

```bash
novps databases pool list <db_id>
novps databases pool create <db_id> --size 50 --mode transaction --target primary
novps databases pool update <db_id> <pool_id> --size 80 --mode session
novps databases pool delete <db_id> <pool_id> [--force]
```

#### Postgres databases inside an instance

```bash
novps databases pg-db list <db_id>
novps databases pg-db create <db_id> --name analytics
novps databases pg-db delete <db_id> <entry_id> [--force]
```

#### Postgres users inside an instance

```bash
novps databases pg-user list <db_id>                            # passwords hidden
novps databases pg-user list <db_id> --show-password            # passwords in clear
novps databases pg-user create <db_id> --name app_user \
    --grant analytics=ro --grant reporting=all                  # password printed once
novps databases pg-user delete <db_id> <entry_id> [--force]
```

### Registry

```bash
novps registry list               # List registry namespaces
```

### GitHub

```bash
novps github list                 # List GitHub installations linked to this project
```

An empty list means the Granite GitHub App is not installed for the project. Install it at
`https://github.com/apps/granite-so/installations/new` and link the account in the dashboard;
this cannot be done from the CLI.

### Storage

Buckets and keys are referenced by their **unique identifier** (`internal_domain` for buckets,
`internal_name` for keys), not the display name — names are not guaranteed unique within a project.
Run the corresponding `list` command to see identifiers in the first column.

```bash
novps storage list                                    # List S3 buckets (+ origin/CDN endpoints)
novps storage create my-bucket [--region eu]          # Display name; identifier is in the output
novps storage delete <bucket> [--force]               # Prompts to type DELETE
novps storage set-access <bucket> private|public-read
```

#### Files

```bash
novps storage files list <bucket> [--path logs/] [--page-size 100]
novps storage files list <bucket> --all               # Fetch all pages
novps storage files list <bucket> --continuation-token <token>   # Resume pagination

novps storage files upload <bucket> ./data.bin [--key path/data.bin] [--content-type application/octet-stream]
novps storage files download <bucket> path/data.bin [-o ./local.bin] [--duration 600]

novps storage files rename <bucket> old/key.txt new/key.txt
novps storage files delete <bucket> key1 key2 ... [--force]
```

#### Access keys

```bash
novps storage keys list
novps storage keys create prod-key --bucket <bucket-a>:rw --bucket <bucket-b>:ro   # Secret shown once
novps storage keys update <key> [--name new-name] [--bucket <bucket-a>:rw]         # --bucket replaces permissions
novps storage keys update <key> --replace-permissions                              # Clear all permissions
novps storage keys regenerate <key> [--force]                                      # Old secret stops working
novps storage keys delete <key> [--force]
```

### Port forwarding

Databases are not exposed publicly. Forward a port to reach one from your machine:

```bash
novps port-forward database <database_id>                        # Default local port by engine
novps port-forward database <database_id> -l 5433                # Custom local port
novps port-forward resource <resource_id> <remote_port>          # Forward to a resource
novps port-forward resource <resource_id> <remote_port> -l 8080
```

---

## Using the CLI from scripts and agents

Everything below holds across commands, which is what makes the CLI safe to drive from CI or from
an AI coding agent:

- **`--json` on every list and get command**, plus on `apps apply`, `apps deploy`,
  `resources update` and `resources deploy`. With `apply --wait --json` the output includes
  `deployment_status` and the resolved `endpoints`.
- **`--force` skips every typed confirmation.** Destructive commands (`apps delete`,
  `resources delete`, `databases delete`, `storage delete`, `keys regenerate`) otherwise prompt for
  the literal word `DELETE` and abort with a non-zero exit.
- **Non-zero exit on failure**, including `apps apply --wait` when the deployment does not reach
  `success` — so a deploy step fails the pipeline instead of passing silently.
- **`--project` / `-p`** selects the stored token, so one machine can drive several projects.
- **`novps auth login --token "$GRANITE_TOKEN"`** authenticates without a prompt.
- **Secrets stay out of the manifest**: `${VAR}` substitution from `--env-file`, and registry
  credentials set through the CLI rather than the committed YAML.

A minimal CI release step:

```bash
novps auth login --token "$GRANITE_TOKEN"
IMAGE_TAG=$(git rev-parse --short HEAD) \
  novps apps apply my-api -f novps.yaml --wait --json > deploy.json
```

---

## Configuration

| Setting | Source | Default |
|---------|--------|---------|
| Token | `~/.novps/config.json` | — |
| API URL | `NOVPS_API_URL` env var | `https://api.granite.so` |
| WebSocket URL | `NOVPS_WS_URL` env var | `wss://api.granite.so` |
| Install directory | `NOVPS_INSTALL_DIR` env var | `~/.local/bin` or `/usr/local/bin` |

---

## Related

- **[granite-so/claude-skill](https://github.com/granite-so/claude-skill)** — Claude Code skill that
  drives this CLI: discovers the project, writes the manifest, deploys, tails logs
- **[granite.so](https://granite.so)** — the platform
- **[dashboard.granite.so](https://dashboard.granite.so)** — web console, personal access tokens,
  GitHub integration, volumes
- **[docs.granite.so](https://docs.granite.so)** — platform documentation
