.PHONY: test test-docker publish pytest black flake8 mypy

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
