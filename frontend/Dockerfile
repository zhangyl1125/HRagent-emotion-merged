FROM node:22-alpine AS build
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    no_proxy=${NO_PROXY}
WORKDIR /app
COPY package*.json tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm ci --include=dev --registry=https://registry.npmjs.org --replace-registry-host=always && npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs \
    && openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
      -keyout /etc/nginx/certs/dev.key \
      -out /etc/nginx/certs/dev.crt \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:10.191.39.131"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080 8443
CMD ["nginx", "-g", "daemon off;"]
