"""Durable comparison conversations with optimistic commits and idempotent turns."""
import copy
import json
import secrets
import sqlite3
import time
from contextlib import closing
from uuid import UUID, uuid4
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.models import ComparisonResult, ComparisonRequest
from backend.scenario.actions import interpret, Action
from backend.scenario.engine import apply, calculate, no_match_message


class Start(BaseModel):
    model_config=ConfigDict(extra="forbid")
    comparison_id: UUID


class Turn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    request_id: UUID
    version: int = Field(ge=0)
    message: str = Field(min_length=1,max_length=2000)


def explanation(result):
    rec=result.recommendation_result
    if not rec or not rec.best_overall: return 'No recommendation is recorded in this comparison.'
    best=rec.best_overall
    cost=best.horizon_cost if best.horizon_cost is not None else best.estimated_annual_cost
    text=f'{best.name} is recommended at ${cost:,.2f} over {rec.comparison_horizon} months. Confidence: {rec.confidence}. '
    text+=' '.join(best.recommendation_reasons + rec.confidence_reasons)
    if len(rec.plan_analyses)==1: text+=' Only one plan qualifies; zero regret does not imply market superiority.'
    ties=[p.name for p in rec.plan_analyses if p.plan_id!=best.plan_id and p.horizon_cost==best.horizon_cost]
    if ties: text+=' Equal estimated cost: '+', '.join(ties)+'.'
    return text+' '+' '.join(rec.warnings)


def router(store,catalog,source,interpreter=None):
    api=APIRouter(prefix='/api/comparison-chat',tags=['comparison chat'])
    interpreter=interpreter or interpret
    def db():
        connection=sqlite3.connect(store.path,timeout=10)
        connection.row_factory=sqlite3.Row
        return connection
    def initialize():
        with closing(db()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS scenario_sessions (id TEXT PRIMARY KEY, token TEXT NOT NULL, version INTEGER NOT NULL, expires REAL NOT NULL, payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS scenario_failures (session_id TEXT NOT NULL, request_id TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS scenario_turns (session_id TEXT NOT NULL, request_id TEXT NOT NULL, body TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(session_id,request_id))')
    def failure(id,payload,message):
        try:
            with closing(db()) as c,c:
                c.execute('INSERT INTO scenario_failures VALUES (?,?,?,?)',(str(id),str(payload.request_id),message,time.time()))
        except sqlite3.Error:
            pass  # The response still reports failure; no scenario commit was attempted.

    def load(id,token):
        with closing(db()) as c:
            row=c.execute('SELECT * FROM scenario_sessions WHERE id=?',(str(id),)).fetchone()
        if row is None or not secrets.compare_digest(row['token'],token): raise HTTPException(404,'Conversation not found. Start chat from a saved comparison.')
        if row['expires']<time.time(): raise HTTPException(410,'Conversation expired. Start a new chat from your saved comparison.')
        return dict(row),json.loads(row['payload'])
    def view(id,version,state,message='',status='ready',result=None):
        current=state['history'][state['active']]
        result=result or store.get(current['result_id'])
        if result is None: raise HTTPException(404,'Saved scenario result is missing. Start from an available comparison.')
        with closing(db()) as c:
            failures=[dict(r) for r in c.execute('SELECT request_id,message,created FROM scenario_failures WHERE session_id=? ORDER BY created DESC LIMIT 20',(str(id),))]
        available=[{'id':r['id'],'name':r['plan']['name']['value'] if 'plan' in r else r['name']} for r in state['frozen']]
        return {'available_plans':available,'failures':failures,'session_id':str(id),'version':version,'message':message,'status':status,
            'result':result.model_dump(mode='json'),'state':current['state'],
            'history':[{'index':i,'comparison_id':h['result_id'],'parent':h['parent']} for i,h in enumerate(state['history'])],
            'active':state['active'],'attempts':state['attempts'],'pending':state['pending'],
            'needs_migration':state['needs_migration']}

    @api.post('',status_code=201)
    def start(payload:Start):
        result=store.get(str(payload.comparison_id))
        if result is None: raise HTTPException(404,'Comparison not found. Run Compare plans first.')
        if not result.zip_code or not result.recommendations: raise HTTPException(409,'This legacy result lacks inputs. Run Compare plans again.')
        if result.scenario_context:
            frozen=copy.deepcopy(result.scenario_context['frozen'])
        elif result.data_mode=='pdf':
            frozen=catalog.all_plans()
            known={p.plan_id for p in result.recommendations} | {p['plan_id'] for p in result.excluded_plans if 'plan_id' in p}
            frozen=[r for r in frozen if r['id'] in known]
            byid={r['id']:r for r in frozen}
            if any(p.plan_id not in byid or byid[p.plan_id]['revision_id']!=p.source_revision for p in result.recommendations):
                raise HTTPException(409,'The source catalog changed. Run Compare plans again to start a new chat.')
        else:
            frozen=[p.model_dump(mode='json') for p in source.list_plans()]
        options=result.recommendation_result.options.model_dump(mode='json') if result.recommendation_result else {}
        options['comparison_horizon']=result.recommendation_result.comparison_horizon if result.recommendation_result else 12
        request=ComparisonRequest(zip_code=result.zip_code,data_source=result.data_mode,
            monthly_kwh=[m.kwh for m in result.recommendations[0].monthly_costs],recommendation_options=options)
        initial=copy.deepcopy(result.scenario_context['state']) if result.scenario_context else {'request':request.model_dump(mode='json'),'overrides':[]}
        state={'original_id':result.id,'frozen':frozen,'history':[{'parent':None,'result_id':result.id,'state':initial}],
            'active':0,'attempts':[],'pending':None,'needs_migration':result.data_mode=='pdf' and any(p.pricing_basis!='custom_efl' for p in result.recommendations)}
        id,token=str(uuid4()),secrets.token_urlsafe(32)
        with closing(db()) as c,c:
            c.execute('DELETE FROM scenario_failures WHERE session_id IN (SELECT id FROM scenario_sessions WHERE expires<?)',(time.time(),))
            c.execute('DELETE FROM scenario_turns WHERE session_id IN (SELECT id FROM scenario_sessions WHERE expires<?)',(time.time(),))
            c.execute('DELETE FROM scenario_sessions WHERE expires<?',(time.time(),))
            if c.execute('SELECT count(*) FROM scenario_sessions').fetchone()[0]>=500: raise HTTPException(429,'Chat capacity reached. Try again later.')
            c.execute('INSERT INTO scenario_sessions VALUES (?,?,0,?,?)',(id,token,time.time()+86400,json.dumps(state)))
        return {**view(id,0,state),'token':token}

    @api.get('/{id}')
    def get(id:UUID,x_scenario_token:str=Header(default='')):
        row,state=load(id,x_scenario_token)
        return view(id,row['version'],state)

    @api.post('/{id}/messages')
    def turn(id:UUID,payload:Turn,x_scenario_token:str=Header(default='')):
        row,state=load(id,x_scenario_token)
        body=payload.model_dump_json()
        def cached(c):
            previous=c.execute('SELECT body,response FROM scenario_turns WHERE session_id=? AND request_id=?',(str(id),str(payload.request_id))).fetchone()
            if previous:
                if previous['body']!=body: raise HTTPException(409,'Request ID was reused for different input. Send a new request.')
                return json.loads(previous['response'])
        with closing(db()) as c:
            previous=cached(c)
            if previous:return previous
        if row['version']!=payload.version: raise HTTPException(409,'Conversation changed in another request. Reload chat before continuing.')
        if row['version']>=100: raise HTTPException(429,'Conversation limit reached. Start a new chat from the current comparison.')
        current=state['history'][state['active']]
        before=store.get(current['result_id'])
        if before is None: raise HTTPException(404,'Current comparison is missing. Start a new chat.')
        context={'state':current['state'],'pending':state['pending'],
            'recent_attempts':state['attempts'][-6:],
            'plans':[{'id':r['id'],'name':r['plan']['name']['value'],'calculation_eligible':r['calculation_eligible'],'calculation_issues':r['calculation_issues'],'components':[{k:v for k,v in c.items() if k!='evidence'} for c in r['plan']['components']]} if 'plan' in r else {'id':r['id'],'name':r['name']} for r in state['frozen']]}
        try:
            action=Action.model_validate(interpreter(payload.message,context))
        except Exception:
            failure(id,payload,'Interpretation failed; retry is available.')
            raise HTTPException(503,'Chat could not interpret this request. Your results are unchanged. Retry or rephrase the message.') from None
        status='explained';message='';result=None;changes=[]
        try:
            if action.kind in ('clarify','unsupported'):
                status=action.kind
                message=action.question or 'Please specify the plan, criterion and units.'
                state['pending']={'request':payload.message,'question':message,'previous':state['pending']} if status=='clarify' else None
                # Bound clarification context without losing the original request.
                if state['pending'] and state['pending']['previous']:
                    state['pending']['request']=state['pending']['previous']['request']+'; '+payload.message
                    state['pending']['previous']=None
            elif action.kind in ('reset','previous'):
                state['active']=0 if action.kind=='reset' else current['parent'] if current['parent'] is not None else 0
                state['pending']=None
                message='Restored the original comparison.' if action.kind=='reset' else 'Restored the previous successful scenario.'
                status='restored'
            elif action.kind=='compare_original':
                original=store.get(state['original_id'])
                if original is None: raise ValueError('Original comparison is missing')
                a,b=original.recommendation_result,before.recommendation_result
                if not a or not b or not a.best_overall or not b.best_overall: raise ValueError('A recommendation is missing from one comparison')
                ac=a.best_overall.horizon_cost if a.best_overall.horizon_cost is not None else a.best_overall.estimated_annual_cost
                bc=b.best_overall.horizon_cost if b.best_overall.horizon_cost is not None else b.best_overall.estimated_annual_cost
                message=f'Original: {a.best_overall.name}, ${ac:,.2f} / {a.comparison_horizon} months. Current: {b.best_overall.name}, ${bc:,.2f} / {b.comparison_horizon} months. '
                message+=(f'Cost difference: ${bc-ac:,.2f}; this is a scenario difference, not guaranteed savings.' if a.comparison_horizon==b.comparison_horizon and a.policy_version==b.policy_version else 'Periods or pricing methods differ; raw totals are not like-for-like savings.')
            elif action.kind=='explain': message=explanation(before)
            else:
                if state['needs_migration'] and action.kind!='migrate':
                    status='clarify';message='This saved result uses an older formula. Reply "use current custom formula" to explicitly migrate, or start a fresh comparison.'
                    state['pending']={'request':payload.message,'question':message,'previous':None}
                else:
                    if action.kind=='change' and not action.operations: raise ValueError('No supported changes were specified')
                    proposed=apply(current['state'],state['history'][0]['state'],action.operations,[r['id'] for r in state['frozen'] if r.get('calculation_eligible',True)])
                    changes=[f"{o.field.replace('_',' ')}: {o.value}" for o in action.operations]
                    result=calculate(proposed,state['frozen'])
                    if result is None:
                        status='no_matches';message=no_match_message(proposed,state['frozen'])
                        state['pending']={'request':payload.message,'question':message,'previous':None}
                    else:
                        names={p['id']:p.get('plan',{}).get('name',{}).get('value',p.get('name','')) for p in state['frozen']}
                        changes=[f"{o.field.replace('_',' ')}: {o.value if o.value is not None else 'cleared'} ({o.unit.replace('_',' ')}); {names.get(o.plan_id,o.plan_id) or 'scenario'}, {o.period}, months {o.months or 'all applicable'}" for o in action.operations]
                        if action.kind=='migrate': changes.append('Migrated to the current custom formula; other pending changes were not applied.')
                        state['history'].append({'parent':state['active'],'result_id':result.id,'state':proposed})
                        state['active']=len(state['history'])-1;state['pending']=None;state['needs_migration']=False
                        message='Changed: '+'; '.join(changes)+'. All other inputs and overrides were retained. '+explanation(result)
                        status='updated'
        except (ValueError,ValidationError) as error:
            result=None;status='invalid'
            message='Changes were not applied: '+str(error)[:1000]
            state['pending']={'request':payload.message,'question':message,'previous':None}
        except Exception:
            failure(id,payload,'Calculation failed; retry is available.')
            raise HTTPException(503,'Scenario calculation failed. Previous results are unchanged. Retry this request.') from None
        state['attempts']=(state['attempts']+[{'user':payload.message,'status':status,'message':message,'changes':changes}])[-40:]
        response=view(id,row['version']+1,state,message,status,result)
        # One transaction commits the scenario, active pointer and idempotency record.
        try:
            with closing(db()) as c,c:
                c.execute('BEGIN IMMEDIATE')
                previous=cached(c)
                if previous:return previous
                changed=c.execute('UPDATE scenario_sessions SET version=version+1,payload=? WHERE id=? AND version=?',(json.dumps(state),str(id),row['version']))
                if changed.rowcount!=1: raise HTTPException(409,'Another request completed first. Reload chat before continuing.')
                if result:c.execute('INSERT INTO comparisons VALUES (?,?)',(result.id,result.model_dump_json()))
                c.execute('INSERT INTO scenario_turns VALUES (?,?,?,?)',(str(id),str(payload.request_id),body,json.dumps(response)))
        except sqlite3.Error:
            failure(id,payload,'Saving failed; retry is available.')
            raise HTTPException(503,'Scenario could not be saved. Previous results are unchanged. Retry this request.') from None
        return response
    return api,initialize
