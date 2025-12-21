.PHONY: test test-web docker publish

# Run Julia tests
test:
	cd julia && julia --project=. -e 'using Pkg; Pkg.test()'

# Run Python web service tests
test-web:
	cd test/web && python -m pytest

# Build Docker image
docker:
	docker build -t tagbot:test .

# Publish release (run from CI)
publish:
	python bin/publish.py
