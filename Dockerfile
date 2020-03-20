FROM golang:1.14-alpine AS builder
COPY go.* *.go /src/
RUN cd /src && go build -o tagbot

FROM alpine
RUN apk add git
USER guest
ENV REGISTRATOR_USERNAME JuliaRegistrator
COPY --from=builder /src/tagbot /app/

CMD /app/tagbot
