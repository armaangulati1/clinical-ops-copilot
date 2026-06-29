.PHONY: fhir-up fhir-down download-synthea generate-synthea load-synthea

SYNTHEA_DIR := synthea
SYNTHEA_JAR := $(SYNTHEA_DIR)/synthea-with-dependencies.jar
SYNTHEA_JAR_URL := https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar
SYNTHEA_STATE ?= Massachusetts
SYNTHEA_POP ?= 100

fhir-up:
	docker compose -f fhir/docker-compose.fhir.yml up -d

fhir-down:
	docker compose -f fhir/docker-compose.fhir.yml down

download-synthea:
	mkdir -p $(SYNTHEA_DIR)
	test -f $(SYNTHEA_JAR) || curl -sL $(SYNTHEA_JAR_URL) -o $(SYNTHEA_JAR)

generate-synthea: download-synthea
	cd $(SYNTHEA_DIR) && java -jar synthea-with-dependencies.jar -p $(SYNTHEA_POP) --exporter.fhir.export true $(SYNTHEA_STATE)

load-synthea:
	uv run load-synthea
