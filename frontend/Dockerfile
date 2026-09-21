# Pin by digest: today's build could not fail; `npm ci` reaches a registry at
# deploy time, so a bad or yanked resolution must not be able to change what
# this image is. Rollback is a tag change to the last good image (README).
FROM node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85 AS build

WORKDIR /build
COPY chat/package.json chat/package-lock.json ./
RUN npm ci
COPY chat/ ./
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

RUN apk add --no-cache apache2-utils

COPY --from=build /build/dist/ /usr/share/nginx/html/chat/
# The legacy Alpine chat still owns `/` until unit 9 deletes it.
COPY index.html /usr/share/nginx/html/index.html
COPY assets/ /usr/share/nginx/html/assets/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY proxy_common.conf /etc/nginx/proxy_common.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
