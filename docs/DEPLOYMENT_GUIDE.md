# Deployment Guide — GenAR PADER Regulatory Engine

This document provides step-by-step instructions to deploy the PADER Regulatory Report Engine on **Render**, **Docker**, and other cloud platforms.

---

## 🚀 Option 1: Deploy on Render (Recommended)

Render is a modern cloud hosting platform with automatic GitHub deployment and free tier support.

### Method A: One-Click via Render Blueprint (`render.yaml`)

1. **Log in** to your [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** in the top navigation bar and select **Blueprint**.
3. Connect your GitHub repository: `https://github.com/ameydongre10/submission` (or your fork).
4. Render will automatically detect `render.yaml` in the root of your repo.
5. Click **Apply**.
6. Render will provision the web service:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Health Check**: `/api/health`
7. Once deployment finishes (typically 2-3 minutes), Render provides a live public URL (e.g. `https://pader-regulatory-engine.onrender.com`).

---

### Method B: Manual Web Service Setup on Render

If you prefer configuring via the web dashboard without Blueprint:

1. Go to [Render Dashboard](https://dashboard.render.com/) -> **New +** -> **Web Service**.
2. Select **Build and deploy from a Git repository**.
3. Choose or paste your repo: `ameydongre10/submission`.
4. Configure the service settings:
   - **Name**: `pader-regulatory-engine`
   - **Region**: Choose closest to you (e.g., Oregon, Frankfurt, Singapore)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
5. (Optional) Set Environment Variables in **Environment**:
   - `LLM_PROVIDER`: `mock` (or `openai`, `gemini`, `anthropic`)
   - `LLM_API_KEY`: *(optional, your API key for live LLM mode)*
   - `LLM_MODEL`: `gpt-4o-mini` (or your preferred model)
6. Click **Create Web Service**.
7. Wait for the build logs to show `Application startup complete`.
8. Visit your deployed URL!

---

## 🐳 Option 2: Docker Container Deployment

The repository includes an optimized `Dockerfile` ready for Docker or containerized cloud hosts (AWS ECS, Google Cloud Run, Railway, Fly.io).

### Build & Run Locally with Docker

```bash
# 1. Build the Docker image
docker build -t pader-engine:latest .

# 2. Run container on port 8000
docker run -p 8000:8000 pader-engine:latest
```

Open your browser at `http://localhost:8000` to access the interactive web dashboard.

---

## 💻 Option 3: Local Development & CLI

### Prerequisites
- Python 3.11+
- Virtual environment (`venv`)

### Setup

```bash
# Clone the repository
git clone https://github.com/ameydongre10/submission.git
cd submission

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Linux/macOS
# or on Windows:
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run full test suite (120 tests)
pytest

# Launch FastAPI web application & dashboard
python app.py
# Or using uvicorn:
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### CLI Execution

You can also run the regulatory pipeline completely via terminal:

```bash
# 1. Generate Draft Report (Status: DRAFT_PENDING_REVIEW)
python run_pader.py --mock --output-dir outputs

# 2. Perform Explicit Human Review Sign-Off
python run_pader.py --sign-off APPROVED --reviewer "Dr. J. Doe, MD" --notes "Verified all statistics."

# 3. Run Simulated Review for Testing / Demo Fixtures
python run_pader.py --simulate-review APPROVED
```

---

## 🔍 Verification & Health Checks

Once deployed, you can verify your service via curl:

```bash
# Health check
curl -X GET https://<your-render-url>/api/health

# Sample data stats
curl -X GET https://<your-render-url>/api/sample-data

# Interactive Swagger Documentation
Open https://<your-render-url>/docs
```
