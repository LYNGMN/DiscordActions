"""Shared delivery loop for the Google News handlers.

The queue preparation differs per handler, but the failure handling must not.
Keeping the delivery loop in one place means a fix to deadline handling or
permanent-error reporting applies to every profile.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from delivery_admin_alert import notify_admin


@dataclass(frozen=True)
class DeliveryBatchResult:
    processed_count: int
    failed: bool = False
    error_code: Optional[str] = None


def deliver_queued_items(
    queued_items: Sequence[Tuple[str, str]],
    delivery_limit: int,
    deliver: Callable[[str], None],
    profile_label: str,
    admin_webhook: str = "",
    notify: Callable[..., bool] = notify_admin,
) -> DeliveryBatchResult:
    """Deliver queued GUIDs up to the limit and report the first failure.

    A run-deadline error is expected work deferral, not a delivery failure, so
    it does not notify the admin. Any other error keeps the message pending and
    stops the profile for this run.
    """
    processed = 0
    for guid, title in list(queued_items)[: max(0, int(delivery_limit))]:
        try:
            deliver(guid)
            processed += 1
            logging.info("뉴스 항목 처리 완료: %s", title)
        except Exception as error:
            error_code = getattr(error, "error_code", "profile_run_failed")
            logging.error(
                "뉴스 항목 전송 실패 (오류 유형: %s)", type(error).__name__
            )
            if error_code == "run_deadline_exceeded":
                return DeliveryBatchResult(processed, True, error_code)
            print(
                "::warning title=Google News delivery failed::"
                "A queued delivery remains pending"
            )
            notify(
                admin_webhook,
                "Google News",
                profile_label,
                guid,
                getattr(error, "error_code", "final_failure"),
            )
            return DeliveryBatchResult(processed, True, error_code)
    return DeliveryBatchResult(processed)
