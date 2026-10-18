"""Case facts are rendered from tools, not guessed by a second LLM or replayed tools."""

import json
import re

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.guardrails.input import redact

CASE_TOOLS = {"report_delivery_issue", "lookup_dispute", "lookup_order_dispute"}
LABELS = {
    "en": (
        "Case",
        "Order",
        "Status",
        "Proposed action",
        "Missing information",
        "Policy",
        "Approved amount",
        "minor units",
    ),
    "hi": (
        "मामला",
        "ऑर्डर",
        "स्थिति",
        "प्रस्तावित कार्रवाई",
        "आवश्यक जानकारी",
        "नीति",
        "स्वीकृत राशि",
        "लघु इकाइयाँ",
    ),
    "mr": (
        "प्रकरण",
        "ऑर्डर",
        "स्थिती",
        "प्रस्तावित कृती",
        "आवश्यक माहिती",
        "धोरण",
        "मंजूर रक्कम",
        "लहान एकके",
    ),
    "ta": (
        "வழக்கு",
        "ஆர்டர்",
        "நிலை",
        "முன்மொழிவு",
        "தேவையான தகவல்",
        "கொள்கை",
        "அனுமதித்த தொகை",
        "சிறிய அலகுகள்",
    ),
    "te": ("కేసు", "ఆర్డర్", "స్థితి", "ప్రతిపాదన", "అవసరమైన సమాచారం", "విధానం", "ఆమోదిత మొత్తం", "చిన్న యూనిట్లు"),
}
NEXT = {
    "en": {
        "awaiting_review": "A support reviewer must assess the proposal. This is not refund approval.",
        "awaiting_investigation": "Support must gather the missing evidence before a decision.",
        "approved": "A reviewer approved a simulated refund. Execution is still pending.",
        "rejected": "The reviewer rejected the case. Contact support for reconsideration.",
        "resolved": "The simulated refund is complete. No real money was moved.",
    },
    "hi": {
        "awaiting_review": "प्रस्ताव की सहायता समीक्षक द्वारा समीक्षा आवश्यक है। रिफंड स्वीकृत नहीं हुआ है।",
        "awaiting_investigation": "निर्णय से पहले सहायता टीम को आवश्यक प्रमाण जुटाने हैं।",
        "approved": "समीक्षक ने सिम्युलेटेड रिफंड स्वीकृत किया है। निष्पादन अभी बाकी है।",
        "rejected": "समीक्षक ने मामला अस्वीकार किया है। पुनर्विचार के लिए सहायता से संपर्क करें।",
        "resolved": "सिम्युलेटेड रिफंड पूरा हुआ। कोई वास्तविक पैसा नहीं भेजा गया।",
    },
    "mr": {
        "awaiting_review": "सहाय्य समीक्षकाची समीक्षा आवश्यक आहे. परतावा अद्याप मंजूर नाही.",
        "awaiting_investigation": "निर्णयापूर्वी आवश्यक पुरावे गोळा करणे गरजेचे आहे.",
        "approved": "सिम्युलेटेड परतावा मंजूर आहे. अंमलबजावणी अद्याप बाकी आहे.",
        "rejected": "प्रकरण नाकारले आहे. पुनर्विचारासाठी सहाय्याशी संपर्क साधा.",
        "resolved": "सिम्युलेटेड परतावा पूर्ण झाला. वास्तविक पैसे पाठवले नाहीत.",
    },
    "ta": {
        "awaiting_review": "ஆதரவு மதிப்பாய்வாளர் பரிசீலிக்க வேண்டும். பணத்திருப்பம் இன்னும் அனுமதிக்கப்படவில்லை.",
        "awaiting_investigation": "முடிவுக்கு முன் தேவையான சான்றுகளை சேகரிக்க வேண்டும்.",
        "approved": "உருவக பணத்திருப்பம் அனுமதிக்கப்பட்டது. செயல்படுத்துதல் நிலுவையில் உள்ளது.",
        "rejected": "வழக்கு நிராகரிக்கப்பட்டது. மறுபரிசீலனைக்கு ஆதரவை அணுகவும்.",
        "resolved": "உருவக பணத்திருப்பம் முடிந்தது. உண்மையான பணம் அனுப்பப்படவில்லை.",
    },
    "te": {
        "awaiting_review": "సహాయ సమీక్షకుడు పరిశీలించాలి. రీఫండ్ ఇంకా ఆమోదించబడలేదు.",
        "awaiting_investigation": "నిర్ణయానికి ముందు అవసరమైన ఆధారాలు సేకరించాలి.",
        "approved": "అనుకరణ రీఫండ్ ఆమోదించబడింది. అమలు ఇంకా పెండింగ్‌లో ఉంది.",
        "rejected": "కేసు తిరస్కరించబడింది. పునఃపరిశీలన కోసం సహాయాన్ని సంప్రదించండి.",
        "resolved": "అనుకరణ రీఫండ్ పూర్తయింది. నిజమైన డబ్బు పంపబడలేదు.",
    },
}


def current_tool_facts(messages):
    start = max(
        (i for i, message in enumerate(messages) if isinstance(message, HumanMessage)), default=-1
    )
    facts = []
    for message in messages[start + 1 :]:
        if isinstance(message, ToolMessage):
            try:
                payload = json.loads(message.content)
            except (ValueError, TypeError):
                continue
            facts.append((message.name, payload))
    return facts


def violations(answer, facts):
    """Audit rubric; conservative patterns are not a complete semantic verifier."""
    case = next(
        (
            payload
            for name, payload in reversed(facts)
            if name in CASE_TOOLS and isinstance(payload, dict) and payload.get("case_id")
        ),
        None,
    )
    issues = []
    # Evaluate affirmative clauses; do not flag explicit denials as issued refunds.
    affirmative = " ".join(
        sentence
        for sentence in re.split(r"[.!?।]\s*", answer)
        if not re.search(
            r"\b(?:not|never|no|pending|cannot|hasn't|haven't)\b|नहीं|बाकी", sentence, re.I
        )
    )
    if re.search(
        r"\b(?:refund (?:was |has been |is )?(?:issued|processed|sent|executed)|refunded|money (?:was |has been )?(?:sent|moved))\b",
        affirmative,
        re.I,
    ):
        issues.append("unverified_payment_claim")
    if re.search(
        r"refund (?:is |was |has been )?approved|approved (?:your |the )?refund", affirmative, re.I
    ):
        if not case or case.get("status") not in {"approved", "resolved"}:
            issues.append("unverified_approval")
    if re.search(r"[$€£₹]|\b(?:USD|EUR|GBP|INR)\b", answer):
        issues.append("invented_currency")
    if case:
        expected = case.get("approved_amount_cents")
        if expected is None and case.get("simulated_refund"):
            expected = case["simulated_refund"].get("amount_cents")
        for amount in re.findall(
            r"([\d,]+)\s+minor units|amount(?:_cents)?[\s:=]+([\d,]+)", answer, re.I
        ):
            if expected is None or int((amount[0] or amount[1]).replace(",", "")) != expected:
                issues.append("amount_mismatch")
        for status in [
            "awaiting_review",
            "awaiting_investigation",
            "approved",
            "rejected",
            "resolved",
        ]:
            if (
                re.search(rf"\bstatus\s*[:=]\s*{status}\b", answer, re.I)
                and status != case["status"]
            ):
                issues.append("status_mismatch")
    return sorted(set(issues))


def render_case(case, language="en"):
    labels = LABELS.get(language, LABELS["en"])
    missing = ", ".join(case.get("missing_information") or []) or "none"
    rows = [
        f"{labels[0]}: {case['case_id']}. {labels[1]}: {case.get('order_id', 'unknown')}.",
        f"{labels[2]}: {case['status']}.",
        f"{labels[3]}: {case.get('proposed_action', 'unknown')}. {labels[4]}: {missing}.",
        NEXT.get(language, NEXT["en"]).get(case["status"], "Contact support for the next step."),
    ]
    if case.get("approved_amount_cents") is not None:
        rows.append(f"{labels[6]}: {case['approved_amount_cents']} {labels[7]}.")
    rows.append(
        f"{labels[5]}: {case.get('policy_version', 'unknown')} ({case.get('policy_source', 'unknown')})."
    )
    if case.get("reused"):
        rows.insert(
            0, "Existing case found." if language == "en" else "Existing case / मौजूदा मामला."
        )
    if case.get("notifications_enabled"):
        rows.append("Status emails are queued on changes; delivery is not guaranteed.")
    elif language == "hi":
        rows.append("स्थिति जानने के लिए यहाँ पूछें।")
    else:
        rows.append("Automatic email updates are not enabled for this case. Ask for status here.")
    return "\n".join(rows)


def verify_answer(answer, facts, language="en"):
    before = violations(answer, facts)
    case = next(
        (
            payload
            for name, payload in reversed(facts)
            if name in CASE_TOOLS and isinstance(payload, dict) and payload.get("case_id")
        ),
        None,
    )
    # Returning a verbatim structured tool result is already evidence-bound.
    structured = any(answer.strip() == json.dumps(payload) for _, payload in facts)
    if case and not structured:
        latest_name = next(name for name, payload in reversed(facts) if payload is case)
        if latest_name != "report_delivery_issue":
            case = {**case, "reused": True}
        safe = render_case(case, language)
    elif before:
        safe = "I cannot verify a refund or payment from the available evidence. Ask for your current case status."
    else:
        safe = answer
    safe, pii = redact(safe)
    return safe, {
        "version": "supportflow-guardrails-v1",
        "before": before,
        "after": violations(safe, facts),
        "rewritten": safe != answer,
        "output_redactions": pii,
    }


async def enforce_result(graph, result, thread, language="en"):
    messages = result["messages"]
    final = messages[-1]
    safe, report = verify_answer(str(final.content), current_tool_facts(messages), language)
    if report["rewritten"]:
        replacement = (
            final.model_copy(update={"content": safe})
            if isinstance(final, AIMessage)
            else AIMessage(content=safe)
        )
        result = {**result, "messages": [*messages[:-1], replacement]}
        if getattr(graph, "checkpointer", None) and getattr(final, "id", None):
            await graph.aupdate_state(
                {"configurable": {"thread_id": thread}}, {"messages": [replacement]}
            )
    return {**result, "guardrails": report}
