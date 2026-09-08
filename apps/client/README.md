# Intelligent Audio Analysis client

One Expo Router + TypeScript source targets the browser, iOS, and Android. The client contains no provider credentials; it talks only to the Intelligent Audio Analysis API.

## Local development

Requires Node 22.13 or newer.

```bash
npm install
EXPO_NO_DOTENV=1 npm run web
```

The API defaults to `http://localhost:8000`. Set `EXPO_PUBLIC_API_URL` to change it. On a physical phone, use the computer's reachable LAN address rather than `localhost`. Only `EXPO_PUBLIC_*` values belong in this client; they are embedded in the application bundle and must never contain secrets.

## Outputs

```bash
EXPO_NO_DOTENV=1 npm run export          # static web bundle in dist/
EXPO_NO_DOTENV=1 npm run prebuild        # generate disposable ios/ and android/ projects
EXPO_NO_DOTENV=1 npm run build:ios       # EAS iOS build (requires Expo project/account setup)
EXPO_NO_DOTENV=1 npm run build:android   # EAS Android build (requires Expo project/account setup)
```

The EAS scripts invoke `npx eas-cli`; the operator must supply the EAS project ID,
store identifiers, account login, and signing credentials. Those values are not
needed for browser export or local native project generation.

The generated native folders are intentionally ignored. Expo's Continuous Native Generation keeps application logic in this package instead of maintaining three source trees.

## Checks

```bash
EXPO_NO_DOTENV=1 npm run typecheck
EXPO_NO_DOTENV=1 npm run lint
EXPO_NO_DOTENV=1 npm test
```
