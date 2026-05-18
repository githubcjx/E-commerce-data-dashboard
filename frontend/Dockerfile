FROM node:20-alpine AS build
WORKDIR /app

# China-friendly default; override at build with --build-arg NPM_REGISTRY=...
ARG NPM_REGISTRY=https://registry.npmmirror.com

COPY package.json package-lock.json ./
RUN npm config set registry "$NPM_REGISTRY" \
 && npm ci --no-audit --no-fund

COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
