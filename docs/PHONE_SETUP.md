# Phone App Setup

## Backend URL
The mobile app is already pointed to:

```text
https://ai-trading-platform-vdm6.onrender.com/api
```

To change it, edit `mobile/app.json` under `expo.extra.apiUrl`.

## Install EAS CLI

```bash
npm install -g eas-cli
eas login
```

## Build installable app

From the `mobile` folder:

```bash
npm install
eas build:configure
eas build --profile preview --platform ios
```

For Android:

```bash
eas build --profile preview --platform android
```

## Development build

```bash
eas build --profile development --platform ios
npx expo start --dev-client --tunnel
```

## Backend deployment settings on Render

Root Directory:

```text
backend
```

Build Command:

```bash
python -m pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
```

Start Command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment variable:

```text
PYTHON_VERSION=3.12.7
```
