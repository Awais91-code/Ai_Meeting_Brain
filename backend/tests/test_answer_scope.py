from .conftest import signup_and_login, make_admin


def test_search_rewrite_does_not_expand_answer_scope(client, test_engine, monkeypatch):
    from app.routes import meetings
    token = signup_and_login(client, 'Scope Admin', 'scope@example.com', 'password-test-123')
    make_admin(test_engine, 'scope@example.com')
    headers = {'Authorization':f'Bearer {token}'}
    meeting_id = client.post('/api/meetings/', headers=headers, json={
        'title':'Marketing', 'meeting_date':'2026-09-16T10:00:00Z',
        'transcript':'The approved marketing budget is $1,000. The campaign ends September 20.'
    }).json()['id']
    monkeypatch.setattr(meetings, 'resolve_followup_question', lambda *args: 'Marketing project budget, tools, expenses, duration and deadline')
    monkeypatch.setattr(meetings, 'search', lambda *args, **kwargs: ({'documents':[[]]}, 'cosine'))
    observed = []
    def answer(question, context, history):
        observed.append(question)
        assert '$1,000' in context
        return 'The approved marketing budget is $1,000. [Source 1]'
    monkeypatch.setattr(meetings, 'generate_answer', answer)
    response = client.post(f'/api/meetings/{meeting_id}/ask', headers=headers, json={'question':'What is budget?'})
    assert response.status_code == 200
    assert observed == ['What is budget?']
    assert 'deadline' not in response.json()['answer']


def test_brief_fallback_keeps_only_relevant_evidence():
    from app.services.llm import _fallback_answer
    answer = _fallback_answer('What is budget?', '[Source 1]\nThe marketing budget is $1,000.\nThe budget pays for HubSpot.\nThe deadline is Friday.')
    assert '$1,000' in answer
    assert 'HubSpot' not in answer and 'Friday' not in answer


def test_existing_summaries_and_all_design_pages_render(client):
    for route in ('/login','/dashboard','/admin','/admin/employees','/meetings/1','/admin/meetings/1/edit','/live'):
        response = client.get(route)
        assert response.status_code == 200
        assert '/static/css/design.css' in response.text
        assert '/static/js/presentation.js' in response.text


def test_hindi_search_keeps_vowel_marks_and_urdu_function_words_do_not_match():
    from app.services.llm import tokenize, _fallback_answer, wants_detail
    assert "लॉन्च" in tokenize("लॉन्च की तारीख क्या है?")
    assert "तारीख" in tokenize("लॉन्च की तारीख क्या है?")
    assert "لॉन्च" not in tokenize("लॉन्च")
    answer = _fallback_answer("बजट क्या है?", "बजट पचास हजार रुपये है। लॉन्च शुक्रवार को है।")
    assert "पचास" in answer and "शुक्रवार" not in answer
    assert "couldn't find" in _fallback_answer("مریخ کا درجہ حرارت کیا ہے؟", "منصوبے کا بجٹ پچاس ہزار روپے ہے۔")
    assert wants_detail("बैठक का सारांश बताओ")
