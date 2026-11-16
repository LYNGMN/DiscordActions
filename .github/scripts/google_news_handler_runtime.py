"""Shared delivery loop for the Google News handlers.

The queue preparation differs per handler, but the failure handling must not.
Keeping the delivery loop in one place means a fix to deadline handling,
permanent-error reporting or event logging applies to every profile.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from delivery_admin_alert import notify_admin
from run_events import emit_event, item_ref


@dataclass(frozen=True)
class DeliveryBatchResult:
    processed_count: int
    failed: bool = False
    error_code: Optional[str] = None


def _error_code(error: Exception, default: str = "profile_run_failed") -> str:
    code = getattr(error, "error_code", None)
    return code if isinstance(code, str) and code else default


def _error_detail(error: Exception):
    return (
        _error_code(error),
        getattr(error, "http_status_code", None),
        getattr(error, "attempt_count", None),
    )


def deliver_queued_items(
    queued_items: Sequence[Tuple[str, str]],
    delivery_limit: int,
    deliver: Callable[[str], None],
    profile_label: str,
    admin_webhook: str = "",
    profile_id: Optional[str] = None,
    notify: Callable[..., bool] = notify_admin,
    emit: Callable[..., None] = emit_event,
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
            emit(
                "item_done",
                profile=profile_id,
                item=item_ref(guid),
                delivered=processed,
            )
            logging.info("뉴스 항목 처리 완료: %s", title)
        except Exception as error:
            code, status, attempt = _error_detail(error)
            emit(
                "item_failed",
                profile=profile_id,
                item=item_ref(guid),
                code=code,
                status=status,
                attempt=attempt,
            )
            logging.error(
                "뉴스 항목 전송 실패 (코드: %s, 상태: %s, 시도: %s, 유형: %s)",
                code,
                status,
                attempt,
                type(error).__name__,
            )
            if code == "run_deadline_exceeded":
                return DeliveryBatchResult(processed, True, code)
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
            return DeliveryBatchResult(processed, True, code)
    return DeliveryBatchResult(processed)
