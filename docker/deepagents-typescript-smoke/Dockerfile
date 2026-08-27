FROM node:22.23.2-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

WORKDIR /workspace/typescript-runtime
COPY typescript-runtime/package.json ./package.json
COPY typescript-runtime/package-lock.json ./package-lock.json
COPY typescript-runtime/tsconfig.json ./tsconfig.json
COPY typescript-runtime/src ./src
RUN npm ci --ignore-scripts --engine-strict --no-audit --no-fund \
    && npm run typecheck \
    && npm run build \
    && npm prune --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm ls --omit=dev --all --json >/dev/null \
    && npm cache clean --force \
    && rm -rf /usr/local/lib/node_modules/npm \
      /usr/local/lib/node_modules/corepack \
      /opt/yarn-v1.22.22 \
      /workspace/typescript-runtime/src \
      /workspace/typescript-runtime/tsconfig.json \
      /workspace/typescript-runtime/package-lock.json

ENV HOME=/home/worker \
    LANGCHAIN_TRACING_V2=false \
    LANGSMITH_TRACING=false \
    NODE_ENV=production \
    NO_UPDATE_NOTIFIER=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false
ENTRYPOINT ["node"]
