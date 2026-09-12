"""Offline API-to-graph tests with scripted model decisions, not mocked graph results."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

try:
    from langchain_core.messages import AIMessage, ToolMessage
    from backend.agent.runtime import Runtime
except ImportError as error:
    raise unittest.SkipTest("Install requirements-rag-dev.txt for agent tests") from error
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend.agent.api import Message, Resume, create_router
from backend.knowledge.config import Settings
from backend.knowledge.models import GeneratedAnswer
from test_knowledge import DOC_ID, TEXT, FakeProviders, manifest, match


def call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(uuid4())}])


def search(query="contract term"):
    return call("search_document_evidence", {"query": query, "document_id": DOC_ID})


class ScriptedModel:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.decisions = 0
        self.contexts = []
        self.bad_quote = False
        self.abstained = False
        self.repairs = 0
        self.repair_succeeds = False

    def decide(self, messages, scope, require_search=False):
        self.decisions += 1
        self.messages = messages
        return next(self.steps)

    def finalize(self, messages, evidence, repair=False):
        self.repairs += int(repair)
        self.contexts.append(evidence)
        return GeneratedAnswer(answer="The contract term is 12 months.", abstained=self.abstained,
            evidence=[{"source_id": evidence[0]["source_id"], "quote": "Invented text that does not occur." if self.bad_quote and not (repair and self.repair_succeeds) else "Contract Term 12 Months."}])

    def close(self):
        pass


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'manifest.json'
        self.path.write_text(json.dumps(manifest()))
        self.settings = Settings(manifest_path=self.path)
        self.providers = FakeProviders()
        self.addCleanup(self.temp.cleanup)

    def client(self, model):
        app = FastAPI()
        router, close = create_router(self.settings, lambda _: model, lambda _: self.providers)
        app.include_router(router)
        self.addCleanup(close)
        client = TestClient(app)
        self.addCleanup(client.close)
        thread = client.post('/api/agent/threads').json()
        self.base = '/api/agent/threads/' + thread['thread_id']
        self.headers = {'Authorization': 'Bearer ' + thread['token']}
        return client

    def send(self, client, **kwargs):
        return client.post(self.base + '/messages', headers=self.headers,
            json={'request_id': str(uuid4()), 'message': 'What is the term?', 'document_id': DOC_ID, **kwargs})

    def test_react_search_followup_and_request_deduplication(self):
        model = ScriptedModel([call('list_indexed_documents', {}), search(), AIMessage(content=''), search('early termination'), AIMessage(content='')])
        client = self.client(model)
        request_id = str(uuid4())
        response = self.send(client, request_id=request_id)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['status'], 'answered')
        self.assertEqual(len(data['activity']), 2)
        self.assertEqual(data['citations'][0]['page'], 1)
        again = self.send(client, request_id=request_id)
        self.assertEqual(again.json(), data)
        self.assertEqual(model.decisions, 3)
        self.assertEqual(self.send(client, message='And its termination fee?').status_code, 200)
        self.assertEqual(len(model.contexts), 2)
        self.assertEqual(model.contexts[0][0]['source_id'], model.contexts[1][0]['source_id'])
        self.assertEqual(self.send(client, request_id=request_id, message='different').status_code, 409)

    def test_interrupt_resume_and_stale_resume(self):
        model = ScriptedModel([call('ask_user', {'question': 'Which fee do you mean?'}), search(), AIMessage(content='')])
        client = self.client(model)
        data = self.send(client).json()
        self.assertEqual(data['status'], 'needs_input', data)
        self.assertEqual(self.send(client).status_code, 409)
        body = {'request_id': str(uuid4()), 'message': 'Contract term', 'interrupt_id': data['interrupt_id']}
        response = client.post(self.base + '/resume', headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'answered')
        self.assertTrue(any(isinstance(m, ToolMessage) and m.name == 'ask_user' for m in model.messages))
        self.assertEqual(client.post(self.base + '/resume', headers=self.headers, json=body).json(), response.json())
        body['request_id'] = str(uuid4())
        self.assertEqual(client.post(self.base + '/resume', headers=self.headers, json=body).status_code, 409)

    def test_refines_search_after_empty_observation(self):
        model = ScriptedModel([search('vague'), search('contract term'), AIMessage(content='')])
        client = self.client(model)
        with patch.object(self.providers, 'retrieve', side_effect=[[], [match()]]):
            data = self.send(client).json()
        self.assertEqual(data['status'], 'answered')
        self.assertIn('0 supporting', data['activity'][0])
        self.assertIn('1 supporting', data['activity'][1])

    def test_invalid_quotes_and_no_evidence_abstain(self):
        for steps, bad in [([search(), AIMessage(content='')], True), ([AIMessage(content='unsupported claim')], False)]:
            model = ScriptedModel(steps); model.bad_quote = bad
            client = self.client(model)
            data = self.send(client).json()
            self.assertEqual(data['status'], 'insufficient_evidence', data)
            self.assertEqual(data['citations'], [])

    def test_citation_repair_and_budget(self):
        for succeeds, exhausted in [(True, False), (False, False), (True, True)]:
            steps = [search(), AIMessage(content='')]
            if exhausted:
                steps = [call('list_indexed_documents', {}) for _ in range(3)] + steps
            model = ScriptedModel(steps)
            model.bad_quote = True
            model.repair_succeeds = succeeds
            data = self.send(self.client(model)).json()
            self.assertEqual(model.repairs, 0 if exhausted else 1)
            self.assertEqual(data['status'], 'answered' if succeeds and not exhausted else 'insufficient_evidence')
            if not exhausted:
                self.assertEqual(model.contexts[0], model.contexts[1])

    def test_no_repair_for_abstention_refusal_or_empty_retrieval(self):
        for mode in ('abstention', 'refusal', 'empty'):
            model = ScriptedModel([search(), AIMessage(content='')])
            client = self.client(model)
            value = None if mode == 'refusal' else GeneratedAnswer(answer='Not documented.', abstained=True, evidence=[])
            with patch.object(model, 'finalize', return_value=value) as finalize, patch.object(
                    self.providers, 'retrieve', return_value=[] if mode == 'empty' else [match()]):
                data = self.send(client).json()
            self.assertEqual(data['status'], 'insufficient_evidence')
            self.assertEqual(finalize.call_count, 0 if mode == 'empty' else 1)

    def test_calculation_redirect_and_factual_followup(self):
        model = ScriptedModel([search(), AIMessage(content='')])
        client = self.client(model)
        data = self.send(client, message='Calculate my exact bill at 1200 kWh.').json()
        self.assertEqual(data['status'], 'insufficient_evidence')
        self.assertIn('Compare Plan Costs', data['answer'])
        self.assertEqual(data['citations'], [])
        self.assertEqual(model.decisions, 0)
        self.assertEqual(self.send(client, message='What is the documented contract term?').json()['status'], 'answered')

    def test_redirect_on_resume_and_model_tool(self):
        model = ScriptedModel([call('ask_user', {'question':'What would you like to know?'})])
        client = self.client(model)
        data = self.send(client, message='Frontier Saver Plus 12').json()
        response = client.post(self.base + '/resume', headers=self.headers, json={
            'request_id':str(uuid4()), 'message':'Recommend a plan for me', 'interrupt_id':data['interrupt_id']})
        self.assertIn('Compare Plan Costs', response.json()['answer'])
        self.assertEqual(model.decisions, 1)
        model = ScriptedModel([call('redirect_to_comparison', {})])
        data = self.send(self.client(model), message='Which offer would suit my household?').json()
        self.assertIn('Compare Plan Costs', data['answer'])

    def test_selected_scope_is_passed_to_retrieval(self):
        model = ScriptedModel([search(), AIMessage(content='')])
        with patch.object(self.providers, 'retrieve', return_value=[match()]) as retrieve:
            data = self.send(self.client(model)).json()
        self.assertEqual(data['status'], 'answered')
        self.assertEqual(retrieve.call_args.args[2], DOC_ID)

    def test_unknown_tools_and_loop_limit(self):
        model = ScriptedModel([call('execute_shell', {'cmd': 'anything'}) for _ in range(5)])
        client = self.client(model)
        data = self.send(client).json()
        self.assertEqual(data['status'], 'limit_reached', data)
        self.assertEqual(model.decisions, 5)
        self.assertEqual(self.send(client).status_code, 409)

    def test_isolation_validation_clear_and_restart(self):
        client = self.client(ScriptedModel([]))
        response = client.post(self.base + '/messages', json={'request_id': str(uuid4()), 'message': 'hello'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.send(client, message=' ').status_code, 422)
        self.assertEqual(client.delete(self.base, headers=self.headers).status_code, 200)
        self.assertEqual(self.send(client).status_code, 404)
        runtime = Runtime(self.settings, lambda _: ScriptedModel([]))
        thread = runtime.create()
        restarted = Runtime(self.settings, lambda _: ScriptedModel([]))
        with self.assertRaises(HTTPException) as raised:
            restarted.acquire(thread['thread_id'], thread['token'])
        self.assertEqual(raised.exception.status_code, 404)

    def test_expiry_busy_thread_and_corpus_change(self):
        now = [0]
        model = ScriptedModel([call('ask_user', {'question': 'Which document?'})])
        runtime = Runtime(self.settings, lambda _: model, clock=lambda: now[0])
        thread = runtime.create(); key, token = thread['thread_id'], thread['token']
        session = runtime.acquire(key, token)
        with self.assertRaises(HTTPException) as raised:
            runtime.acquire(key, token)
        self.assertEqual(raised.exception.status_code, 409)
        session.lock.release()
        result = runtime.run(key, token, Message(request_id=uuid4(), message='fee?'))
        changed = manifest(); changed['corpus_id'] = 'new'; changed['namespace'] = 'power-plans-new'
        self.path.write_text(json.dumps(changed))
        with self.assertRaises(HTTPException) as raised:
            runtime.run(key, token, Resume(request_id=uuid4(), message='this one', interrupt_id=result['interrupt_id']), True)
        self.assertEqual(raised.exception.status_code, 409)
        now[0] = 1801
        with self.assertRaises(HTTPException) as raised:
            runtime.acquire(key, token)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertFalse(runtime.sessions)

    def test_provider_failure_is_sanitized(self):
        client = self.client(ScriptedModel([search()]))
        with patch.object(self.providers, 'connect', side_effect=RuntimeError('SECRET must not escape')):
            response = self.send(client)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('SECRET', response.text)
        self.assertTrue(self.providers.closed)

    def test_citation_repair_is_bounded_and_uses_current_evidence(self):
        for succeeds in (True, False):
            model = ScriptedModel([search(), AIMessage(content='')])
            model.bad_quote = True
            model.repair_succeeds = succeeds
            data = self.send(self.client(model)).json()
            self.assertEqual(model.repairs, 1)
            self.assertEqual(model.contexts[0], model.contexts[1])
            self.assertEqual(data['status'], 'answered' if succeeds else 'insufficient_evidence')
            self.assertEqual(bool(data['citations']), succeeds)
            self.assertIn('Retried answer with exact source excerpts', data['activity'])


    def test_no_repair_for_abstention_missing_evidence_or_exhausted_budget(self):
        for mode in ('abstain', 'empty', 'budget'):
            steps = [search(), AIMessage(content='')]
            if mode == 'budget':
                steps = [call('list_indexed_documents', {}) for _ in range(3)] + steps
            model = ScriptedModel(steps)
            model.bad_quote = True
            model.abstained = mode == 'abstain'
            client = self.client(model)
            with patch.object(self.providers, 'retrieve', return_value=[] if mode == 'empty' else [match()]):
                data = self.send(client).json()
            self.assertEqual(model.repairs, 0)
            self.assertEqual(data['status'], 'insufficient_evidence')
            self.assertEqual(data['citations'], [])



class ModelAdapterTests(unittest.TestCase):
    def test_responses_tool_contract_and_latest_question(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from langchain_core.messages import HumanMessage
        from backend.agent.model import Model
        with patch('backend.agent.model.OpenAI') as sdk:
            model = Model(Settings(openai_key='test'))
            sdk.return_value.responses.parse.return_value.output_parsed = None
            sdk.return_value.responses.create.return_value = SimpleNamespace(output_text='', output=[
                SimpleNamespace(type='function_call', call_id='call-1', name='search_document_evidence',
                                arguments=json.dumps({'query':'termination fee','document_id':DOC_ID}))])
            history = [HumanMessage(content='Contract term?'), AIMessage(content='12 months'), HumanMessage(content='And termination?')]
            decision = model.decide(history, DOC_ID, require_search=True)
            kwargs = sdk.return_value.responses.create.call_args.kwargs
            self.assertEqual(kwargs['tool_choice'], 'required')
            self.assertFalse(kwargs['parallel_tool_calls'])
            self.assertFalse(kwargs['store'])
            self.assertTrue(all(t['strict'] for t in kwargs['tools']))
            self.assertEqual(decision.tool_calls[0]['id'], 'call-1')
            history.extend([decision, ToolMessage(content='evidence', tool_call_id='call-1')])
            model.decide(history, DOC_ID)
            wire = sdk.return_value.responses.create.call_args.kwargs['input']
            self.assertEqual(wire[-1]['type'], 'function_call_output')
            self.assertEqual(wire[-1]['call_id'], 'call-1')
            model.finalize(history, [])
            final_input = json.loads(sdk.return_value.responses.parse.call_args.kwargs['input'])
            self.assertEqual(final_input['latest_question'], 'And termination?')
            self.assertEqual(final_input['earlier_user_turns'], ['Contract term?'])

    def test_finalizer_preserves_clarification_and_resolves_ids(self):
        from types import SimpleNamespace
        from langchain_core.messages import HumanMessage
        from backend.agent.model import Model, SelectedAnswer
        context = [{'source_id':'S1','document_id':DOC_ID,'filename':'EFL.pdf','page':1,'text':'Contract Term | 12 Months'}]
        history = [HumanMessage(content='What are the fees?'),
            call('ask_user', {'question':'Which plan?'}),
            ToolMessage(content=json.dumps({'user_clarification':'Frontier Saver Plus 12'}), name='ask_user', tool_call_id='a'),
            HumanMessage(content='rates')]
        with patch('backend.agent.model.OpenAI') as sdk:
            model = Model(Settings(openai_key='test'))
            sdk.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=SelectedAnswer(
                answer='12 months', abstained=False, excerpt_ids=['E1']))
            answer = model.finalize(history, context)
            wire = json.loads(sdk.return_value.responses.parse.call_args.kwargs['input'])
            self.assertIn('Frontier Saver Plus 12', wire['earlier_clarifications'][0])
            self.assertEqual(wire['latest_question'], 'rates')
            self.assertEqual(answer.evidence[0].quote, context[0]['text'])
            model.finalize(history[:-1], context)
            wire = json.loads(sdk.return_value.responses.parse.call_args.kwargs['input'])
            self.assertEqual(wire['clarification_questions'], ['Which plan?'])

    def test_finalizer_preserves_clarification_question_and_repair_contract(self):
        from langchain_core.messages import HumanMessage
        from backend.agent.model import Model, PROMPT
        with patch('backend.agent.model.OpenAI') as sdk:
            model = Model(Settings(openai_key='test'))
            sdk.return_value.responses.parse.return_value.output_parsed = None
            history = [HumanMessage(content='Frontier Saver Plus 12'),
                call('ask_user', {'question':'What would you like to know?'}),
                ToolMessage(content=json.dumps({'user_clarification':'Contract term'}),
                    tool_call_id='clarify', name='ask_user')]
            model.finalize(history, [], repair=True)
            kwargs = sdk.return_value.responses.parse.call_args.kwargs
            payload = json.loads(kwargs['input'])
            self.assertEqual(payload['clarification_questions'], ['What would you like to know?'])
            self.assertIn('Contract term', payload['clarifications'][0])
            self.assertIn('previous attempt failed', kwargs['instructions'])
            self.assertIn('excerpt_ids instead of free-form quotes', kwargs['instructions'])
            self.assertIn('only a plan or document name', PROMPT)




class ExcerptTests(unittest.TestCase):
    def test_exact_symbols_and_unknown_ids(self):
        from backend.agent.model import prepare_excerpts, resolve_excerpts, SelectedAnswer
        from backend.knowledge.evidence import validate_answer
        text = ('Energy | 12.7600 \u00a2 per kWh\nCredit | $125 at >=1000 kWh\n' * 30)
        context = [{'source_id':'S1','document_id':DOC_ID,'filename':'EFL.pdf','page':1,'text':text}]
        sources, excerpts = prepare_excerpts(context)
        self.assertNotIn('text', sources[0])
        self.assertEqual(excerpts['E1']['quote'][-200:], excerpts['E2']['quote'][:200])
        self.assertTrue(all(e['quote'] in text and len(e['quote']) <= 1000 for e in excerpts.values()))
        value = SelectedAnswer(answer='Energy is 12.7600 cents/kWh.', abstained=False, excerpt_ids=['E1'])
        answer = validate_answer(resolve_excerpts(value, excerpts), context)
        self.assertFalse(answer.abstained)
        self.assertIn('\u00a2', answer.citations[0].excerpt)
        value.excerpt_ids = ['E1','unknown']
        self.assertEqual(validate_answer(resolve_excerpts(value, excerpts), context).citations, [])
        self.assertIsNone(resolve_excerpts(None, excerpts))

    def test_document_rate_and_credit_questions_are_not_calculations(self):
        from backend.agent.graph import comparison_request
        from langchain_core.messages import HumanMessage
        for question in ['rates', 'fees', 'How does the bill credit work?', 'What is the energy charge?', 'What is the termination fee?']:
            self.assertFalse(comparison_request([HumanMessage(content=question)]), question)
        for question in ['Estimate my bill', 'How much would I pay at 1200 kWh?', 'Recommend a plan', 'Which is the cheapest plan?']:
            self.assertTrue(comparison_request([HumanMessage(content=question)]), question)


class ExcerptSelectionTests(unittest.TestCase):
    def test_symbols_tables_windows_and_unknown_references(self):
        from backend.agent.model import prepare_excerpts, resolve_excerpts, SelectedAnswer
        from backend.knowledge.evidence import validate_answer
        text = ('Energy Charge | 12.7600 \u00a2 per kWh\nDelivery | $4.06 per cycle\n' * 35)
        context = [{"source_id":"S1", "document_id":DOC_ID, "filename":"EFL-4.pdf", "page":1, "text":text}]
        sources, excerpts = prepare_excerpts(context)
        self.assertNotIn('text', sources[0])
        values = list(excerpts.values())
        self.assertGreater(len(values), 1)
        self.assertTrue(all(20 <= len(' '.join(v['quote'].split())) <= 1000 for v in values))
        self.assertEqual(values[0]['quote'][-200:], values[1]['quote'][:200])
        self.assertTrue(all(v['quote'] in text for v in values))
        selected = SelectedAnswer(answer='Energy is 12.7600 \u00a2 per kWh.', abstained=False,
                                  excerpt_ids=['E1','E2','E1'])
        answer = validate_answer(resolve_excerpts(selected, excerpts), context)
        self.assertFalse(answer.abstained)
        self.assertEqual(len(answer.citations), 2)
        self.assertIn('12.7600 \u00a2', answer.citations[0].excerpt)
        self.assertEqual(answer.citations[0].page, 1)
        selected.excerpt_ids = ['E1','invented']
        rejected = validate_answer(resolve_excerpts(selected, excerpts), context)
        self.assertTrue(rejected.abstained)
        self.assertEqual(rejected.citations, [])
        self.assertIsNone(resolve_excerpts(None, excerpts))
        selected.excerpt_ids = []
        self.assertTrue(validate_answer(resolve_excerpts(selected, excerpts), context).abstained)
        self.assertEqual(prepare_excerpts([{**context[0], 'text':'short'}])[1], {})

    def test_adapter_resolves_selected_ids_to_original_source_text(self):
        from types import SimpleNamespace
        from langchain_core.messages import HumanMessage
        from backend.agent.model import Model, SelectedAnswer
        context = [{"source_id":"S1", "document_id":DOC_ID, "filename":"EFL-4.pdf", "page":1,
                    "text":"Energy Charge | 12.7600 \u00a2 per kWh\nDelivery | $4.06 per cycle"}]
        with patch('backend.agent.model.OpenAI') as sdk:
            model = Model(Settings(openai_key='test'))
            sdk.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=
                SelectedAnswer(answer='Energy is 12.7600 \u00a2 per kWh.', abstained=False, excerpt_ids=['E1']))
            result = model.finalize([HumanMessage(content='rates')], context)
            self.assertEqual(result.evidence[0].quote, context[0]['text'])
            self.assertEqual(result.evidence[0].source_id, 'S1')
            wire = sdk.return_value.responses.parse.call_args.kwargs
            self.assertIs(wire['text_format'], SelectedAnswer)
            self.assertEqual(json.loads(wire['input'])['sources'][0]['excerpts'][0]['text'], context[0]['text'])
