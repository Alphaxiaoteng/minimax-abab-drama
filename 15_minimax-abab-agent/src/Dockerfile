# 多阶段构建：deps 安装 → runner 运行。镜像仅含 node_modules 与源码，无 Python。
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# npm ci 复现 devDependencies（tsx/typescript），供 CMD 启动服务器
RUN npm ci

FROM node:22-alpine AS runner
WORKDIR /app
ENV PORT=8787
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json tsconfig.json ./
COPY src ./src
EXPOSE 8787
# 健康检查打到 /api/health；alpine 自带 busybox wget
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT}/api/health" >/dev/null || exit 1
CMD ["npx", "tsx", "src/server/index.ts"]