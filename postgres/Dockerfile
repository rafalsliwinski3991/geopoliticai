FROM postgres:16-alpine
ARG PGVECTOR_VERSION=0.8.1
RUN apk add --no-cache --virtual .pgvector-build git build-base postgresql16-dev \
 && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector with_llvm=no OPTFLAGS="" \
 && make -C /tmp/pgvector with_llvm=no install \
 && rm -rf /tmp/pgvector \
 && apk del .pgvector-build
