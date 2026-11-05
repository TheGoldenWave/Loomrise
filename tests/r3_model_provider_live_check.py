"""Opt-in live checks using only original fictional material and local credentials."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
from contextlib import closing, ExitStack
from unittest.mock import patch
import httpx

from loomrise.adapters.agentscope_runtime import build_model
from loomrise.durable_store import SqliteStore
from loomrise.graph_runtime import GraphRuntime
from loomrise.model_provider import LocalModelProvider, ModelProviderError
from loomrise.service import ExecutionService
from tests.test_concurrent_runtime import recall_pack
from tests.test_graph_runtime import config


async def verify():
    provider = LocalModelProvider.from_local_config(max_calls=3)
    if provider is None:
        return {'passed': False, 'error': 'model_not_configured'}
    material = '虚构课程测试：咨询时间为每周三晚上，体验课价格为 19 元。'
    source = {'source_id': 'fictional-course', 'title': '原创虚构资料', 'text': material,
              'content_hash': hashlib.sha256(material.encode()).hexdigest()}
    report = {'model': provider.model, 'data': 'original fictional material', 'checks': {}}
    try:
        answer = await provider.answer(text='什么时候可以咨询？', persona={'name': '虚构课程咨询'}, sources=[source], history=[])
        report['checks']['answer'] = {**answer, 'passed': bool(answer['citations']) and not answer['handoff']}
        graph = config()
        graph['units'][1]['exit_ports'][0]['completion'] = {'llm': '访客已明确同意继续答疑'}
        route = await asyncio.to_thread(GraphRuntime(graph, completion_evaluator=provider.completion).route,
                                       {'recent_turns': ['我同意继续答疑。']})
        report['checks']['completion'] = {'passed': route.status == 'completed', 'decisions': route.completion_checks}
        recalled = await provider.recall([
            {'unit_id': 'schedule-help', 'title': '咨询时间', 'applies_when': '询问咨询开放时间'},
            {'unit_id': 'refund-help', 'title': '退款说明', 'applies_when': '询问退款'},
        ], {'input': '周三晚上几点可以咨询？'})
        report['checks']['recall'] = {'passed': recalled == ['schedule-help'], 'selected_unit_ids': recalled}
    except ModelProviderError as exc:
        report['error'] = str(exc)
    report['passed'] = len(report['checks']) == 3 and all(check['passed'] for check in report['checks'].values())
    return report


async def verify_contact():
    """One fictional strict-schema request; persist only after explicit contact.save."""
    from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
    from loomrise.customer_service import CustomerService, CustomerServiceApplication
    from tests.test_configuration_service import spec

    provider = LocalModelProvider.from_local_config(max_calls=1)
    if provider is None:
        return {'passed': False, 'error': 'model_not_configured'}
    report = {'mode': 'contact-generation', 'data': 'original fictional material',
              'model': provider.model, 'budgets': {'provider_calls': 1, 'retries': 0}, 'checks': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-r3-live-contact-') as directory:
            database = str(Path(directory) / 'contact.db')
            with closing(SqliteStore(database)) as store:
                configuration = ConfigurationService(store)
                configuration.register_stable_version(tenant_id='fictional-tenant', agent_id='fictional-contact',
                    version_id='fixture-v1', config=spec())
                before = configuration.create_draft_from_stable(tenant_id='fictional-tenant',
                    agent_id='fictional-contact', base_version_id='fixture-v1')
                principal = ConfigurationPrincipal(tenant_id='fictional-tenant', actor_id='fixture-owner',
                    role='owner', agent_ids=('fictional-contact',))
                application = CustomerServiceApplication(CustomerService(
                    store, configuration, contact_generation_provider=provider))
                result = await application.execute_async(principal=principal, action='contact.generate', payload={
                    'agent_id': 'fictional-contact', 'expected_revision': before['revision'], 'template_id': 'support',
                    'brief': '原创虚构资料：星原手作工坊提供作品咨询，邮箱 hello@example.test。'
                             '请起草简洁中文联系页，含服务介绍、客服入口和联系信息。'
                             '在介绍中保留核对码 R3-CONTACT-8641。不要添加未提供的价格、地址、承诺或评价。'})
                if not result['ok']:
                    report['error'] = result['error']['code']
                    return {**report, 'passed': False}
                proposal = result['result']
                text = json.dumps(proposal['contact'], ensure_ascii=False)
                unchanged = configuration.get_draft(tenant_id='fictional-tenant', agent_id='fictional-contact') == before
                evidence = proposal['model_evidence']
                report['checks']['strict_proposal'] = {
                    'passed': proposal['state'] == 'proposal' and proposal['base_revision'] == before['revision']
                        and evidence['model'] == provider.model and bool(evidence['response_id'])
                        and 'R3-CONTACT-8641' in text and 'hello@example.test' in text,
                    'contact': proposal['contact'], 'model_evidence': evidence}
                report['checks']['no_implicit_save'] = {'passed': unchanged}
                saved = application.execute(principal=principal, action='contact.save', payload={
                    'agent_id': 'fictional-contact', 'expected_revision': proposal['base_revision'],
                    'contact': proposal['contact']})
                after = configuration.get_draft(tenant_id='fictional-tenant', agent_id='fictional-contact')
                expected = {**deepcopy(before['config']), 'contact': proposal['contact']}
                report['checks']['explicit_save'] = {'passed': saved['ok']
                    and after['revision'] == before['revision'] + 1 and after['config'] == expected}
            with closing(SqliteStore(database)) as reopened:
                restored = ConfigurationService(reopened).get_draft(
                    tenant_id='fictional-tenant', agent_id='fictional-contact')
                report['checks']['reopened'] = {'passed': restored == after, 'revision': restored['revision']}
    except Exception as exc:
        report['error'] = 'contact_check_failed'
        report['error_type'] = type(exc).__name__
    report['passed'] = len(report['checks']) == 4 and all(item['passed'] for item in report['checks'].values())
    return report


async def verify_assistance():
    """One fictional proposal, explicit state check/reply and SQLite reopen."""
    from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
    from loomrise.customer_service import CustomerService, CustomerServiceApplication
    from tests.test_configuration_service import spec

    provider = LocalModelProvider.from_local_config(max_calls=1)
    if provider is None:
        return {'passed': False, 'error': 'model_not_configured'}
    report = {'mode': 'inbox-assistance', 'data': 'original fictional material', 'model': provider.model,
              'budgets': {'provider_calls': 1, 'retries': 0}, 'checks': {}}
    tenant, agent = 'fictional-tenant', 'fictional-inbox'
    principal = ConfigurationPrincipal(tenant_id=tenant, actor_id='fictional-owner', role='owner', agent_ids=(agent,))
    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-r3-live-assistance-') as directory:
            database = str(Path(directory) / 'assistance.db')
            with closing(SqliteStore(database)) as store:
                configuration = ConfigurationService(store)
                source = configuration.create_knowledge_source(tenant_id=tenant, agent_id=agent, kind='faq',
                    locator='原创虚构资料：星原手作工坊体验课价格为 19 元。预约须人工核对，不在本次答疑中办理。',
                    display_name='原创虚构工坊说明', authorization='owned')
                source = configuration.ingest_knowledge_source(tenant_id=tenant, agent_id=agent, source_id=source['source_id'])
                config = spec()
                config['ai_reception'] = {'enabled': True, 'model_id': provider.model,
                    'sources': [{'source_id': source['source_id'], 'content_hash': source['content_hash']}]}
                configuration.register_stable_version(tenant_id=tenant, agent_id=agent, version_id='fixture-base', config=config)
                configuration.create_draft_from_stable(tenant_id=tenant, agent_id=agent, base_version_id='fixture-base')
                candidate = configuration.freeze_candidate(tenant_id=tenant, agent_id=agent, expected_revision=1, idempotency_key='assist-fixture')
                store.approve_release_candidate(tenant_id=tenant, agent_id=agent, candidate_id=candidate['candidate_id'],
                    content_hash=candidate['content_hash'], environment='sandbox', entry_id='fixture-entry',
                    version_id='fixture-v1', approved_by=principal.actor_id)
                store.publish_sandbox_candidate(tenant_id=tenant, agent_id=agent, candidate_id=candidate['candidate_id'],
                    entry_id='fixture-entry', version_id='fixture-v1')
                service = CustomerService(store, configuration, reception_provider=provider)
                app = CustomerServiceApplication(service)
                session = service.open_widget(tenant_id=tenant, agent_id=agent, entry_id='fixture-entry')
                await service.visitor_send_with_reception(conversation_id=session['conversation_id'], visitor_token=session['visitor_token'],
                    text='我想了解体验课多少钱；请人工协助，仅咨询，不要预约。', request_human=True, message_id='fixture-message')
                claim = service.claim(principal=principal, agent_id=agent, conversation_id=session['conversation_id'])
                scope = {'agent_id': agent, 'conversation_id': session['conversation_id'],
                         'generation': claim['occupancy_generation'], 'through_sequence': 1}
                before = service.inbox_messages(principal=principal, agent_id=agent, conversation_id=session['conversation_id'])
                result = await app.execute_async(principal=principal, action='inbox.assistance.generate', payload=scope)
                if not result['ok']:
                    return {**report, 'passed': False, 'error': result['error']['code']}
                proposal = result['result']
                checked = app.execute(principal=principal, action='inbox.assistance.check',
                    payload={**scope, 'snapshot_hash': proposal['snapshot_hash']})
                after = service.inbox_messages(principal=principal, agent_id=agent, conversation_id=session['conversation_id'])
                row = service.inbox_list(principal=principal, agent_id=agent)[0]
                report['checks']['proposal_only'] = {'passed': before == after and row['read_sequence'] == 0
                    and row['occupancy_generation'] == claim['occupancy_generation'] and checked['ok']
                    and proposal['state'] == 'proposal' and '19' in proposal['reply'],
                    'summary': proposal['summary'], 'reply': proposal['reply'], 'citations': proposal['citations'],
                    'model_evidence': proposal['model_evidence']}
                reply = app.execute(principal=principal, action='inbox.reply', payload={
                    'agent_id': agent, 'conversation_id': session['conversation_id'],
                    'generation': claim['occupancy_generation'], 'text': proposal['reply']})
                report['checks']['explicit_reply'] = {'passed': reply['ok']}
            with closing(SqliteStore(database)) as reopened:
                restored = CustomerService(reopened, ConfigurationService(reopened))
                messages = restored.inbox_messages(principal=principal, agent_id=agent, conversation_id=session['conversation_id'])
                report['checks']['reopened'] = {'passed': len(messages) == 2
                    and messages[1]['sender'] == 'operator' and messages[1]['text'] == proposal['reply']}
    except Exception as exc:
        report.update(error='assistance_check_failed', error_type=type(exc).__name__)
    report['passed'] = len(report['checks']) == 3 and all(item['passed'] for item in report['checks'].values())
    return report


EXECUTION_PROOF = 'R3-LIVE-REFUND-7319'


def execution_fixture(model, *, multi_candidate=False):
    """Original fictional pack; optional branches never register business tools."""
    pack = recall_pack()
    pack.agent_version = replace(pack.agent_version, model=model, tool_ids=[], rule_ids=[])
    pack.tools, pack.rules = [], []
    graph_unit = pack.agent_version.orchestration['units'][0]
    graph_unit['body']['text'] = '以下仅说明原创虚构资料。'
    graph_unit['exit_ports'][0]['completion'] = {'llm': '访客已明确同意继续资料答疑'}
    pack.skills = [replace(skill, tool_ids=[],
        goal='仅依据已加载资料回答当前问题，不办理任何业务。', exit_when='说明资料或缺失信息。')
        for skill in pack.skills]
    pack.skills[1] = replace(pack.skills[1], title='虚构课程退费资料',
        applies_when='用户查询开课前退费政策、申请交接方式或核对码；只提供资料，不办理退费。')
    pack.fragments = [replace(fragment, title='原创虚构退费说明',
        content=f'本次虚构课程仅允许开课前申请退费，须交由人工核对。核对码为 {EXECUTION_PROOF}。')
        if fragment.applies_to == 'refund_request' else replace(fragment,
        content='仅依据已加载资料答疑，不办理预约或退费。')
        if fragment.applies_to == 'course_consult_booking' else fragment
        for fragment in pack.fragments]
    if multi_candidate:
        value = pack.agent_version.orchestration
        decision = deepcopy(graph_unit)
        decision['unit_id'] = 'intent-choice'
        decision['entry_ports'][0]['goto'] = 'entry.from_start'
        decision['exit_ports'] = [
            {'port': topic, 'completion': {'deterministic': {}}, 'exits': [f'self.{topic}']}
            for topic in ('refund', 'schedule')]
        decision['body'] = {'kind': 'graph', 'routing': {'mode': 'llm'},
            'nodes': [{'id': 'entry', 'unit_ref': {'unit_id': graph_unit['unit_id'], 'version': 1}}],
            'edges': [{'id': f'choose-{topic}', 'from': 'entry.done', 'to': f'self.{topic}',
                       'condition': {'llm': {'prompt': prompt}}}
                      for topic, prompt in (('refund', '用户询问开课前退费规定、交接方式或退费核对码。'),
                                            ('schedule', '用户只询问咨询开放时间，不询问退费。'))]}
        terminals = []
        for topic in ('refund', 'schedule'):
            terminal = deepcopy(graph_unit)
            terminal['unit_id'] = f'{topic}-answer'
            terminal['exit_ports'][0]['completion'] = {'deterministic': {}}
            terminal['body']['text'] = f'以下仅提供原创虚构{topic}资料说明。'
            terminals.append(terminal)
        value['units'].extend([decision, *terminals])
        value['orchestration'].update(
            nodes=[{'id': 'decision', 'unit_ref': {'unit_id': 'intent-choice', 'version': 1}},
                   *[{'id': unit['unit_id'], 'unit_ref': {'unit_id': unit['unit_id'], 'version': 1}}
                     for unit in terminals]],
            entry='decision.from_start',
            edges=[*[{'id': f'enter-{topic}', 'from': f'decision.{topic}',
                       'to': f'{topic}-answer.from_start', 'condition': {}}
                      for topic in ('refund', 'schedule')],
                   *[{'id': f'finish-{topic}', 'from': f'{topic}-answer.done', 'to': 'end', 'condition': {}}
                     for topic in ('refund', 'schedule')]])
        pack.agent_version.unit_skill_bindings.update({
            unit['unit_id']: 'course_consult_booking' for unit in [decision, *terminals]})
        schedule = replace(pack.skills[1], skill_id='schedule_information', title='虚构课程咨询时间资料',
            applies_when='用户询问咨询开放时间、星期几和具体时段；不处理退费资料。')
        pack.skills.append(schedule)
        pack.agent_version.skill_ids.append(schedule.skill_id)
        fragment = next(item for item in pack.fragments if item.fragment_id == 'ctx.sop.refund')
        pack.fragments.append(replace(fragment, fragment_id='ctx.sop.schedule', applies_to=schedule.skill_id,
            title='原创虚构咨询时间', content='本次虚构课程只在周三晚上提供咨询，时间核对码为 R3-LIVE-SCHEDULE-8042。',
            token_estimate=0))
        helper = deepcopy(value['units'][1])
        helper['unit_id'] = 'schedule-helper'
        value['units'].append(helper)
        pack.agent_version.unit_skill_bindings[helper['unit_id']] = schedule.skill_id
    return pack


async def verify_execution(*, multi_candidate=False):
    """Exercise real completion/recall/generation, then reopen the event database.

    Wrappers only observe decisions and cap API attempts. All live responses
    come from the configured model; no business tools are registered.
    """
    provider = LocalModelProvider.from_local_config(max_calls=3 if multi_candidate else 2)
    if provider is None:
        return {'passed': False, 'error': 'model_not_configured'}
    pack = execution_fixture(provider.model, multi_candidate=multi_candidate)
    model = build_model()
    model.parameters.max_tokens = 1200
    original_client = model.client
    transport = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address='0.0.0.0'), timeout=60)
    model.client = original_client.with_options(http_client=transport, max_retries=0)
    await original_client.close()
    call_api = model._call_api
    generation_calls = 0

    async def bounded_call(*args, **kwargs):
        nonlocal generation_calls
        if generation_calls >= 1:
            raise RuntimeError('live_generation_call_budget_exceeded')
        generation_calls += 1
        return await call_api(*args, **kwargs)

    route_calls = []
    actual_route = provider.route

    def observed_route(candidates, state):
        decision = actual_route(candidates, state)
        route_calls.append({'candidate_edge_ids': [candidate['id'] for candidate in candidates],
                            'decision': decision})
        return decision

    report = {'model': provider.model, 'data': 'original fictional material', 'transport': 'ipv4',
              'scope': 'ExecutionService + SQLite, no business tools', 'checks': {}}
    if multi_candidate:
        report['mode'] = 'multi-candidate'
        report['budgets'] = {'provider_calls': 3, 'generation_calls': 1}
    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-r3-live-execution-') as directory:
            database = str(Path(directory) / 'execution.db')
            store = SqliteStore(database)
            try:
                service = ExecutionService(pack, store=store, agent_id='fictional-course', model_provider=provider)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(model, '_call_api', bounded_call))
                    stack.enter_context(patch('loomrise.service.build_model', return_value=model))
                    if multi_candidate:
                        # Keep the single-run observation and budget on the same
                        # real provider; neither candidate nor decision is changed.
                        stack.enter_context(patch.object(provider, 'for_run', return_value=provider))
                        stack.enter_context(patch.object(provider, 'route', observed_route))
                    result = await asyncio.wait_for(service.handle_text(
                        '我同意继续资料答疑。请说明开课前退费规定和核对码，不办理预约或退费。'), timeout=150)
                events = store.load_events(result.run_id)
                completions = [event.payload for event in events if event.event_type == 'route.graph.completion']
                recalls = [event.payload for event in events if event.event_type == 'recall.diagnostic'
                           and event.payload.get('code') == 'selected']
                outputs = [event.payload['text'] for event in events if event.event_type == 'reply.text']
                model_calls = [event.payload for event in events if event.event_type == 'model.call_end']
                report['checks'] = {
                    'completion': {'passed': len(completions) == 1 and completions[0]['satisfied']
                        and bool(completions[0].get('model_evidence', {}).get('response_id')),
                        'decisions': completions},
                    'recall': {'passed': len(recalls) == 1 and recalls[0]['selected_unit_ids'] == ['refund-helper']
                        and (not multi_candidate or recalls[0]['candidate_count'] >= 2)
                        and any(item['stage'] == 'concurrent' and item['fragment_id'] == 'ctx.sop.refund'
                                for item in result.context_audit['loaded']), 'diagnostics': recalls},
                    'generation': {'passed': generation_calls == 1 and len(model_calls) == 1
                        and model_calls[0].get('model') == model.model
                        and any(EXECUTION_PROOF in output for output in outputs), 'model_calls': model_calls,
                        'expected_model': model.model,
                        'text': result.text},
                    'zero_business_write': {'passed': result.write_count == 0 and result.request.result_id is None
                        and not any(event.event_type.startswith('tool.') for event in events)},
                }
                if multi_candidate:
                    routed = [event.payload for event in events if event.event_type == 'request.routed']
                    chosen = [event.payload for event in events if event.event_type == 'route.graph.step'
                              and event.payload.get('edge_id') == 'choose-refund']
                    report['checks']['routing'] = {'passed': len(route_calls) == 1
                        and route_calls[0]['candidate_edge_ids'] == ['choose-refund', 'choose-schedule']
                        and route_calls[0]['decision'].get('edge_id') == 'choose-refund'
                        and bool(route_calls[0]['decision'].get('model_evidence', {}).get('response_id'))
                        and len(chosen) == 1 and chosen[0]['layer'] == ['decision']
                        and len(routed) == 1 and routed[0].get('unit_id') == 'refund-answer',
                        'provider_calls': route_calls, 'route_steps': chosen, 'primary_route': routed}
                before = [event.to_dict() for event in events]
            finally:
                store.close()
            with closing(SqliteStore(database)) as restored:
                row = restored.run_row(result.run_id)
                request = restored.request_row(result.request.request_id)
                report['checks']['reopened'] = {'passed': restored.verify_chain(result.run_id)
                    and [event.to_dict() for event in restored.load_events(result.run_id)] == before
                    and row['status'] == 'succeeded' and request['state'] == 'success',
                    'event_count': len(before), 'run_status': row['status'], 'request_state': request['state']}
    except Exception as exc:
        report['error'] = 'execution_check_failed'
        report['error_type'] = type(exc).__name__
        report['http_status'] = getattr(exc, 'status_code', None)
    finally:
        await model.client.close()
        await transport.aclose()
    report['generation_calls'] = generation_calls
    report['passed'] = len(report['checks']) == (6 if multi_candidate else 5) and all(
        check['passed'] for check in report['checks'].values())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-live', action='store_true', required=True,
                        help='Use fictional data; Contact caps at one call, direct/single at three, multi at four')
    parser.add_argument('--execution-service', action='store_true',
                        help='Use persistent ExecutionService instead of direct provider checks')
    parser.add_argument('--multi-candidate', action='store_true',
                        help='With --execution-service: use two route and two recall candidates')
    parser.add_argument('--contact-generation', action='store_true',
                        help='Check one strict Contact proposal and explicit save in temporary SQLite')
    parser.add_argument('--inbox-assistance', action='store_true',
                        help='Check one Inbox summary/reply proposal, explicit reply and SQLite reopen')
    args = parser.parse_args()
    if args.multi_candidate and not args.execution_service:
        parser.error('--multi-candidate requires --execution-service')
    if sum((args.contact_generation, args.execution_service, args.inbox_assistance)) > 1:
        parser.error('Choose one of --contact-generation, --execution-service or --inbox-assistance')
    result = asyncio.run(verify_assistance() if args.inbox_assistance else verify_contact() if args.contact_generation else
        verify_execution(multi_candidate=args.multi_candidate) if args.execution_service else verify())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
