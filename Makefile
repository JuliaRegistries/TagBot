build:
	rm -rf bin/
	env GOOS=linux go build -ldflags="-s -w" -o bin/github github/main.go
	cp *.pem bin/ || true
	chmod 644 bin/*.pem || true
