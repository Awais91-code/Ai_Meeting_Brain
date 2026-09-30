"""Opt-in live evaluation using synthetic facts; no private meetings are sent."""
import re
import sys
from app.services.llm import generate_answer

EVIDENCE = '''[Source 1]
The approved total marketing budget for the Zika restaurant campaign is $1,000.
That one budget covers lead-generation tools, HubSpot, utility bills and other expenses.
No amount was assigned to individual categories.
[Source 2]
The campaign lasts one month. Its deadline is 20 September 2026.'''

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    brief = generate_answer('What is budget?', EVIDENCE)
    print('Budget answer:', brief)
    assert '$1,000' in brief or '$1000' in brief
    assert len(brief.split()) <= 45, 'Simple question expanded into a recap'
    assert not re.search(r'HubSpot|September|deadline|utility|key details|based on', brief, re.I)
    breakdown = generate_answer('Give me the budget breakdown.', EVIDENCE)
    print('Breakdown answer:', breakdown)
    assert 'AI generation is unavailable' not in breakdown, 'Provider was unavailable'
    assert '$1,000' in breakdown or '$1000' in breakdown
    assert re.search(r'\b(no|not|unspecified|unassigned|without)\b', breakdown, re.I)
    print('PASS: concise factual answer; explicit detail request; no invented category amounts')
