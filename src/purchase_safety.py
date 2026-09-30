"""Local purchase deny rules. Unrecognized payment/shop screens stop inputs."""
import re
from automation_safety import AutomationStopped


def purchase_reason(texts, *, trusted_game_screen=False):
    text = ' '.join(texts).casefold()
    # OCR can misread a resource icon as a currency sign beside an integer.
    # On a recognized game screen, require a formatted money price instead.
    formatted_money = re.search(r'[$€£]\s*\d+[.,]\d{2}\b|\b\d+[.,]\d{2}\s*[$€£]|\b(?:usd|eur|gbp)\s*\d+', text)
    any_money = re.search(r'[$€£]\s*\d|\d[\d.,]*\s*[$€£]|\b(?:usd|eur|gbp)\s*\d', text)
    if formatted_money or (any_money and not trusted_game_screen):
        return 'real_money_price'
    groups = {
        'purchase_action': ('google play', 'app store', 'buy now', 'purchase',
                            'payment', 'credit card', 'pay with', 'one tap buy',
                            'kopen', 'betalen'),
        'resource_topup': ('buy resources', 'buy gems', 'missing resources',
                           'not enough', 'insufficient', 'onvoldoende'),
    }
    for reason, phrases in groups.items():
        if any(re.search(r'\b'+re.escape(phrase)+r'\b', text) for phrase in phrases):
            return reason
    # SHOP is a permanent village footer, also visible behind upgrade dialogs.
    if not trusted_game_screen and any(re.search(r'\b'+phrase+r'\b',text)
                                        for phrase in ('shop','winkel','aanbiedingen')):
        return 'shop_label'
    return None


def reject_purchase_text(texts):
    if not any(str(text).strip() for text in texts):
        raise AutomationStopped('Purchase guard cannot read this screen; refusing input')
    reason = purchase_reason(texts)
    if reason:
        raise AutomationStopped(f'Purchase guard blocked input: {reason}')
