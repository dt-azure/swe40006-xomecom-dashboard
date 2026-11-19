# Contributing

How we work in this repository. Read this before your first pull request.

## Repository layout

```
.
├── dashboard/              Streamlit dashboard (reads schema gold)          -> image xom-dashboard
├── data_pipeline/          Kafka, raw API, consumer, poller, dbt runner     -> image xom-pipeline
│   ├── Dockerfile          The pipeline image
│   ├── docker-compose.yml  Pipeline-only local stack (see data_pipeline/README.md)
│   └── tests/              Pipeline tests (run from data_pipeline/)
├── dashboard_server/       Gold snapshot tools for dashboard development
├── tests/dashboard/        Dashboard tests (run from the repo root)
├── deploy/
│   ├── dashboard.Dockerfile  The dashboard image (built from the repo root)
│   ├── compose.yml           What runs on the servers, in /opt/xom
│   ├── compose.ci.yml        Adds a local PostgreSQL for local runs and CI
│   ├── deploy.sh             Runs on a server during a deploy
│   └── server.env.example    What /opt/xom/.env on each server must contain
├── scripts/smoke_test.sh   Is the stack up? Used by CI and after each deploy
├── docker-compose.yml      Full stack locally: deploy/compose.yml + deploy/compose.ci.yml
└── .github/workflows/      ci.yml (test, build, deploy) and deploy.yml (one deploy)
```

Rules:

- Put code in the folder of your workstream. If something is shared, discuss it in the PR.
- Each image has its own dependencies: `dashboard/requirements.txt` and
  `data_pipeline/requirements.txt`. Add a package in the file of the component that uses it.
- Dashboard tests go in `tests/dashboard/`; pipeline tests in `data_pipeline/tests/`.
- Never commit data dumps, CSV snapshots, or `.env` files.

## One-time setup

You need Python 3.13, Git, and Docker. Create virtual environments inside the repository as
`.venv` (gitignored). The examples use [uv](https://docs.astral.sh/uv/); plain `python -m venv`
and `pip` work too.

```bash
git clone <repo-url>
cd <repo>

# Dashboard and repository tools (repo root)
uv venv                              # reads .python-version, so you get 3.13
uv pip install -r requirements-dev.txt
uv run pre-commit install            # lint and a secret scan on every commit

# Pipeline (its own environment, in data_pipeline/)
cd data_pipeline
uv venv
uv pip install -r requirements-dev.txt
```

uv environments have no `pip` inside them, so use `uv pip ...`. Prefix commands with `uv run`
or activate the venv first (Windows PowerShell: `.venv\Scripts\Activate.ps1`).

## Day-to-day commands

```bash
# From the repo root
uv run ruff check --fix .            # lint and auto-fix (covers data_pipeline/ too)
uv run ruff format .                 # format
uv run pytest                        # dashboard tests

# From data_pipeline/ (needs DATABASE_URL pointing at a PostgreSQL you can create databases on)
uv run pytest                        # pipeline tests
```

Run the whole stack in Docker, the same way CI does:

```bash
docker compose up -d --build
bash scripts/smoke_test.sh --api http://localhost:5000 --dashboard http://localhost:8501
docker compose down -v
```

The local databases start empty; the dashboard then shows that Gold has no data. To load
real data, follow `data_pipeline/README.md`.

## Branches and pull requests

- `main` is protected: every change goes through a PR with one approving review and green checks.
- Merging to `main` deploys to the test server, then to production after approval, so only
  merge what you would be happy to demo.
- Branch names: `<type>/<short-description>`, for example `feat/orders-endpoint`,
  `fix/null-delivery-date`, `ci/deploy-workflow`.
- Keep PRs small. Use **Squash and merge**.

Commit messages: short, imperative, with a type prefix (`feat:`, `fix:`, `test:`, `ci:`, `docs:`).

## What CI checks

Every pull request to `main` runs `.github/workflows/ci.yml`. A PR can only be merged when
all five checks are green:

| Check | What it does | Fix locally with |
| --- | --- | --- |
| Lint | `ruff check` and `ruff format --check` over the whole repo | `uv run ruff check --fix .` and `uv run ruff format .` |
| Secret scan | gitleaks over the whole git history | Remove the secret, rotate it, tell the team |
| Dashboard tests | `pytest` from the repo root | `uv run pytest` |
| Pipeline tests | `pytest` in `data_pipeline/` with a real PostgreSQL | `uv run pytest` in `data_pipeline/` |
| Build and smoke test | Builds both images, starts the full stack, checks the API and dashboard answer and every service stays up | The Docker commands above |

## Deployment

After a merge to `main`, the same workflow:

1. pushes both images to GitHub Container Registry as `ghcr.io/<owner>/xom-dashboard` and
   `ghcr.io/<owner>/xom-pipeline`, tagged `sha-<commit>` and `latest`;
2. deploys that release to the **test** server and smoke-tests it;
3. waits for a reviewer to approve the **production** deployment, then deploys and checks it
   through the load balancer.

Each deploy copies `deploy/compose.yml`, `deploy/deploy.sh` and `scripts/smoke_test.sh` to
`/opt/xom` on the server and runs `deploy.sh`, which pulls the images, restarts the stack,
checks the new version answers, and checks that no service is restarting. Before
any of that, it checks that `/opt/xom/.env` belongs to the server being deployed: `APP_ENV`
must match, and every database user and database name must contain `_test` on the test
server and `_prod` on production. A file copied from the other server stops the deploy.

To roll back: Actions -> **Deploy** -> Run workflow, pick the environment and an earlier
`sha-...` tag. On a server, `bash /opt/xom/deploy.sh rollback` switches to the release before
the current one.

## Secrets

- Never commit passwords, keys, tokens, or `.env` files. The pre-commit hook and CI both scan
  for secrets, but do not rely on them.
- Database passwords live only in `/opt/xom/.env` on each server. SSH keys live only in the
  GitHub environments `test` and `production`.
- If you commit a secret by accident, tell the team straight away. Deleting the commit is not
  enough: the secret must be changed.
