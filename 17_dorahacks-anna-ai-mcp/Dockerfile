# syntax=docker/dockerfile:1.7
#
# NetIntel MCP Server -- multi-stage, zero-runtime-dependency image.
#
# Stage 1 compiles TypeScript (the only dev dependency) into dist/.
# Stage 2 ships node + the compiled JS + fixtures. `dependencies` in package.json
# is `{}`, so no npm install is required at runtime and the final image contains
# no node_modules at all.

FROM node:22-alpine AS build
WORKDIR /build

# Dependency manifest first: this layer is cached until devDependencies change.
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts --no-audit --no-fund || npm install --ignore-scripts --no-audit --no-fund

COPY tsconfig.json ./
COPY src ./src
COPY tests ./tests
RUN npm run build


FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NETINTEL_TRANSPORT=stdio \
    NETINTEL_OFFLINE=0 \
    NETINTEL_FIXTURE_DIR=/app/fixtures/feeds \
    NETINTEL_LOG_LEVEL=info

WORKDIR /app

# Compiled server + curated offline fixtures + the one-command smoke proof.
COPY --from=build /build/dist ./dist
COPY fixtures ./fixtures
COPY scripts ./scripts
COPY package.json ./package.json

# Run unprivileged. /app/data is the only writable path, kept for operators who
# want to mount a fixture volume or a persistent cache directory.
RUN addgroup -g 10001 -S netintel \
 && adduser -u 10001 -S netintel -G netintel \
 && mkdir -p /app/data \
 && chown -R netintel:netintel /app/data

USER netintel

# The stdio transport speaks NDJSON over stdin/stdout; nothing listens on a port
# by default. `--transport http` binds 127.0.0.1:8765 unless NETINTEL_HOST/PORT
# are overridden.
EXPOSE 8765

# Non-root liveness check: a full initialize + tools/list handshake against the
# real binary, asserting the server advertises exactly the documented tool set.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "const{spawn}=require('node:child_process');const p=spawn(process.execPath,['dist/src/cli.js','--transport','stdio'],{env:{...process.env,NETINTEL_OFFLINE:'1'}});let b='';const done=(ok)=>{try{p.kill()}catch{};process.exit(ok?0:1)};setTimeout(()=>done(false),8000);p.stdout.on('data',(d)=>{b+=d;for(const l of b.split('\n')){if(!l.trim())continue;let m;try{m=JSON.parse(l)}catch{continue}if(m.id===1){p.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');p.stdin.write(JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/list'})+'\n')}else if(m.id===2){done(m.result.tools.length===5)}}});p.stdin.write(JSON.stringify({jsonrpc:'2.0',id:1,method:'initialize',params:{protocolVersion:'2025-06-18',capabilities:{},clientInfo:{name:'healthcheck',version:'1'}}})+'\n')"

ENTRYPOINT ["node", "dist/src/cli.js"]
CMD ["--transport", "stdio"]
