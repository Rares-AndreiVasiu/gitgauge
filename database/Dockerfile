FROM postgres:16-alpine

ENV POSTGRES_DB=gitgauge
ENV POSTGRES_USER=gitgauge
ENV POSTGRES_PASSWORD=gitgauge

COPY init.sql /docker-entrypoint-initdb.d/

EXPOSE 5432

