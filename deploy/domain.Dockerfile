# Rails domain service for the local full stack (development mode).
# Runs as two compose services from this one image: the broker web dashboard
# (puma) and the Domain gRPC server (bin/grpc_server). Build context is the repo
# root so the shared layout is available.
FROM ruby:3.3

ENV RAILS_ENV=development \
    BUNDLE_PATH=/usr/local/bundle

WORKDIR /app

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends postgresql-client libpq-dev libsqlite3-0 curl && \
    rm -rf /var/lib/apt/lists/*

# Install gems first for layer caching. All groups (dev tools + grpc + pg).
COPY services/domain/Gemfile services/domain/Gemfile.lock ./
RUN bundle config set --local without '' && bundle install

# App code (generated gRPC stubs under lib/grpc are committed).
COPY services/domain/ ./

COPY deploy/domain-entrypoint.sh /usr/local/bin/domain-entrypoint.sh
RUN chmod +x /usr/local/bin/domain-entrypoint.sh bin/grpc_server

EXPOSE 3000 50052
ENTRYPOINT ["/usr/local/bin/domain-entrypoint.sh"]
# Default command is the web dashboard; the gRPC service overrides it in compose.
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
