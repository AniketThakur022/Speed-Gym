FROM node:20-slim

WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev

COPY src ./src
COPY tsconfig.json ./

EXPOSE 3001
CMD ["npx", "tsx", "src/index.ts"]
