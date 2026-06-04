FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# postinstall runs repo-root scripts/copy-pdf-worker.sh (needs bash + parent dir);
# pdf.worker.min.mjs is committed under public/ for container builds.
RUN npm ci --ignore-scripts
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
