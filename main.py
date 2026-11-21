import asyncio
from core.router import build_creed_engine
from utils.logger import setup_logger
from version import VERSION


def boot():
    logger = setup_logger()

    print(f"CREED v{VERSION} initialized")
    logger.info("Boot Sequence Started")

    creed = build_creed_engine()
    try:
        asyncio.run(creed.run())
    except KeyboardInterrupt:
        print("\nCreed shutting down.")
    finally:
        creed.shutdown()
        logger.info("Boot Complete")


if __name__ == "__main__":
    boot()
