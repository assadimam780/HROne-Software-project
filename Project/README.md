# HROne Employee Attendance & Analytics API

A RESTful API built with Python 3.11+, FastAPI, and MongoDB (Motor).

## Features
- Smart Punch-In / Punch-Out with double-punch prevention
- Automated Late-coming mark (09:00 AM IST + 15m grace period)
- Manual corrections with immutable audit trail
- MongoDB Aggregation Analytics (Daily summary, Monthly employee report, Department stats)

## Setup & Run
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run application
uvicorn app.main:app --reload --port 8000