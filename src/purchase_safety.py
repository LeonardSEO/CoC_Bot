"""Local purchase deny rules. Unrecognized payment/shop screens stop inputs."""
import re
from automation_safety import AutomationStopped


def purchase_reason(texts):
    text = ' '.join(texts).casefold()
    if re.search(r'[$€£]\s*\d|\d[\d.,]*\s*[$€£]|\b(?:USD|EUR|GBP)\s*\d', text):
        return 'real_money_price'
    phrases = ('google play', 'app store', 'buy now', 'purchase', 'payment',
               'credit card', 'pay with', 'one tap buy', 'shop', 'winkel',
               'aanbiedingen', 'buy resources', 'buy gems', 'missing resources',
               'not enough', 'insufficient', 'onvoldoende', 'kopen', 'betalen')
    if any(re.search(r'\b'+re.escape(phrase)+r'\b', text) for phrase in phrases):
        return 'shop_payment_or_resource_topup'
    return None


def reject_purchase_text(texts):
    if not any(str(text).strip() for text in texts):
        raise AutomationStopped('Purchase guard cannot read this screen; refusing input')
    reason = purchase_reason(texts)
    if reason:
        raise AutomationStopped(f'Purchase guard blocked input: {reason}')
