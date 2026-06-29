.PHONY: fhir-up fhir-down

fhir-up:
	docker compose -f fhir/docker-compose.fhir.yml up -d

fhir-down:
	docker compose -f fhir/docker-compose.fhir.yml down
