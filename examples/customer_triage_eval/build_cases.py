"""Rebuild the 100-case demonstration set from the upstream agent's KB contract."""
from __future__ import annotations

import json
from pathlib import Path


OUT = Path(__file__).with_name("cases.jsonl")

BILLING = [
    ("duplicate", "I see the same order charge twice; the second one is still pending.", "What should I expect?"),
    ("duplicate", "My card shows two entries for one purchase and one has not settled.", "Is this a real second charge?"),
    ("duplicate", "There are two authorizations for my order, but only one is completed.", "Can you explain the pending one?"),
    ("duplicate", "I was charged twice for a purchase, although one transaction says pending.", "What do I need to do?"),
    ("duplicate", "One order appears twice on my statement; the newer entry is pending.", "Will it disappear?"),
    ("duplicate", "I noticed a duplicate payment line, with one still awaiting settlement.", "Please advise."),
    ("duplicate", "The same purchase is listed twice, but one charge is not posted yet.", "Should I open a refund?"),
    ("duplicate", "My bank app shows a second pending authorization for the same order.", "How is this handled?"),
    ("duplicate", "I have two card entries for one order and one is marked as a hold.", "Can you check the policy?"),
    ("duplicate", "A duplicate charge is showing, but the second one is still processing.", "What happens next?"),
    ("duplicate", "Two transactions have the same order amount; one is pending and one cleared.", "Do I need to contact support again?"),
    ("duplicate", "My statement has a completed charge and a matching pending charge.", "Is the pending amount temporary?"),
    ("duplicate", "I think I was billed twice, but one line has not settled with my bank.", "What should I do now?"),
    ("duplicate", "The pending authorization looks like a duplicate of my completed order payment.", "Can you explain the timing?"),
    ("duplicate", "There is one settled payment and another identical pending hold.", "Will both be taken?"),
    ("duplicate", "I see a duplicate order payment where one entry is still an authorization.", "How long should I wait?"),
    ("duplicate", "One of the two identical charges on my card is still pending.", "Is that expected?"),
    ("duplicate", "My purchase generated two card entries, though one is only pending.", "What is the correct next step?"),
    ("duplicate", "A second charge appeared for the same order, but it has not cleared.", "Should I request a refund?"),
    ("duplicate", "I have two entries for yesterday's order; one says authorization pending.", "Could you clarify the policy?"),
    ("settled", "Both charges for the same order have fully cleared on my statement.", "How do I get the duplicate refunded?"),
    ("settled", "I was charged twice and both transactions are posted, not pending.", "Please tell me the resolution process."),
    ("settled", "Two completed payments were taken for a single purchase.", "Can the extra one be refunded?"),
    ("settled", "My bank confirms both duplicate order charges have settled.", "What should support do?"),
    ("settled", "The duplicate payment is no longer pending; both charges are final.", "How can I fix this?"),
    ("settled", "I paid twice for one order and both charges are completed.", "Please help with the duplicate."),
    ("settled", "Both identical card transactions have cleared for my purchase.", "Can you open a refund request?"),
    ("settled", "The two charges have posted to my account as completed payments.", "What is the next step?"),
    ("settled", "I can see two settled charges for one order, not a temporary hold.", "How is the duplicate handled?"),
    ("settled", "The bank statement shows the same order charged twice and neither is pending.", "Could you resolve this?"),
    ("settled", "Both payments for this single order are fully processed.", "Should I file a refund ticket?"),
    ("settled", "A duplicate charge has cleared; the second transaction is not an authorization hold.", "What can you do?"),
    ("settled", "Two final charges appear for one purchase on my card.", "Please explain the refund process."),
    ("settled", "I checked with my bank: both duplicate transactions are posted.", "Can this be corrected?"),
    ("settled", "The second payment is completed too, so this is not just pending.", "How should I proceed?"),
    ("settled", "My account was debited twice for the same order and both debits settled.", "Please investigate."),
    ("settled", "Both identical transactions are marked complete on the card account.", "Can I get one reversed?"),
    ("settled", "One order has two completed charges, and the extra charge is settled.", "What is your policy?"),
    ("settled", "The duplicate transaction is fully posted alongside the original payment.", "Please advise on a refund."),
    ("settled", "I have confirmed that both charges cleared rather than one being pending.", "How do I get help?"),
]

TECHNICAL = [
    ("login", "After signing in I keep landing back on the login page.", "I already cleared the browser cache."),
    ("login", "The sign-in form accepts my details but sends me to login again.", "What should I try?"),
    ("login", "I cannot get past the login screen; it loops after authentication.", "My password is correct."),
    ("login", "Every successful sign-in redirects me back to the sign-in page.", "Can you help troubleshoot?"),
    ("login", "The site keeps asking me to log in again right after I sign in.", "I tried refreshing already."),
    ("login", "Authentication seems to work, then the app returns to the login form.", "What steps do you recommend?"),
    ("login", "I am stuck in a login loop on the web app.", "How can I get into my account?"),
    ("login", "Signing in repeatedly takes me back to the same login page.", "I have restarted the browser."),
    ("login", "The login never stays completed; it redirects me to sign in again.", "Please suggest a fix."),
    ("login", "I enter my credentials and get sent back to the login screen.", "What should I check next?"),
    ("login", "My account sign-in cycles back to the login page after submitting.", "Is there a troubleshooting guide?"),
    ("login", "The website will not keep me signed in and returns to the login screen.", "I cleared cache but it continues."),
    ("login", "I am redirected to sign in after the login appears successful.", "What can I do?"),
    ("login", "Login redirects me in a loop instead of opening my dashboard.", "Please help me resolve it."),
    ("login", "The app bounces me back to the sign-in screen every time.", "My credentials should be valid."),
    ("login", "After authentication I see the login page again, over and over.", "What do you advise?"),
    ("login", "I cannot stay logged in; the site sends me back to sign-in.", "Could you provide steps?"),
    ("login", "The login page reloads after I submit my correct password.", "How do I troubleshoot this?"),
    ("login", "I sign in and am immediately asked to sign in again.", "What should I test?"),
    ("login", "The account page is unreachable because sign-in keeps looping.", "Please share the recommended checks."),
    ("rate", "My API requests are getting HTTP 429 responses on the free plan.", "What is the request limit?"),
    ("rate", "We hit rate limits while using the API on a free account.", "How many requests per minute are allowed?"),
    ("rate", "The service returns 429 and includes a Retry-After header.", "What does that mean for our quota?"),
    ("rate", "Our free-tier integration exceeds the API request cap.", "Can you explain the limit and retry guidance?"),
    ("rate", "I am seeing too many requests errors from the API.", "What are the free and paid limits?"),
    ("rate", "Requests are throttled at 429 on my account.", "How should my client handle Retry-After?"),
    ("rate", "The API rate limit is blocking our free plan workload.", "What limit applies and what can we do?"),
    ("rate", "Our service gets a 429 after sending many requests each minute.", "Is there a documented cap?"),
    ("rate", "Can you tell me why the API sends Retry-After with status 429?", "We use the free tier."),
    ("rate", "We need to know the per-minute API quota for free accounts.", "The server has started throttling us."),
    ("rate", "Our integration exceeded 60 API calls in a minute and got 429.", "What is the supported behavior?"),
    ("rate", "How can I handle 429 responses from the API correctly?", "We are on a paid plan."),
    ("rate", "The API says too many requests; what does Retry-After indicate?", "Please explain the limits."),
    ("rate", "We are rate limited during bursts of requests.", "What are the free-tier and paid-tier quotas?"),
    ("rate", "A 429 response is slowing down our integration.", "How long should we wait before retrying?"),
    ("rate", "The API quota seems to be 60 requests per minute for our account.", "Is that correct for free tier?"),
    ("rate", "Our paid account got rate-limited after around 600 requests in a minute.", "What should we check?"),
    ("rate", "Please clarify the API's requests per minute and the Retry-After header.", "We need to tune our client."),
    ("rate", "We received 429 while calling the API repeatedly.", "Can you provide the published rate limits?"),
    ("rate", "The free plan API calls are being throttled.", "How do we back off and what quota applies?"),
]

VAGUE = [
    "It doesn't work anymore.", "Something is wrong with my account.", "I need help urgently.",
    "The app is acting weird today.", "Can you fix this for me?", "I am having a problem.",
    "Nothing is working as expected.", "Please look into my issue.", "I can't use the service.",
    "This is broken and I need assistance.", "I have a problem but I am not sure what caused it.",
    "Can someone help me with what happened?", "The service failed again.", "I need support with a recent issue.",
    "It stopped working after I tried something.", "I am frustrated; please sort this out.",
    "I don't know what is wrong, but I cannot continue.", "Can you check why this is happening?",
    "I tried fixing it but it still fails.", "Please help me get things working again.",
]

CONTEXTS = {
    "billing_duplicate": "A pending duplicate authorization usually drops off in 3-5 business days. If both charges have cleared, open a refund ticket and refund the duplicate within 24 hours.",
    "billing_settled": "If both duplicate charges have cleared, open a refund ticket and refund the duplicate within 24 hours. Pending authorizations usually drop off in 3-5 business days.",
    "technical_login": "For login loops, ask the customer to clear cookies for the domain, try an incognito window, and confirm their email is verified.",
    "technical_rate": "Free tier is limited to 60 requests per minute; paid tier is 600 rpm. HTTP 429 responses include Retry-After; clients should respect it.",
    "vague": "For vague tickets, use available tools to gather context, then either give a grounded likely answer or ask one focused clarifying question. Low confidence should be escalated to human review.",
}


def main() -> None:
    rows = []
    for n, (kind, problem, ask) in enumerate(BILLING, 1):
        category = "billing"
        subtype = "duplicate" if kind == "duplicate" else "settled"
        rows.append({"id": f"billing_{n:02}", "input": {"ticket": f"{problem} {ask}"},
                     "expected": {"category": category},
                     "metadata": {"tags": [category, subtype], "context": CONTEXTS[f"billing_{subtype}"]}})
    for n, (kind, problem, ask) in enumerate(TECHNICAL, 1):
        category = "technical"
        subtype = "login" if kind == "login" else "rate"
        rows.append({"id": f"technical_{n:02}", "input": {"ticket": f"{problem} {ask}"},
                     "expected": {"category": category},
                     "metadata": {"tags": [category, subtype], "context": CONTEXTS[f"technical_{subtype}"]}})
    for n, ticket in enumerate(VAGUE, 1):
        rows.append({"id": f"vague_{n:02}", "input": {"ticket": ticket},
                     "expected": {"category": "vague"},
                     "metadata": {"tags": ["vague", "ambiguous"], "context": CONTEXTS["vague"]}})
    assert len(rows) == 100, f"expected 100 cases, got {len(rows)}"
    OUT.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} cases to {OUT}")


if __name__ == "__main__":
    main()
