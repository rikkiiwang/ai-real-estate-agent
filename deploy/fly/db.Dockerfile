# Postgres + pgvector for the Fly deployment, built from the same image the
# local compose stack uses so the vector extension is guaranteed. The init
# scripts run once on an empty data volume: they create the Rails database and
# enable pgvector on the RAG database.
#
# Build context is deploy/fly/ so db-initdb/ is in scope.
FROM pgvector/pgvector:pg16
COPY db-initdb/ /docker-entrypoint-initdb.d/
