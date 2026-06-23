"""Run the approval UI locally."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("ui.app:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
