COMPOSE = docker compose
RUN     = $(COMPOSE) run --rm estrato

.DEFAULT_GOAL := help
.PHONY: help build db generate load run replay step fingerprint charts dbt psql test lint shell clean down

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build:  ## Build the image (dbt-core, dbt-postgres, numpy, matplotlib)
	$(COMPOSE) build

db:  ## Start Postgres in the background and wait until it accepts connections
	$(COMPOSE) up -d --wait postgres

generate:  ## Write the synthetic source into data/ (never committed). Optional: SEED=7 SCALE=10000
	@mkdir -p data
	$(RUN) python -m estrato generate $(if $(SEED),--seed $(SEED),) $(if $(SCALE),--scale $(SCALE),)

load:  ## COPY every extract in data/ into the raw schema
	$(RUN) python -m estrato load

replay:  ## Build every extract not yet seen, in order, then run the dbt tests. REBUILD=1 starts over
	$(RUN) python -m estrato replay $(if $(REBUILD),--rebuild,)

step:  ## Build one extract date again, e.g. make step AS_OF=2018-12-31 (must not precede the last one)
	$(RUN) python -m estrato step $(AS_OF)

run: generate load replay  ## generate → load → replay, end to end

fingerprint:  ## Row count and content hash of every mart: run twice, compare
	$(RUN) python -m estrato fingerprint

charts:  ## Redraw the README figures from the marts into docs/img
	$(RUN) python -m estrato charts

dbt:  ## Run any dbt command inside the image, e.g. make dbt ARGS="test --select dim_insured"
	$(RUN) dbt $(ARGS)

psql:  ## Open psql against the warehouse
	$(COMPOSE) exec postgres psql -U estrato -d estrato

test:  ## Run the test suite inside the image (needs Postgres; no dataset needed)
	@mkdir -p data
	$(RUN) python -m pytest -q

lint:  ## Static checks (blocking in CI)
	$(RUN) sh -c "ruff check . && ruff format --check ."

shell:  ## Open a shell in the container
	$(RUN) bash

clean:  ## Remove the generated source and the dbt build artefacts (keeps the database)
	rm -rf data dbt/target dbt/logs

down:  ## Stop every container and drop the Postgres volume
	$(COMPOSE) down --volumes
