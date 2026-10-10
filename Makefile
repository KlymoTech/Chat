.PHONY: bootstrap dev test lint typecheck conformance build image-push deploy config architecture up down local-up local-down logs ps migrate smoke smoke-powershell clean reset-data

.env:
	cp .env.example .env
	@echo "Created .env from placeholders. Rotate every credential before non-local use."

bootstrap: .env
	npm install
	uv sync --project backend --all-groups

dev:
	npm run dev

test:
	npm test
	uv run --project backend pytest -c backend/pyproject.toml backend/tests

lint:
	npm run lint
	uv run --project backend ruff check backend

typecheck:
	npm run typecheck
	uv run --project backend mypy --config-file backend/pyproject.toml backend/src

conformance:
	uv run --project backend python scripts/audit-platform-conformance.py

build:
	npm run build
	docker compose build

# Publish only through the pinned, verified release workflow. Pushing the tag
# triggers .github/workflows/release.yml, which builds both architectures and
# applies the SBOM, provenance, vulnerability and attestation gates.
image-push:
	@test -n "$$RELEASE_TAG" || { echo 'Set RELEASE_TAG to a new v* tag at HEAD.' >&2; exit 2; }
	@git check-ref-format "refs/tags/$$RELEASE_TAG"
	@case "$$RELEASE_TAG" in v*) ;; *) echo 'RELEASE_TAG must start with v.' >&2; exit 2 ;; esac
	@test "$$(git rev-parse "refs/tags/$$RELEASE_TAG^{commit}")" = "$$(git rev-parse HEAD)" || { echo 'RELEASE_TAG must point to HEAD.' >&2; exit 2; }
	@if git ls-remote --exit-code --tags origin "refs/tags/$$RELEASE_TAG" >/dev/null 2>&1; then echo 'RELEASE_TAG already exists on origin.' >&2; exit 2; fi
	git push origin "refs/tags/$$RELEASE_TAG"

# Dispatch only the repository's provenance-checking production workflow;
# production environment protection remains the approval gate.
deploy:
	@test -n "$$RELEASE_SHA" || { echo 'Set RELEASE_SHA to the full 40-character release commit SHA.' >&2; exit 2; }
	@test "$${#RELEASE_SHA}" -eq 40 && case "$$RELEASE_SHA" in *[!0-9a-f]*) false ;; *) true ;; esac || { echo 'RELEASE_SHA must be 40 lowercase hexadecimal characters.' >&2; exit 2; }
	@case "$$HEALTH_URL" in https://*) ;; *) echo 'Set HEALTH_URL to the public HTTPS health endpoint.' >&2; exit 2 ;; esac
	@test -n "$$DEPLOY_WORKFLOW_REF" || { echo 'Set DEPLOY_WORKFLOW_REF to the reviewed branch or tag containing the protected deployment workflow.' >&2; exit 2; }
	@git check-ref-format "$$DEPLOY_WORKFLOW_REF"
	@git ls-remote --exit-code origin "refs/heads/$$DEPLOY_WORKFLOW_REF" "refs/tags/$$DEPLOY_WORKFLOW_REF" >/dev/null || { echo 'DEPLOY_WORKFLOW_REF must exist on origin.' >&2; exit 2; }
	@command -v gh >/dev/null || { echo 'GitHub CLI (gh) is required to dispatch the protected deployment workflow.' >&2; exit 2; }
	gh workflow run deploy-production.yml --ref "$$DEPLOY_WORKFLOW_REF" --field release_sha="$$RELEASE_SHA" --field health_url="$$HEALTH_URL"

config:
	docker compose config --quiet

architecture:
	bash scripts/validate-architecture.sh

up: .env
	docker compose up --build -d
	@echo "Northstar is starting at http://localhost:3000. Run 'make smoke' to wait for readiness."

down:
	docker compose down

local-up: up

local-down: down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

migrate:
	docker compose run --rm migrate

smoke:
	bash scripts/smoke.sh

smoke-powershell:
	pwsh -NoProfile -File scripts/smoke.ps1

clean:
	docker compose down --remove-orphans

reset-data:
	docker compose down --volumes --remove-orphans
