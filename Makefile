.PHONY: test test-docker publish pytest black flake8 mypy build-ApiFunction build-ReportsFunction

build-ApiFunction build-ReportsFunction:
	poetry export --extras web --without-hashes --output requirements.txt
	pip install -r requirements.txt -t $(ARTIFACTS_DIR)/
	cp -r tagbot $(ARTIFACTS_DIR)/

test:
	./bin/test.sh

test-docker:
	./bin/test-docker.sh

pytest:
	python -m pytest --cov tagbot --ignore node_modules

black:
	black --check bin stubs tagbot test

flake8:
	flake8 bin tagbot test

mypy:
	mypy --strict bin tagbot

publish:
	./bin/publish.py
