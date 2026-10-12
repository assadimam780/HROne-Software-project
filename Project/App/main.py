"""
Employee Attendance & Analytics API
Built with FastAPI, Motor (Async MongoDB), and Pydantic v2.
Designed for HROne Software Engineer Trainee Technical Assignment.
"""

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional
import os
import pytz
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson import ObjectId


MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "hrone_attendance_db")

LOCAL_TIMEZONE = pytz.timezone("Asia/Kolkata")
SHIFT_START_TIME = time(9, 0)
GRACE_PERIOD_MINUTES = 15
FULL_DAY_MIN_HOURS = 8.0
HALF_DAY_MIN_HOURS = 4.0


class Database:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

db_instance = Database()

async def get_db() -> AsyncIOMotorDatabase:
    if db_instance.db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not initialized"
        )
    return db_instance.db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_instance.client = AsyncIOMotorClient(MONGODB_URL)
    db_instance.db = db_instance.client[DATABASE_NAME]
    
    await db_instance.db.employees.create_index("employee_id", unique=True)
    await db_instance.db.attendance.create_index(
        [("employee_id", 1), ("date", 1)],
        unique=True
    )
    await db_instance.db.attendance.create_index("date")
    await db_instance.db.attendance.create_index("status")
    
    yield
    
    if db_instance.client:
        db_instance.client.close()


app = FastAPI(
    title="HROne Employee Attendance & Analytics API",
    version="1.0.0",
    description="Attendance tracking, audit logs, and aggregation analytics using FastAPI and MongoDB",
    lifespan=lifespan
)


class EmployeeCreateRequest(BaseModel):
    employee_id: str = Field(..., example="EMP101")
    name: str = Field(..., example="Rohit Sharma")
    email: str = Field(..., example="rohit.sharma@example.com")
    department: str = Field(..., example="Engineering")
    designation: str = Field(..., example="Software Engineer")


class PunchInRequest(BaseModel):
    employee_id: str = Field(..., example="EMP101")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional UTC timestamp. If omitted, current UTC time is used."
    )


class PunchOutRequest(BaseModel):
    employee_id: str = Field(..., example="EMP101")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional UTC timestamp. If omitted, current UTC time is used."
    )


class ManualCorrectionRequest(BaseModel):
    employee_id: str = Field(..., example="EMP101")
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", example="2026-10-12")
    punch_in: datetime = Field(..., description="Corrected punch-in timestamp (UTC)")
    punch_out: datetime = Field(..., description="Corrected punch-out timestamp (UTC)")
    reason: str = Field(..., min_length=5, example="Biometric scanner network timeout")
    corrected_by: str = Field(..., example="HR_ADMIN_01")


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TIMEZONE)


def compute_attendance_metrics(punch_in_utc: datetime, punch_out_utc: datetime):
    if punch_out_utc < punch_in_utc:
        raise ValueError("Punch-out time cannot be earlier than punch-in time")

    duration_seconds = (punch_out_utc - punch_in_utc).total_seconds()
    total_hours = round(duration_seconds / 3600.0, 2)
    work_duration_minutes = int(duration_seconds // 60)

    if total_hours >= FULL_DAY_MIN_HOURS:
        status_val = "PRESENT"
    elif total_hours >= HALF_DAY_MIN_HOURS:
        status_val = "HALF_DAY"
    else:
        status_val = "INSUFFICIENT_HOURS"

    overtime_hours = round(max(0.0, total_hours - FULL_DAY_MIN_HOURS), 2)

    ist_in = to_ist(punch_in_utc)
    grace_cutoff = time(
        SHIFT_START_TIME.hour,
        SHIFT_START_TIME.minute + GRACE_PERIOD_MINUTES
    )
    is_late = ist_in.time() > grace_cutoff

    return {
        "total_hours": total_hours,
        "work_duration_minutes": work_duration_minutes,
        "status": status_val,
        "overtime_hours": overtime_hours,
        "is_late": is_late
    }


def serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


@app.post("/api/v1/employees", status_code=status.HTTP_201_CREATED, tags=["Employees"])
async def create_employee(emp: EmployeeCreateRequest):
    db = await get_db()
    existing = await db.employees.find_one({"employee_id": emp.employee_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Employee with ID {emp.employee_id} already exists"
        )
    
    doc = emp.model_dump()
    doc["created_at"] = get_utc_now()
    doc["is_active"] = True
    result = await db.employees.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return {"message": "Employee created successfully", "employee": doc}


@app.get("/api/v1/employees", tags=["Employees"])
async def list_employees():
    db = await get_db()
    cursor = db.employees.find({})
    employees = [serialize_doc(doc) async for doc in cursor]
    return employees


@app.post("/api/v1/attendance/punch-in", tags=["Attendance"])
async def punch_in(payload: PunchInRequest):
    db = await get_db()
    
    emp = await db.employees.find_one({"employee_id": payload.employee_id, "is_active": True})
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active employee with ID {payload.employee_id} not found"
        )

    punch_time_utc = payload.timestamp if payload.timestamp else get_utc_now()
    if punch_time_utc.tzinfo is None:
        punch_time_utc = punch_time_utc.replace(tzinfo=timezone.utc)

    ist_time = to_ist(punch_time_utc)
    work_date = ist_time.strftime("%Y-%m-%d")

    grace_cutoff = time(SHIFT_START_TIME.hour, SHIFT_START_TIME.minute + GRACE_PERIOD_MINUTES)
    is_late = ist_time.time() > grace_cutoff

    existing = await db.attendance.find_one({
        "employee_id": payload.employee_id,
        "date": work_date
    })

    if existing:
        if existing.get("punch_in") is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee {payload.employee_id} has already punched in for {work_date} at {existing['punch_in'].isoformat()}"
            )
        await db.attendance.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "punch_in": punch_time_utc,
                    "is_late": is_late,
                    "status": "IN_PROGRESS",
                    "updated_at": get_utc_now()
                }
            }
        )
        record = await db.attendance.find_one({"_id": existing["_id"]})
        return {"message": "Punch-in recorded successfully", "attendance": serialize_doc(record)}

    attendance_doc = {
        "employee_id": payload.employee_id,
        "date": work_date,
        "punch_in": punch_time_utc,
        "punch_out": None,
        "total_hours": 0.0,
        "work_duration_minutes": 0,
        "status": "IN_PROGRESS",
        "is_late": is_late,
        "overtime_hours": 0.0,
        "audit_trail": [],
        "created_at": get_utc_now(),
        "updated_at": get_utc_now()
    }

    result = await db.attendance.insert_one(attendance_doc)
    attendance_doc["_id"] = str(result.inserted_id)
    return {
        "message": "Punch-in recorded successfully",
        "attendance": attendance_doc
    }


@app.post("/api/v1/attendance/punch-out", tags=["Attendance"])
async def punch_out(payload: PunchOutRequest):
    db = await get_db()
    
    punch_time_utc = payload.timestamp if payload.timestamp else get_utc_now()
    if punch_time_utc.tzinfo is None:
        punch_time_utc = punch_time_utc.replace(tzinfo=timezone.utc)

    ist_time = to_ist(punch_time_utc)
    work_date = ist_time.strftime("%Y-%m-%d")

    existing = await db.attendance.find_one({
        "employee_id": payload.employee_id,
        "date": work_date
    })

    if not existing or existing.get("punch_in") is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No active punch-in found for employee {payload.employee_id} on {work_date}"
        )

    if existing.get("punch_out") is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Employee {payload.employee_id} has already punched out for {work_date} at {existing['punch_out'].isoformat()}"
        )

    punch_in_utc = existing["punch_in"]
    if punch_in_utc.tzinfo is None:
        punch_in_utc = punch_in_utc.replace(tzinfo=timezone.utc)

    if punch_time_utc < punch_in_utc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Punch-out timestamp cannot be earlier than punch-in timestamp"
        )

    metrics = compute_attendance_metrics(punch_in_utc, punch_time_utc)

    await db.attendance.update_one(
        {"_id": existing["_id"]},
        {
            "$set": {
                "punch_out": punch_time_utc,
                "total_hours": metrics["total_hours"],
                "work_duration_minutes": metrics["work_duration_minutes"],
                "status": metrics["status"],
                "overtime_hours": metrics["overtime_hours"],
                "updated_at": get_utc_now()
            }
        }
    )

    updated_record = await db.attendance.find_one({"_id": existing["_id"]})
    return {
        "message": "Punch-out recorded successfully",
        "attendance": serialize_doc(updated_record)
    }


@app.post("/api/v1/attendance/correction", tags=["Attendance"])
async def manual_correction(payload: ManualCorrectionRequest):
    db = await get_db()
    
    emp = await db.employees.find_one({"employee_id": payload.employee_id})
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {payload.employee_id} not found"
        )

    p_in = payload.punch_in if payload.punch_in.tzinfo else payload.punch_in.replace(tzinfo=timezone.utc)
    p_out = payload.punch_out if payload.punch_out.tzinfo else payload.punch_out.replace(tzinfo=timezone.utc)

    try:
        metrics = compute_attendance_metrics(p_in, p_out)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    existing = await db.attendance.find_one({
        "employee_id": payload.employee_id,
        "date": payload.date
    })

    now_utc = get_utc_now()

    if existing:
        previous_state = {
            "punch_in": existing.get("punch_in").isoformat() if existing.get("punch_in") else None,
            "punch_out": existing.get("punch_out").isoformat() if existing.get("punch_out") else None,
            "total_hours": existing.get("total_hours"),
            "status": existing.get("status")
        }

        new_state = {
            "punch_in": p_in.isoformat(),
            "punch_out": p_out.isoformat(),
            "total_hours": metrics["total_hours"],
            "status": metrics["status"]
        }

        audit_entry = {
            "corrected_by": payload.corrected_by,
            "corrected_at": now_utc,
            "reason": payload.reason,
            "previous_state": previous_state,
            "new_state": new_state
        }

        await db.attendance.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "punch_in": p_in,
                    "punch_out": p_out,
                    "total_hours": metrics["total_hours"],
                    "work_duration_minutes": metrics["work_duration_minutes"],
                    "status": metrics["status"],
                    "overtime_hours": metrics["overtime_hours"],
                    "is_late": metrics["is_late"],
                    "updated_at": now_utc
                },
                "$push": {
                    "audit_trail": audit_entry
                }
            }
        )
        record = await db.attendance.find_one({"_id": existing["_id"]})
        return {
            "message": "Attendance record corrected successfully with audit log",
            "attendance": serialize_doc(record)
        }

    else:
        audit_entry = {
            "corrected_by": payload.corrected_by,
            "corrected_at": now_utc,
            "reason": payload.reason,
            "previous_state": None,
            "new_state": {
                "punch_in": p_in.isoformat(),
                "punch_out": p_out.isoformat(),
                "total_hours": metrics["total_hours"],
                "status": metrics["status"]
            }
        }

        new_doc = {
            "employee_id": payload.employee_id,
            "date": payload.date,
            "punch_in": p_in,
            "punch_out": p_out,
            "total_hours": metrics["total_hours"],
            "work_duration_minutes": metrics["work_duration_minutes"],
            "status": metrics["status"],
            "is_late": metrics["is_late"],
            "overtime_hours": metrics["overtime_hours"],
            "audit_trail": [audit_entry],
            "created_at": now_utc,
            "updated_at": now_utc
        }

        res = await db.attendance.insert_one(new_doc)
        new_doc["_id"] = str(res.inserted_id)
        return {
            "message": "Manual attendance record created with audit log",
            "attendance": new_doc
        }


@app.get("/api/v1/analytics/daily-summary", tags=["Analytics"])
async def get_daily_summary(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", example="2026-10-12")):
    db = await get_db()
    
    total_active_employees = await db.employees.count_documents({"is_active": True})

    pipeline = [
        {"$match": {"date": date}},
        {
            "$group": {
                "_id": None,
                "total_punches": {"$sum": 1},
                "present_count": {
                    "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                },
                "half_day_count": {
                    "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                },
                "late_count": {
                    "$sum": {"$cond": ["$is_late", 1, 0]}
                },
                "total_hours_worked": {"$sum": "$total_hours"},
                "avg_hours_worked": {"$avg": "$total_hours"},
                "total_overtime_hours": {"$sum": "$overtime_hours"}
            }
        }
    ]

    cursor = db.attendance.aggregate(pipeline)
    results = await cursor.to_list(length=1)

    if not results:
        return {
            "date": date,
            "total_active_employees": total_active_employees,
            "total_punches": 0,
            "present_count": 0,
            "half_day_count": 0,
            "absent_count": total_active_employees,
            "late_count": 0,
            "total_hours_worked": 0.0,
            "avg_hours_worked": 0.0,
            "total_overtime_hours": 0.0
        }

    data = results[0]
    total_punched = data["total_punches"]
    absent_count = max(0, total_active_employees - total_punched)

    return {
        "date": date,
        "total_active_employees": total_active_employees,
        "total_punches": total_punched,
        "present_count": data["present_count"],
        "half_day_count": data["half_day_count"],
        "absent_count": absent_count,
        "late_count": data["late_count"],
        "total_hours_worked": round(data["total_hours_worked"], 2),
        "avg_hours_worked": round(data["avg_hours_worked"] or 0.0, 2),
        "total_overtime_hours": round(data["total_overtime_hours"], 2)
    }


@app.get("/api/v1/analytics/employee/{employee_id}/monthly", tags=["Analytics"])
async def get_employee_monthly_report(
    employee_id: str,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", example="2026-10")
):
    db = await get_db()
    
    emp = await db.employees.find_one({"employee_id": employee_id})
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee {employee_id} not found"
        )

    pipeline = [
        {
            "$match": {
                "employee_id": employee_id,
                "date": {"$regex": f"^{month}"}
            }
        },
        {
            "$group": {
                "_id": "$employee_id",
                "days_recorded": {"$sum": 1},
                "full_days": {
                    "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                },
                "half_days": {
                    "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                },
                "late_arrivals": {
                    "$sum": {"$cond": ["$is_late", 1, 0]}
                },
                "total_hours": {"$sum": "$total_hours"},
                "avg_daily_hours": {"$avg": "$total_hours"},
                "total_overtime_hours": {"$sum": "$overtime_hours"}
            }
        }
    ]

    cursor = db.attendance.aggregate(pipeline)
    results = await cursor.to_list(length=1)

    if not results:
        return {
            "employee_id": employee_id,
            "employee_name": emp["name"],
            "month": month,
            "days_recorded": 0,
            "full_days": 0,
            "half_days": 0,
            "late_arrivals": 0,
            "total_hours": 0.0,
            "avg_daily_hours": 0.0,
            "total_overtime_hours": 0.0
        }

    data = results[0]
    return {
        "employee_id": employee_id,
        "employee_name": emp["name"],
        "month": month,
        "days_recorded": data["days_recorded"],
        "full_days": data["full_days"],
        "half_days": data["half_days"],
        "late_arrivals": data["late_arrivals"],
        "total_hours": round(data["total_hours"], 2),
        "avg_daily_hours": round(data["avg_daily_hours"] or 0.0, 2),
        "total_overtime_hours": round(data["total_overtime_hours"], 2)
    }


@app.get("/api/v1/analytics/department-summary", tags=["Analytics"])
async def get_department_summary(month: str = Query(..., pattern=r"^\d{4}-\d{2}$", example="2026-10")):
    db = await get_db()

    pipeline = [
        {
            "$match": {
                "date": {"$regex": f"^{month}"}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "employee_id",
                "foreignField": "employee_id",
                "as": "emp_details"
            }
        },
        {"$unwind": "$emp_details"},
        {
            "$group": {
                "_id": "$emp_details.department",
                "unique_employees": {"$addToSet": "$employee_id"},
                "total_work_sessions": {"$sum": 1},
                "present_count": {
                    "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                },
                "half_day_count": {
                    "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                },
                "total_late_arrivals": {
                    "$sum": {"$cond": ["$is_late", 1, 0]}
                },
                "total_hours_worked": {"$sum": "$total_hours"},
                "avg_hours_per_session": {"$avg": "$total_hours"},
                "total_overtime_hours": {"$sum": "$overtime_hours"}
            }
        },
        {
            "$project": {
                "department": "$_id",
                "active_employees_count": {"$size": "$unique_employees"},
                "total_work_sessions": 1,
                "present_count": 1,
                "half_day_count": 1,
                "total_late_arrivals": 1,
                "total_hours_worked": {"$round": ["$total_hours_worked", 2]},
                "avg_hours_per_session": {"$round": ["$avg_hours_per_session", 2]},
                "total_overtime_hours": {"$round": ["$total_overtime_hours", 2]},
                "_id": 0
            }
        },
        {"$sort": {"department": 1}}
    ]

    cursor = db.attendance.aggregate(pipeline)
    summary = await cursor.to_list(length=100)
    return {
        "month": month,
        "department_count": len(summary),
        "departments": summary
    }


@app.get("/health", tags=["Health"])
async def health_check():
    db = await get_db()
    await db.command("ping")
    return {"status": "ok", "database": "connected"}