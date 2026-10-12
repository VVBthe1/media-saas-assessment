from backend.exceptions import AppError


class TaskNotFound(AppError):
    code = "task_not_found"
    message = "Task not found"
    status_code = 404
