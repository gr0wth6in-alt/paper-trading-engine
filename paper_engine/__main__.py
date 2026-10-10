import sys

import uvicorn


def main():
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "paper_engine.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        workers=1,
        loop="asyncio",
        ws_max_size=4096,
        timeout_graceful_shutdown=15,
    )


if __name__ == "__main__":
    main()
