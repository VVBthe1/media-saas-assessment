class AppError(Exception):
    code: str = "internal_error"
    message: str = "Something went wrong"
    status_code: int = 500

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)
