"""Trusted, deterministic customer messages for critical moments (no LLM text, no amounts, no promises)."""

from __future__ import annotations

FIELD_LABELS = {"governorate": "المحافظة", "city": "المدينة أو المنطقة", "street": "اسم الشارع",
                "building": "رقم العمارة", "customer_name": "الاسم", "phone": "رقم موبايل صحيح"}


def ready_notice(order_id: str) -> str:
    return f"تم تأكيد طلبك {order_id} وهيتجهز للشحن. الدفع عند الاستلام. شكرًا لثقتك في StyleHub Egypt."


def escalation_notice(order_id: str) -> str:
    return f"شكرًا لرسالتك. زميل من فريق StyleHub هيتواصل معاك بخصوص طلبك {order_id}."


def fallback_message(order_id: str, agent_outcome: str | None, decision: dict) -> tuple[str, str]:
    """(kind, text) for a customer message the agent left unanswered, chosen from authoritative state."""
    if agent_outcome == "ESCALATE_TO_HUMAN":
        return "ESCALATION_NOTICE", escalation_notice(order_id)
    if agent_outcome == "READY_FOR_DISPATCH":
        return "INFO", ready_notice(order_id)
    action, details = decision.get("next_action"), decision.get("details", {})
    if action == "AWAIT_CONFIRMATION":
        return "INFO", (f"لو موافق على ملخص طلبك {order_id} اللي بعتناه، رد بكلمة (تمام). "
                        "ولو حابب تغيّر حاجة قولنا إيه هي.")
    if action == "ASK_CLARIFICATION" and details.get("missing_fields"):
        labels = "، ".join(FIELD_LABELS.get(f, f) for f in details["missing_fields"])
        return "CLARIFICATION", f"عشان نكمل طلبك {order_id} محتاجين: {labels}."
    if action == "OFFER_ALTERNATIVES" and details.get("alternatives"):
        sizes = sorted({a["size"] for alts in details["alternatives"].values() for a in alts})
        if sizes:
            return "CLARIFICATION", (f"المقاس المطلوب في طلبك {order_id} مش متاح حاليًا. "
                                     f"المتاح من نفس المنتج: مقاس {' أو '.join(sizes)}. تحب أنهي؟")
    return "INFO", f"استلمنا رسالتك بخصوص طلبك {order_id}، وبنراجع التفاصيل وهنرجعلك قريب."
