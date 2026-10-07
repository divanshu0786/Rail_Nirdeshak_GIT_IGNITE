# 🚆 Rail Nirdeshak (रेल निर्देशक)
### *Next-Gen Dynamic ETA & Delay Propagation Intelligence Platform for Indian Railways*

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)
[![WebSocket](https://img.shields.io/badge/RealTime-WebSocket-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

---

## 1. Problem Statement
Indian Railways operates over 13,000 passenger trains daily across complex shared corridors. Current passenger tracking systems only display **static delay snapshots** (e.g. *"Delayed by 15 mins"*), without forecasting how the delay will evolve over the next 3–5 stations. 

Traditional tracking suffers from:
1. **Lack of Dynamic Forecast**: Delays cascade or recover dynamically as trains encounter headway congestion, speed restrictions, and scheduled buffer margins.
2. **Black-Box Tracking ("Why did the train stop?")**: Commuters receive no explainability regarding signal halts, section saturation, or weather constraints.
3. **Unchecked Shared-Track Propagation**: Upstream delays on busy trunk routes propagate to trailing trains on shared tracks without early notification.

---

## 2. Proposed Solution
**Rail Nirdeshak** transforms train tracking into an intelligent, explainable predictive engine:
- **Dynamic ETA Engine**: Forecasts arrival times for 3–5 upcoming stations based on physics, speed deficits, track-specific field surveys, and scheduled recovery buffers.
- **Explainable Delay Breakdown**: Transparently details *Signal Halt (+8m)*, *Section Congestion (+6m)*, *Weather (+3m)*, and *Recovery Buffer (-3m)*.
- **Shared-Track Delay Propagation**: Detects upstream congestion on shared corridors (e.g., Northern Railway Line 1) and alerts downstream trains.
- **Track-Aware Positioning**: Combines GPS telemetry with physical railway field survey markers (e.g., *KM 68/14*).
- **Dual Interfaces**: Passenger Dashboard & Division Traffic Control Room.

---

## 3. Key Features
- ⚡ **Real-Time Dynamic Recalculation**: Live telemetry ingestion triggers instant ETA recalculation and WebSocket broadcast.
- 💡 **Explainable Delay Breakdown**: Answers *"Why Did The ETA Change?"* with contributor bars.
- ⚠️ **Headway Propagation Alerts**: Warns commuters and controllers when upstream trains impact shared track headway.
- 🗺️ **Interactive Corridor Map**: Real-time Leaflet canvas visualizing routes, live train markers, and station progressions.
- 🧪 **Interactive Telemetry Stepper**: Built-in evaluation simulator to inject delays, speed recoveries, or signal halts during demonstrations.
- 🛡️ **Division Control Room**: Real-time KPI board, section congestion matrix, and on-ground field survey observation logger.
- 🔒 **Secure Authentication**: JWT-based auth for passenger watchlists and controller workflows.

---

## 4. System Architecture

```
                               ┌─────────────────────────────┐
                               │     Live / Demo Telemetry   │
                               │   (GPS, Speed, Pole, Delay) │
                               └──────────────┬──────────────┘
                                              │ POST /api/telemetry
                                              ▼
┌──────────────────────────┐      ┌─────────────────────────────┐
│ Physical Field Surveys   ├─────►│  Dynamic ETA Prediction     │
│ (Track Observations)     │      │  & Propagation Engine       │
└──────────────────────────┘      │ (eta_engine.py)             │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │   SQLite Database (Models)  │
                                  │   - Trains & Stations       │
                                  │   - Live State & ETAs       │
                                  │   - Users & Saved Watchlist │
                                  └──────────────┬──────────────┘
                                                 │
                                ┌────────────────┴────────────────┐
                                │                                 │
                   REST APIs (/api/*)                 WebSocket (/ws/*)
                                │                                 │
                                ▼                                 ▼
                     ┌──────────────────────────────────────────────┐
                     │           Modern Responsive Web App          │
                     │  - Passenger Tracker (Dynamic ETA Timeline)  │
                     │  - "Why Did ETA Change?" Explainer Card      │
                     │  - Interactive Live Leaflet Map              │
                     │  - Division Traffic Control Room             │
                     └──────────────────────────────────────────────┘
```

---

## 5. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Backend API** | Python 3.11, FastAPI, Uvicorn | High performance asynchronous REST API & WebSockets |
| **Prediction Engine** | Python Physics & Contributor Model | Explainable, deterministic, and verifiable delay calculation |
| **Database** | SQLite + SQLAlchemy ORM | Zero-config, reliable, and hackathon-ready persistence |
| **Authentication** | JWT (PyJWT), SHA-256 Hashing | Lightweight, stateless token authentication |
| **Real-Time Sync** | WebSockets (`/ws/trains/{id}`) | Instant telemetry push without page reloads |
| **Frontend** | HTML5, CSS3 (Modern Dark Theme), JS ES6+ | Zero-build complexity, fast loading, responsive |
| **Mapping** | Leaflet.js, OpenStreetMap CARTO tiles | Smooth interactive route rendering |
| **Containerization** | Docker, Procfile | Seamless multi-platform cloud deployment |

---

## 6. Repository Structure
```
f:\Rail_Nirdeshak\Git-Ignite-Rail-Nirdeshak\
├── backend/
│   ├── main.py               # FastAPI application & API routing
│   ├── models.py             # SQLAlchemy database models
│   ├── database.py           # DB connection & session factory
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── auth.py               # JWT authentication & password verification
│   ├── eta_engine.py         # Dynamic ETA calculation & propagation logic
│   ├── websocket_manager.py  # WebSocket client manager
│   ├── seed_data.py          # Northern Railway demo corridor seeder
│   ├── test_backend.py       # Comprehensive 12-stage automated test suite
│   └── requirements.txt      # Backend dependencies
├── frontend/
│   ├── index.html            # Web client application layout
│   ├── style.css             # Design system & dark theme styling
│   └── app.js                # Frontend controller & WebSocket client
├── Dockerfile                # Production Docker container definition
├── Procfile                  # Platform-as-a-Service deployment entry
├── start.bat                 # One-click Windows runner
├── start.sh                  # One-click Linux/macOS runner
├── .env.example              # Environment configuration template
└── README.md                 # Complete project documentation
```

---

## 7. Installation & Setup

### Prerequisites
- Python 3.11+
- Node.js (Optional, frontend is natively served by FastAPI)

### 1. Clone & Navigate
```bash
git clone https://github.com/cseclubs-auts/Git-Ignite-Rail-Nirdeshak.git
cd Git-Ignite-Rail-Nirdeshak
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Initialize & Seed Database
```bash
python backend/seed_data.py
```

---

## 8. Running Locally

### Option A: One-Click Script
- **Windows**: Double-click `start.bat`
- **Linux/macOS**: Run `./start.sh`

### Option B: Manual Command
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser and navigate to: **`http://127.0.0.1:8000`**

---

## 9. Environment Variables
Create `.env` based on `.env.example`:
```ini
DATABASE_URL=sqlite:///./rail_nirdeshak.db
SECRET_KEY=rail-nirdeshak-super-secret-key-2026
PORT=8000
HOST=0.0.0.0
```

---

## 10. API Endpoints Reference

### Authentication
- `POST /auth/register` — Create new passenger or controller account
- `POST /auth/login` — Sign in and receive JWT bearer token
- `GET /auth/me` — Retrieve active user session

### Trains & Dynamic ETA
- `GET /api/trains` — List or search active trains (e.g. `?query=12497`)
- `GET /api/trains/{train_id}` — Full train details, route stops, live state, and dynamic ETAs
- `GET /api/stations` — List corridor railway stations

### Real-Time Telemetry & Simulation
- `POST /api/telemetry` — Ingest live telemetry & trigger dynamic recalculation
- `POST /api/telemetry/simulate-step/{train_id}` — Step delay/speed for interactive judging demonstration

### Field Survey Observations
- `GET /api/field-observations` — Retrieve active on-ground track observations
- `POST /api/field-observations` — Dispatch surveyor track condition

### Control Room & Watchlist
- `GET /api/control-room/overview` — Network-wide congestion & headway risk overview
- `GET /api/saved-trains` — Retrieve user's bookmarked train watchlist
- `POST /api/saved-trains/{train_id}` — Save train to watchlist
- `DELETE /api/saved-trains/{train_id}` — Remove saved train

### WebSockets
- `ws://127.0.0.1:8000/ws/trains/{train_id}` — Live telemetry stream for specific train
- `ws://127.0.0.1:8000/ws/control-room` — Global corridor operations stream

---

## 11. Demo & Testing Credentials

| Role | Email | Password | Access Level |
|---|---|---|---|
| **Passenger** | `passenger@railnirdeshak.in` | `demo123` | Train tracking, Dynamic ETAs, Watchlist |
| **Zone Controller** | `control@railnirdeshak.in` | `admin123` | Traffic Control Room, Survey Dispatch |

### Demonstration Trains Seeded
1. **12497 – Shane Punjab Express** (New Delhi `NDLS` → Amritsar Junction `ASR`)
2. **12011 – Kalka Shatabdi Express** (New Delhi `NDLS` → Kalka `KLK`)

---

## 12. Automated Testing

Run the full end-to-end test suite:
```bash
python backend/test_backend.py
```
*Tests 12 complete execution phases: Database re-seeding, Health check, JWT Authentication, Train lookup, Dynamic ETA calculation, Explainable reason breakdown, Telemetry ingestion, Control Room overview, Static frontend delivery, Saved trains, Telemetry simulation, and Field survey logging.*

---

## 13. Deployment

### Render / Railway / Heroku
The repository contains `Procfile` and `Dockerfile` ready for zero-config one-click cloud deployment:
1. Connect repository on Render or Railway.
2. Build command: `pip install -r backend/requirements.txt`
3. Start command: `python backend/seed_data.py && uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

---

## 14. Team Contribution
- **System Architecture & Dynamic ETA Engine**: Dynamic prediction mathematics, headway propagation risk algorithms, explainable delay contributor model.
- **Backend & Real-Time Telemetry**: FastAPI application, SQLAlchemy models, JWT auth, WebSockets manager, and automated test suite.
- **Frontend & Interactive UI**: Modern dark-mode responsive dashboard, dynamic ETA station timeline, Leaflet interactive route mapping, and Traffic Control Room.
- **Data Modeling & Field Survey Integration**: Northern Railway corridor dataset, physical pole references, and on-ground track survey logging.

---
*Built for the Scratch to Hack Hackathon 2026.*