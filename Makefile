# Spatial app: operator control surface. `make help` lists every target.
# Guide: docs/setup/. Docker Compose reads .env (COMPOSE_FILE, versions, passwords).
SHELL := /bin/bash
.DEFAULT_GOAL := help

export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
export HOST_USER := $(shell id -un)

COMPOSE := docker compose
TOOLS   := $(COMPOSE) run --rm geotools
TOOLS_T := $(COMPOSE) run --rm -T geotools
OPS     := bash scripts/ops.sh

.PHONY: help check-env env bootstrap verify arch-check \
        up down stop start restart ps health logs shell rebuild pull \
        psql migrate migrate-status migration seed refresh backup restore reset-db nuke \
        build-tools inspect import import-recipe import-all datasets cog \
        r py tools-sh \
        frontend frontend-install frontend-dev frontend-check e2e \
        contracts contracts-check validate-styles projects-sync projects-check \
        mcp-credentials mcp-build mcp-test \
        workers-up workers-logs \
        recipes-sync health-datasets freshness admin-credentials

help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} \
	  /^## / {printf "\n\033[1m%s\033[0m\n", substr($$0, 4)} \
	  /^[a-z][a-zA-Z0-9_-]*:.*## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

check-env:
	@test -f .env || { echo ".env missing: run 'make env' first (docs/setup/01-install.md)"; exit 1; }

## Setup
env: ## Create .env with random passwords (force=1 overwrites an existing .env)
	@if [ -f .env ] && [ "$(force)" != "1" ]; then \
	  echo ".env already exists. force=1 overwrites it (an existing database keeps its old owner password)."; exit 1; fi
	@python3 -c 'import re, secrets; src = open(".env.example").read(); \
	  print(re.sub(r"^(\w*PASSWORD)=changeme$$", lambda m: m.group(1) + "=" + secrets.token_hex(16), src, flags=re.M), end="")' > .env
	@chmod 600 .env
	@echo "wrote .env with random passwords"

bootstrap: check-env ## First run: start, build geotools, import recipes, seed, refresh
	@$(OPS) bootstrap

verify: check-env ## Run the automated Phase 1 checks
	@bash scripts/verify.sh

verify-prod: check-env ## Check a production-mode stack: public site has no admin/drafts (PUBLIC_URL=, ADMIN_URL=)
	@set -a; . ./.env; set +a; bash scripts/verify_prod.sh

prod-local: check-env ## Try production mode locally: public site on :8090, admin on :8081 (make dev-proxy to undo)
	COMPOSE_FILE=compose.yaml:compose.prod.yaml PUBLIC_HTTP_BIND=127.0.0.1:8090 PUBLIC_HTTPS_BIND=127.0.0.1:8453 \
		$(COMPOSE) up -d --force-recreate --no-deps proxy

cog-sync: check-env ## Mirror data/cog to s3://$$COG_S3_BUCKET/$$COG_S3_PREFIX (needs compose.s3.yaml in COMPOSE_FILE)
	@case "$${COMPOSE_FILE:-$$(grep -E '^COMPOSE_FILE=' .env | cut -d= -f2)}" in *compose.s3.yaml*) ;; \
	  *) echo "add compose.s3.yaml to COMPOSE_FILE first (docs/setup/10-production.md)"; exit 2;; esac
	$(COMPOSE) run --rm cog-sync

backup-offsite: check-env ## make backup, then upload it to s3://$$BACKUP_S3_BUCKET/backups/ (needs compose.s3.yaml)
	@case "$${COMPOSE_FILE:-$$(grep -E '^COMPOSE_FILE=' .env | cut -d= -f2)}" in *compose.s3.yaml*) ;; \
	  *) echo "add compose.s3.yaml to COMPOSE_FILE first (docs/setup/10-production.md)"; exit 2;; esac
	@$(OPS) backup
	$(COMPOSE) run --rm backup-upload
	@if [ "$${BACKUP_PRUNE_LOCAL:-$$(grep -E '^BACKUP_PRUNE_LOCAL=' .env | cut -d= -f2)}" = 1 ]; then \
	  find data/backups -maxdepth 1 -name '*.dump' -mtime +7 -print -delete; fi

dev-proxy: check-env ## Back to the dev proxy on :8080 after make prod-local
	$(COMPOSE) up -d --force-recreate --no-deps proxy

arch-check: ## Check docs/architecture.md still names every service, adapter and project
	@bash scripts/check_architecture.sh

## Containers
up: check-env ## Start the stack (data is kept)
	$(COMPOSE) up -d
	@$(OPS) wait

down: ## Stop and remove containers (data volumes are kept)
	$(COMPOSE) --profile tools down --remove-orphans

stop: ## Pause containers without removing them
	$(COMPOSE) stop

start: check-env ## Resume paused containers
	$(COMPOSE) start
	@$(OPS) wait

restart: check-env ## Restart one service (s=tipg) or all
	$(COMPOSE) restart $(s)
	@$(OPS) wait

ps: ## Container status
	$(COMPOSE) ps -a

health: ## Health per service
	@$(COMPOSE) ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Health}}\t{{.Status}}'

logs: ## Follow logs (s=<service> for one)
	$(COMPOSE) logs -f --tail=200 $(s)

shell: ## Shell inside a running container (s=postgis|tipg|proxy)
	@test -n "$(s)" || { echo "usage: make shell s=<service>"; exit 2; }
	$(COMPOSE) exec $(s) sh

rebuild: check-env ## Recreate a service from a fresh image (s=<service>)
	$(COMPOSE) up -d --build --force-recreate $(s)
	@$(OPS) wait

pull: check-env ## Download the pinned images from .env
	$(COMPOSE) pull --ignore-buildable

## Database
psql: check-env ## psql as the owner (r=loader|analyst|tipg for another role)
	@if [ -z "$(r)" ]; then \
	  $(COMPOSE) exec postgis sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'; \
	else $(TOOLS) psql service=$(r); fi

migrate: check-env ## Apply db/migrations (also re-sets role passwords from .env)
	$(COMPOSE) run --rm migrator migrate

migrate-status: check-env ## Show applied/pending migrations
	$(COMPOSE) run --rm migrator status

migration: check-env ## Create a migration file (n=<name>)
	@$(OPS) migration $(n)

seed: check-env ## Create/replace the placeholder pub views (db/seed)
	$(COMPOSE) run --rm migrator seed

refresh: check-env ## Make tiPG see new/changed pub views (restarts tipg)
	@$(OPS) refresh

backup: check-env ## pg_dump to data/backups/
	@$(OPS) backup

restore: check-env ## Replace the database with a backup (b=<file>)
	@$(OPS) restore $(b)

reset-db: check-env ## DESTRUCTIVE: rebuild the database from migrations + recipes + seed
	@$(OPS) reset-db

nuke: check-env ## DESTRUCTIVE: remove containers, volumes, generated files (all=1: images too)
	@$(OPS) nuke $(if $(all),all)

## Data
build-tools: check-env ## Build the geotools image (GDAL + R + Python; slow the first time)
	$(COMPOSE) build geotools

inspect: check-env ## Layers, CRS, fields of a file (f=<file> [l=<layer>])
	@test -n "$(f)" || { echo "usage: make inspect f=<file in data/incoming> [l=<layer>]"; exit 2; }
	@$(TOOLS_T) python scripts/geoimport.py inspect "$(f)" $(if $(l),--layer "$(l)") $(foreach o,$(oo),--oo "$(o)")

import: check-env ## Import a file (f=<file> t=src_<domain>.<table>; options: docs/setup/04)
	@test -n "$(f)" -a -n "$(t)" || { echo "usage: make import f=<file in data/incoming> t=src_<domain>.<table>"; exit 2; }
	@$(TOOLS_T) python scripts/geoimport.py import "$(f)" "$(t)" \
	  $(if $(l),--layer "$(l)") $(if $(srs),--srs "$(srs)") $(if $(src_srs),--src-srs "$(src_srs)") \
	  $(if $(m),--mode "$(m)") $(if $(fix),--fix) $(if $(clip),--clip) $(foreach o,$(oo),--oo "$(o)") \
	  $(if $(license),--license "$(license)") $(if $(notes),--notes "$(notes)")

import-recipe: check-env ## Run one recipe (r=<name>; force=1 runs a disabled recipe)
	@test -n "$(r)" || { echo "usage: make import-recipe r=<name>  (see data/recipes/)"; exit 2; }
	@$(TOOLS_T) python scripts/geoimport.py recipe "$(r)" $(if $(force),--force)

import-all: check-env ## Run every enabled recipe in data/recipes/
	@$(TOOLS_T) python scripts/geoimport.py all $(if $(rasters),--rasters)

datasets: check-env ## List imported datasets (app.datasets)
	@$(TOOLS_T) python scripts/geoimport.py list

cog: check-env ## Convert a raster to a Cloud Optimized GeoTIFF in data/cog/ (f=<file>)
	@test -n "$(f)" || { echo "usage: make cog f=<raster in data/incoming>"; exit 2; }
	@$(TOOLS_T) python scripts/geoimport.py cog "$(f)"

## Frontend (Svelte + MapLibre; docs/setup/05-frontend.md)
frontend: check-env ## Rebuild and restart the web app after frontend code changes
	$(COMPOSE) up -d --build frontend
	@$(OPS) wait

frontend/node_modules: frontend/package-lock.json
	$(COMPOSE) run --rm -T node npm ci --no-audit --no-fund
	@touch frontend/node_modules

frontend-install: check-env ## Install frontend dependencies (node container)
	$(COMPOSE) run --rm -T node npm ci --no-audit --no-fund

frontend-dev: check-env frontend/node_modules ## Live-reload dev server on http://localhost:5173
	$(COMPOSE) run --rm --service-ports node npm run dev -- --host 0.0.0.0 --port 5173

frontend-check: check-env frontend/node_modules ## Type-check the frontend (svelte-check)
	$(COMPOSE) run --rm -T node npm run check

e2e: check-env frontend/node_modules ## Browser tests + screenshots (frontend/test-results/screens/)
	$(COMPOSE) --profile test run --rm e2e

## Projects (./mapgen; docs/setup/07-projects.md)
contracts: check-env frontend/node_modules ## Regenerate frontend types from contracts/*.schema.json
	$(COMPOSE) run --rm -T node node scripts/contracts.mjs

contracts-check: check-env frontend/node_modules ## Fail if the generated frontend types are stale
	@$(COMPOSE) run --rm -T node node scripts/contracts.mjs check

validate-styles: check-env frontend/node_modules ## MapLibre style-spec check of every project (p=<slug> for one)
	@$(COMPOSE) run --rm -T node node scripts/validate-styles.mjs $(p)

projects-sync: check-env ## Register every project in projects/index.json (same as ./mapgen sync)
	@$(TOOLS_T) python scripts/mapgen.py sync

projects-check: check-env ## Fail if projects/ and the project registry differ
	@$(TOOLS_T) python scripts/mapgen.py sync --check

## Analysis workers (R/Python processes; docs/setup/09-ml-workers.md)
workers-up: check-env ## Start the dataset worker and the analysis worker (needs the geotools image: make build-tools)
	$(COMPOSE) --profile workers up -d --build worker dataset-worker

workers-logs: check-env ## Follow both workers' logs
	$(COMPOSE) --profile workers logs -f worker dataset-worker

## MCP servers (Claude Code; docs/setup/08-mcp.md)
mcp-credentials: check-env ## Create the MCP credentials in .env if missing, then apply them (migrate, core-api)
	@python3 -c 'import re, secrets; p = ".env"; s = open(p).read(); \
	  add = [k + "=" + secrets.token_hex(16 if k.endswith("PASSWORD") else 24) for k in ("MCP_DB_PASSWORD", "MCP_PIPELINE_TOKEN", "MCP_ANALYSIS_TOKEN") \
	         if not re.search("^" + k + "=.", s, re.M)]; \
	  s = re.sub(r"^MCP_(PIPELINE|ANALYSIS)_TOKEN=\n", "", s, flags=re.M) if add else s; \
	  open(p, "w").write(s.rstrip("\n") + "\n" + "\n".join(add) + "\n") if add else None; \
	  print("added " + ", ".join(a.split("=")[0] for a in add) + " to .env" if add else "MCP credentials are already set")'
	@$(MAKE) --no-print-directory migrate > /dev/null && echo "role mcp_ro can log in"
	@$(COMPOSE) up -d core-api > /dev/null 2>&1 && echo "core-api accepts the project-pipeline token"

mcp-build: check-env ## Build the MCP server image (shared by every MCP server)
	$(COMPOSE) build mcp-db

mcp-test: check-env ## Smoke-test the MCP servers over stdio (Maine data), incl. propose -> apply -> publish
	@$(COMPOSE) run --rm -T --no-deps mcp-db python tests/smoke_spatial_db.py
	@bash scripts/mcp_pipeline_e2e.sh
	@$(COMPOSE) run --rm -T --no-deps mcp-analysis python tests/smoke_analysis.py

## Admin dashboard (http://localhost:8080/admin; docs/setup/06-admin.md)
recipes-sync: check-env ## Mirror data/recipes/*.yaml into the dataset registry
	@$(TOOLS_T) python scripts/geoimport.py sync

health-datasets: check-env ## Re-check every dataset output (tables, pub views, tiPG collections)
	@$(TOOLS_T) python scripts/geoimport.py health $(r)

freshness: check-env ## Compare loaded data with what upstream offers now (r=<recipe> for one)
	@$(TOOLS_T) python scripts/geoimport.py freshness $(r)

admin-credentials: check-env ## Show the /admin login (creates one in an older .env)
	@python3 -c 'import re, secrets; p = ".env"; s = open(p).read(); add = []; \
	  add += [] if re.search(r"^ADMIN_USER=", s, re.M) else ["ADMIN_USER=admin"]; \
	  add += [] if re.search(r"^ADMIN_PASSWORD=", s, re.M) else ["ADMIN_PASSWORD=" + secrets.token_hex(12)]; \
	  add += [] if re.search(r"^ADMIN_API_DB_PASSWORD=", s, re.M) else ["ADMIN_API_DB_PASSWORD=" + secrets.token_hex(16)]; \
	  open(p, "a").write("\n" + "\n".join(add) + "\n") if add else None; \
	  print("added " + ", ".join(a.split("=")[0] for a in add) + " to .env; run make up") if add else None'
	@grep -E '^ADMIN_(USER|PASSWORD)=' .env | sed 's/^ADMIN_USER=/user:     /; s/^ADMIN_PASSWORD=/password: /'
	@echo "login at http://localhost:$${HTTP_PORT:-8080}/admin"

## Tools (geotools container, connected to PostGIS as analyst_ro)
r: check-env ## R session
	$(TOOLS) R

py: check-env ## Python session
	$(TOOLS) python

tools-sh: check-env ## bash with gdal/ogr2ogr/psql/R/python
	$(TOOLS) bash
