#!/usr/bin/env bash
# Domain container entrypoint: wait for Postgres, prepare the schema, then run
# whatever command was passed (the web server or the gRPC runner).
set -e

echo "domain: waiting for database..."
until bin/rails runner "ActiveRecord::Base.connection.execute('SELECT 1')" >/dev/null 2>&1; do
  sleep 1
done

# Exactly one service migrates (RUN_MIGRATIONS=1, the web service) to avoid a
# concurrent CREATE DATABASE race. The gRPC service waits for the schema instead.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  bin/rails db:prepare
else
  echo "domain: waiting for schema (migrations owned by the web service)..."
  until bin/rails runner "ActiveRecord::Base.connection.table_exists?('leads')" >/dev/null 2>&1; do
    sleep 1
  done
fi

exec "$@"
