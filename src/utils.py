import logging
import time

log = logging.getLogger("retry")


def retry(fn, attempts=3, delay=5, backoff=2, what="step"):
    """Run fn(); on exception wait and retry. Re-raises after the last attempt."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed (attempt %d/%d): %s", what, i, attempts, e)
            if i == attempts:
                raise
            time.sleep(delay * backoff ** (i - 1))
