.PHONY: container-check up migrate seed db-check db-up
container-check:
	MODE=$(MODE) sh scripts/container-check.sh
up: container-check
	docker compose up -d --no-build
migrate: container-check
	docker compose run --rm --no-deps app1 python app.py migrate
seed: container-check
	docker compose run --rm --no-deps app1 python app.py init-demo
db-check:
	$(MAKE) container-check MODE=db
db-up: db-check
	docker compose -f compose.db.yml up -d

.PHONY: ci
ci:
	sh scripts/ci-dind.sh all
