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

    def decide(self, messages, scope, require_search=False):
        self.decisions += 1
        self.messages = messages
        return next(self.steps)

    def finalize(self, messages, evidence):
        self.contexts.append(evidence)
        return GeneratedAnswer(answer="The contract term is 12 months.", abstained=False,
            evidence=[{"source_id": evidence[0]["source_id"], "quote": "Invented text that does not occur." if self.bad_quote else "Contract Term 12 Months."}])

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


class ModelAdapterTests(unittest.TestCase):
    def test_responses_tool_contract_and_latest_question(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from langchain_core.messages import HumanMessage
        from backend.agent.model import Model
        with patch('backend.agent.model.OpenAI') as sdk:
            model = Model(Settings(openai_key='test'))
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
