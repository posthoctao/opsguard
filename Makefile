.PHONY: install run repair-worker repair-verifier test compose-up compose-down compose-logs

install:
	python -m pip install -r requirements.txt

run:
	uvicorn app.main:app --reload

repair-worker:
	uvicorn repair_worker.main:app --reload --port 8090

repair-verifier:
	uvicorn repair_verifier.main:app --reload --port 8100

test:
	pytest -q

compose-up:
	docker compose up --build

compose-down:
	docker compose down --remove-orphans

compose-logs:
	docker compose logs -f backend repair-worker demo-service
