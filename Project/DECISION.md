# Architectural Decisions & Technical Rationale

This document outlines the core architectural and design decisions made for the Employee Attendance & Analytics API.

---

## 1. Schema Design: Embedded vs. Referenced Documents

### Decision
1. **Separation of `employees` and `attendance` Collections**:
   - `employees` contains master metadata (`employee_id`, `name`, `department`, `shift`).
   - `attendance` contains daily transactional records (`employee_id`, `date`, `punch_in`, `punch_out`, `total_hours`, `status`).
   - **Rationale**: Daily attendance grows rapidly ($N \times 365$ records per year). Embedding daily records inside an employee document would exceed MongoDB's **16 MB BSON document limit**.

2. **Embedded `audit_trail` Inside `attendance`**:
   - Manual corrections are stored inside the `attendance` document as an array.
   - **Rationale**: Manual corrections are bounded (rarely exceed 2–3 per day) and single-document reads remain fast ($O(1)$).

---

## 2. Concurrency & Race Condition Prevention

### Decision
- **Compound Unique Index**:
  ```javascript
  db.attendance.createIndex({ "employee_id": 1, "date": 1 }, { unique: true })