"""Colored terminal logger with progress indicators."""


class Logger:
    @staticmethod
    def header(msg: str) -> None:
        print(f"\n{'='*60}")
        print(f"  {msg}")
        print(f"{'='*60}")

    @staticmethod
    def info(msg: str) -> None:
        print(f"  {msg}")

    @staticmethod
    def step(msg: str) -> None:
        print(f"  -> {msg}")

    @staticmethod
    def success(msg: str) -> None:
        print(f"  [OK] {msg}")

    @staticmethod
    def warning(msg: str) -> None:
        print(f"  [WARN] {msg}")

    @staticmethod
    def error(msg: str) -> None:
        print(f"  [ERR] {msg}")
