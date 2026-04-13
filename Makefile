.PHONY: test test-docker publish pytest black flake8 mypy build-ApiFunction build-ReportsFunction

build-ApiFunction build-ReportsFunction:
	test -f requirements.txt || poetry export --extras web --without-hashes --output requirements.txt
	pip install -r requirements.txt -t $(ARTIFACTS_DIR)/ \
		--platform manylinux2014_x86_64 --only-binary=:all: \
		--python-version 3.12 --implementation cp
	cp -r tagbot $(ARTIFACTS_DIR)/
	cp pyproject.toml $(ARTIFACTS_DIR)/

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
