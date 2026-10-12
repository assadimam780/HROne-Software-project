# HROne — Employee Attendance & Analytics API

A RESTful backend API for managing employee attendance and generating attendance analytics. This project is built with **Python 3.11+, FastAPI, and MongoDB**, using Motor for asynchronous database access.

The project focuses on reliable punch-in/punch-out workflows, late-arrival tracking, auditable manual corrections, and reporting across employees and departments.

## Overview

The Employee Attendance & Analytics API is designed to support common workforce attendance operations:

- Record employee punch-in and punch-out activity.
- Prevent duplicate attendance records for the same employee and work date.
- Mark late arrivals using a **09:00 AM IST start time with a 15-minute grace period**.
- Keep an audit trail for manual attendance corrections.
- Generate attendance summaries using MongoDB aggregation pipelines.

## Key Features

### Attendance Management
- Smart punch-in and punch-out workflow.
- Double-punch prevention for an employee on the same work date.
- Daily attendance records with punch timestamps, total hours, and status.

### Late-Arrival Tracking
- Uses 09:00 AM IST as the reference start time.
- Applies a 15-minute grace period before marking an employee late.
- Uses the `Asia/Kolkata` timezone for work-date and attendance-rule calculations.

### Manual Corrections & Auditability
- Supports manual corrections to attendance records.
- Stores correction history in an `audit_trail` array within the relevant attendance document.
- Keeps correction history available for review.

### Attendance Analytics
- Daily attendance summaries.
- Monthly employee attendance reports.
- Department-level statistics.
- MongoDB aggregation for reporting queries.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.11+ | Backend programming language |
| FastAPI | REST API framework |
| MongoDB | Document database |
| Motor | Asynchronous MongoDB driver |
| Uvicorn | ASGI server for running the API |

## High-Level Data Model

The design separates employee master data from daily attendance transactions.

### `employees` collection
Stores relatively stable employee information, such as:

- `employee_id`
- `name`
- `department`
- `shift`

### `attendance` collection
Stores attendance information for each employee and work date, such as:

- `employee_id`
- `date`
- `punch_in`
- `punch_out`
- `total_hours`
- `status`
- `audit_trail`

### Why separate the collections?

Attendance data grows over time, while employee profile information changes less frequently. Keeping these records separate avoids an ever-growing employee document and makes attendance queries and reporting easier to manage. The bounded `audit_trail` is embedded in the attendance document so its correction history can be retrieved with that record.

## Reliability & Design Considerations

The accompanying `DECISION.md` documents the architectural rationale. Important safeguards include:

- **Unique attendance per employee per date:** use a compound unique index on `{ employee_id: 1, date: 1 }`.
- **Concurrent requests:** use an atomic database operation, such as an upsert with `$setOnInsert`, alongside the unique index to reduce duplicate-record race conditions.
- **Timezone consistency:** store timestamps in UTC and convert to `Asia/Kolkata` when applying local attendance rules or deriving the work date.
- **Request validation:** use Pydantic models to validate incoming payloads.
- **Correct HTTP responses:** return appropriate HTTP status codes for validation failures and duplicate punch attempts.
- **Query performance:** create indexes that match common employee/date and employee/timestamp query patterns.

> These are design and hardening considerations documented for the project. Confirm the implementation in the source code before describing every safeguard as already implemented.

## Project Setup

### Prerequisites

- Python 3.11 or newer
- MongoDB instance (local or hosted)
- `pip`

### 1. Clone or open the project

Open the project directory in your terminal.

### 2. Create and activate a virtual environment (recommended)

**Windows PowerShell**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure MongoDB

Configure the MongoDB connection using the settings expected by the application. Keep credentials and connection strings in environment variables or a local environment file, and do not commit secrets to version control.

### 5. Run the application

From the project root, run:

```bash
uvicorn app.main:app --reload --port 8000
```

The local API server should then be available at:

- API base URL: `http://127.0.0.1:8000`
- Interactive Swagger documentation: `http://127.0.0.1:8000/docs`
- ReDoc documentation: `http://127.0.0.1:8000/redoc`

The documentation URLs are provided by FastAPI when its default documentation routes are enabled.

## Code Review & Improvements

The accompanying `Review.md` reviews a punch-in snippet and identifies issues that should be addressed before production use:

1. **Blocking database calls:** avoid synchronous PyMongo calls inside an `async` FastAPI route; use an asynchronous driver such as Motor or move blocking work to a thread pool.
2. **Race conditions:** a separate “check then insert” flow can allow concurrent requests to create duplicates; use a unique index and an atomic database operation.
3. **Timezone-naive timestamps:** use timezone-aware UTC timestamps and convert to IST for attendance rules.
4. **HTTP status conventions:** use appropriate error status codes instead of returning an error payload with HTTP 200.
5. **Payload validation:** define request schemas with Pydantic.
6. **Database indexes:** index fields used frequently for filtering and sorting.

These points describe the review findings and recommended fixes; they should not be read as proof that the supplied snippet or entire application already includes all fixes.

## Documentation Files

- `README.md` — project overview, features, technology stack, setup, and design notes.
- `DECISION.md` — architectural decisions and technical rationale.
- `Review.md` — code review findings and recommended improvements for the punch-in implementation.

## Future Enhancements

Potential next steps, depending on the assignment requirements:

- Add automated tests for attendance rules and simultaneous punch-in requests.
- Add authentication and role-based authorization.
- Add structured logging and consistent error responses.
- Add API examples and endpoint-specific request/response documentation.
- Add deployment instructions and environment-specific configuration guidance.

## Summary

The HROne Employee Attendance & Analytics API demonstrates a backend design for employee attendance workflows and analytics using FastAPI and MongoDB. Its main focus areas are attendance record management, late-arrival rules, auditable corrections, aggregation-based reports, and careful handling of concurrency, timezones, validation, and database performance.
