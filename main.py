from typing import Optional
from fastapi import Depends, FastAPI, HTTPException
from fastapi.params import Query
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, func
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from datetime import datetime, date

DATABASE_URL = "sqlite:///./task.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(String(250), nullable=True)
    priority = Column(String, nullable=False)
    status = Column(String(20), nullable=False)
    due_date = Column(Date, nullable=False)
    completed_at = Column(DateTime, nullable=True)


Base.metadata.create_all(bind=engine)


class CreateTask(BaseModel):
    title: str
    description: Optional[str] = None
    priority: Optional[str] = "high"
    status: Optional[str] = "pending"
    due_date: date
    completed_at: Optional[datetime] = None


class ResponseTask(BaseModel):
    id: int
    title: str
    description: Optional[str]
    priority: Optional[str]
    status: Optional[str]
    due_date: date
    completed_at: Optional[datetime]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/tasks", response_model=ResponseTask)
def create_task(task: CreateTask, db: Session = Depends(get_db)):
    high_priority_count = (
        db.query(UserDB)
        .filter(UserDB.priority == "high", UserDB.status == "pending")
        .count()
    )
    due_date = task.due_date
    if due_date <= date.today():
        raise HTTPException(status_code=400, detail="Possible nahi hein")

    if task.priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority value")

    if task.priority == "high":
        if high_priority_count >= 5:
            raise HTTPException(
                status_code=400, detail="Cannot create more than 5 high priority tasks"
            )

    if task.status not in ["pending", "in_progress", "completed"]:
        raise HTTPException(status_code=400, detail="Invalid status value")

    input_task = UserDB(**task.model_dump())
    db.add(input_task)
    db.commit()
    db.refresh(input_task)
    return input_task


@app.get("/tasks", response_model=list[ResponseTask])
def get_tasks(
    db: Session = Depends(get_db),
    priority: Optional[str] = None,
    status: Optional[str] = None,
    overdue: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    query = db.query(UserDB)

    if priority:
        query = query.filter(UserDB.priority == priority)

    if status:
        query = query.filter(UserDB.status == status)

    if overdue:
        query = query.filter(
            UserDB.due_date < date.today(), UserDB.status != "completed"
        )
    offset = (page - 1) * limit
    tasks = query.offset(offset).limit(limit).all()
    return tasks


@app.get("/tasks/stats")
def get_task_stats(db: Session = Depends(get_db)):

    total = db.query(UserDB.id).count()

    pending = db.query(UserDB.id).filter(UserDB.status == "pending").count()
    in_progress = db.query(UserDB.id).filter(UserDB.status == "in_progress").count()
    completed = db.query(UserDB.id).filter(UserDB.status == "completed").count()

    overdue = (
        db.query(UserDB.id)
        .filter(UserDB.due_date < date.today(), UserDB.status != "completed")
        .count()
    )

    high_priority_pending = (
        db.query(UserDB.id)
        .filter(UserDB.priority == "high", UserDB.status == "pending")
        .count()
    )

    return {
        "total": total or 0,
        "pending": pending or 0,
        "in_progress": in_progress or 0,
        "completed": completed or 0,
        "overdue": overdue or 0,
        "high_priority_pending": high_priority_pending or 0,
    }


@app.get("/tasks/{task_id}", response_model=ResponseTask)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(UserDB).filter(UserDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.put("/tasks/{task_id}", response_model=ResponseTask)
def update_task(task_id: int, updated_task: CreateTask, db: Session = Depends(get_db)):
    high_priority_count = (
        db.query(UserDB)
        .filter(UserDB.priority == "high", UserDB.status == "pending")
        .count()
    )
    task = db.query(UserDB).filter(UserDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if updated_task.due_date <= date.today():
        raise HTTPException(status_code=400, detail="Possible nahi hein")

    if updated_task.priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority value")

    if updated_task.priority == "high":
        if high_priority_count >= 5:
            raise HTTPException(
                status_code=400,
                detail="Cannot update to high priority task as there are already 5 high priority tasks",
            )

    if task.status == "pending" and updated_task.status == "in_progress":
        pass

    elif task.status == "in_progress" and updated_task.status == "completed":
        updated_task.completed_at = datetime.now()

    elif task.status == "completed" and updated_task.status in [
        "pending",
        "in_progress",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Cannot revert status from completed to pending or in_progress",
        )

    elif updated_task.status not in ["pending", "in_progress", "completed"]:
        raise HTTPException(status_code=400, detail="Invalid status value")

    else:
        raise HTTPException(status_code=400, detail="Invalid status transition")

    task.title = updated_task.title
    task.description = updated_task.description
    task.priority = updated_task.priority
    task.status = updated_task.status
    task.due_date = updated_task.due_date
    task.completed_at = updated_task.completed_at
    db.commit()
    db.refresh(task)
    return task


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(UserDB).filter(UserDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"detail": "Task deleted successfully"}
