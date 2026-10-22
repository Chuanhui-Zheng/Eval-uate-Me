"""Template-based support reply oracle.

Produces a canned but complete reply for each ticket category and urgency.
Used as the reference target for selftest and meta-eval; not intended as a
useful production agent.
"""
from __future__ import annotations

from evalharness import Case, TargetOutput, register_target
from evalharness.targets import Target

_TEMPLATES: dict[tuple[str, str], str] = {
    ("account_access", "high"): (
        "I'm sorry to hear you're locked out — I understand this is urgent. "
        "Please try the following steps right now: (1) clear your browser cache and cookies, "
        "(2) try in an incognito/private window, (3) check that Caps Lock is off. "
        "If you're still blocked, please use our live chat for immediate assistance — "
        "our team can manually unlock your account within minutes."
    ),
    ("account_access", "medium"): (
        "Thank you for reaching out. We can help resolve this. "
        "Please try resetting your password via the 'Forgot Password' link and check your spam folder "
        "for the reset email. If the issue persists, reply here with your registered email address "
        "and we'll investigate directly."
    ),
    ("account_access", "low"): (
        "Thank you for your message. We've received your request and will process it "
        "in accordance with our standard procedures. You'll receive a confirmation email "
        "once the action has been completed, typically within 1-3 business days."
    ),
    ("billing", "high"): (
        "I sincerely apologise for the billing issue — this should not have happened. "
        "I'm escalating this to our billing team immediately for urgent review. "
        "We will verify the charges and issue any applicable refund within 1-2 business days. "
        "You will receive an email confirmation once the refund has been processed."
    ),
    ("billing", "medium"): (
        "Thank you for bringing this to our attention. I'll have our billing team investigate "
        "the charge right away. You can also review your billing history in Account > Billing. "
        "If a refund is due, it will be processed within 5-7 business days."
    ),
    ("billing", "low"): (
        "Thank you for your enquiry. I've noted your request and our billing team will "
        "follow up with you shortly. If you need anything in the meantime, "
        "please don't hesitate to reach out."
    ),
    ("bug", "high"): (
        "I'm sorry for the disruption — this is a known issue and our engineering team "
        "is working on a fix as a priority. In the meantime, please try the workaround "
        "described below. I'll send you a direct update as soon as the fix is deployed. "
        "Thank you for your patience."
    ),
    ("bug", "medium"): (
        "Thank you for reporting this. I've logged it with our engineering team "
        "and can confirm it is under investigation. I'll follow up once I have "
        "an estimated resolution time. In the meantime, please let me know if "
        "you need any assistance working around the issue."
    ),
    ("bug", "low"): (
        "Thank you for letting us know. I've passed this along to our engineering team "
        "for investigation. We'll keep you updated on progress. "
        "Please feel free to reach out if the issue worsens or you need further help."
    ),
    ("feature_request", "low"): (
        "Thank you for the suggestion — we really appreciate feedback from our users! "
        "I've logged your request with our product team. While I can't promise a specific "
        "timeline, all feature requests are reviewed as part of our roadmap planning. "
        "We'll reach out if this makes it onto the schedule."
    ),
    ("how_to", "high"): (
        "Happy to help with this urgently. Here are the steps: please follow the instructions "
        "below carefully. If you run into any difficulty, reply here immediately and "
        "we'll walk you through it in real time."
    ),
    ("how_to", "medium"): (
        "Great question! Here's how to do it: please follow the steps outlined below. "
        "If you need any clarification or run into issues, feel free to reply and we'll help."
    ),
    ("how_to", "low"): (
        "Thanks for asking! Here's a quick overview of how that works. "
        "You can also find more detail in our documentation. "
        "Let us know if you have any follow-up questions."
    ),
}

_DEFAULT = (
    "Thank you for reaching out to our support team. I've received your message and "
    "will look into this for you. I'll follow up with more information shortly. "
    "Please don't hesitate to let us know if you need anything in the meantime."
)


@register_target("support_reply")
class SupportReplyTarget(Target):
    """Template oracle — produces a canned reply based on category and urgency."""

    evalharness_api = 1

    def __init__(self, flaw: str | None = None, **_: object) -> None:
        self.flaw = flaw

    def run(self, case: Case) -> TargetOutput:
        inp = case.input if isinstance(case.input, dict) else {}
        category = inp.get("category", "")
        urgency = inp.get("urgency", "medium")

        reply = _TEMPLATES.get((category, urgency), _DEFAULT)

        if self.flaw == "dismissive":
            reply = "Please check the FAQ and try again. We cannot assist with this issue at this time."
        elif self.flaw == "wrong_tone":
            reply = "This is not our fault. You should have read the documentation before contacting support."
        elif self.flaw == "empty":
            reply = ""
        elif self.flaw == "no_action":
            reply = "Thank you for your message. We will look into this."

        return TargetOutput(output={"reply": reply})
