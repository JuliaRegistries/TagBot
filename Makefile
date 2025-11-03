.PHONY: test test-docker publish

test:
	./bin/test.sh

test-docker:
	./bin/test-docker.sh

publish:
	./bin/publish.py

bake:
	python3 bin/embed_example_into_readme.py
