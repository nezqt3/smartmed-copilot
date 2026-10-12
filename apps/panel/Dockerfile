FROM node:22-alpine AS build
WORKDIR /app/apps/panel
COPY apps/panel/package*.json ./
RUN npm ci
COPY apps/panel/ ./
COPY examples/outpatient_realistic_synthetic_zh.json /app/examples/outpatient_realistic_synthetic_zh.json
RUN npm run build

FROM nginx:1.27-alpine
COPY apps/panel/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/panel/dist /usr/share/nginx/html
EXPOSE 80
