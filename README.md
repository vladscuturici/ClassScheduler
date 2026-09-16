# ClassScheduler

A class scheduling application built with a Python backend and React frontend.

## Run locally

### 1. Clone the repository

```bash
git clone https://github.com/vladscuturici/ClassScheduler.git
cd ClassScheduler
```

### 2. Install backend dependencies

```bash
pip install -r requirements.txt
```

### 3. Install and build the frontend

```bash
cd frontend
npm install
npm run build
```

### 4. Start the application

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:5173** in your browser.
