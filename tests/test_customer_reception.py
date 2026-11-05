from __future__ import annotations

import asyncio
import json
from pathlib import Path
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.customer_statistics import aggregate_reception_statistics
from loomrise.durable_store import SqliteStore
from loomrise.config_validation import validate_configuration
from loomrise.widget_configuration import public_widget_configuration
from tests.test_configuration_service import spec


class AnswerProvider:
    model = 'test-model'
    def __init__(self):
        self.payloads = []
        self.started = asyncio.Event()
        self.release = None
        self.failure = None
        self.response = None

    async def answer(self, **payload):
        self.payloads.append(payload)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure:
            raise self.failure
        return self.response or {
            'text': '体验课价格为 19 元。',
            'citations': [{'source_id': payload['sources'][0]['source_id'], 'content_hash': payload['sources'][0]['content_hash'], 'quote': '体验课价格为 19 元。'}],
            'handoff': False,
            'model': 'test-model', 'provider_response_id': 'response-test', 'usage': {'input_tokens': 12, 'output_tokens': 8},
        }


class CustomerReceptionCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, 'reception.db'))
        self.configuration = ConfigurationService(self.store)
        self.owner = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='owner', role='owner', agent_ids=('expert-a',))
        self.provider = AnswerProvider()
        self.source = self.configuration.create_knowledge_source(tenant_id='tenant-a', agent_id='expert-a',
            kind='faq', locator='体验课价格为 19 元。', display_name='虚构课程说明', authorization='owned')
        self.source = self.configuration.ingest_knowledge_source(tenant_id='tenant-a', agent_id='expert-a', source_id=self.source['source_id'])
        self.config = spec()
        self.config['ai_reception'] = {'enabled': True, 'mode': 'always', 'model_id': 'test-model', 'sources': [
            {'source_id': self.source['source_id'], 'content_hash': self.source['content_hash']} ]}
        self.publish(self.config)
        self.service = CustomerService(self.store, self.configuration, reception_provider=self.provider)
        self.app = CustomerServiceApplication(self.service)
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        self.addCleanup(self.store.close)
        self.addCleanup(self.tmp.cleanup)

    def publish(self, config, version='sandbox-v1'):
        if version == 'sandbox-v1':
            self.configuration.register_stable_version(tenant_id='tenant-a', agent_id='expert-a', version_id=version+'-base', config=config)
            draft = self.configuration.create_draft_from_stable(tenant_id='tenant-a', agent_id='expert-a', base_version_id=version+'-base')
        else:
            current = self.configuration.get_draft(tenant_id='tenant-a', agent_id='expert-a')
            draft = self.configuration.save_draft(tenant_id='tenant-a', agent_id='expert-a', expected_revision=current['revision'], config=config)
        candidate = self.configuration.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a', expected_revision=draft['revision'], idempotency_key=version)
        self.store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='entry-a', version_id=version, approved_by='owner')
        self.store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'], entry_id='entry-a', version_id=version)

    async def send(self, text='体验课多少钱？', message_id='message-1', **extra):
        return await self.app.execute_async(principal=self.owner, action='widget.send', payload={
            'conversation_id': self.session['conversation_id'], 'visitor_token': self.session['visitor_token'],
            'text': text, 'message_id': message_id, **extra})

    def messages(self):
        return self.service.visitor_messages(conversation_id=self.session['conversation_id'], visitor_token=self.session['visitor_token'])

    async def test_answer_has_frozen_sources_and_durable_request_run_citations(self):
        result = await self.send()
        self.assertTrue(result['ok'], result)
        answer = result['result']
        self.assertEqual(answer['reception']['status'], 'answered')
        self.assertEqual(answer['assistant']['text'], '体验课价格为 19 元。')
        self.assertEqual(answer['assistant']['citations'][0]['content_hash'], self.source['content_hash'])
        self.assertEqual(self.provider.payloads[0]['sources'][0]['source_id'], self.source['source_id'])
        run_id = answer['reception']['run_id']
        events = self.store.load_events(run_id)
        self.assertTrue(events)
        self.assertEqual({e.request_id for e in events}, {answer['reception']['request_id']})
        self.assertEqual({e.agent_version for e in events}, {'sandbox-v1'})
        self.assertTrue(self.store.verify_chain(run_id))
        row = self.store._conn.execute('SELECT state,result_id FROM requests WHERE request_id=?', (answer['reception']['request_id'],)).fetchone()
        self.assertIsNone(row['result_id'])
        self.assertNotEqual(row['state'], 'success')
        self.assertEqual(self.messages()[1]['reception']['run_id'], run_id)

    async def test_statistics_reader_projects_only_scoped_reception_events(self):
        result = await self.send()
        rows = self.store.customer_reception_statistics_rows(tenant_id='tenant-a', agent_id='expert-a')
        self.assertEqual({row['event_type'] for row in rows}, {
            'customer.reception.started', 'customer.reception.generated',
            'customer.reception.published', 'customer.reception.finished',
        })
        self.assertEqual({row['turn_run_id'] for row in rows}, {result['result']['reception']['run_id']})
        self.assertEqual(self.store.customer_reception_statistics_rows(tenant_id='other', agent_id='expert-a'), [])
        projection = aggregate_reception_statistics(rows, tenant_id='tenant-a', agent_id='expert-a')
        self.assertEqual((projection['request_count'], projection['run_count']), (1, 1))
        self.assertEqual(projection['generated_count'], 1)
        self.assertEqual(projection['model_usage']['input_tokens'], 12)
        self.assertEqual((projection['handoff']['claimed_count'], projection['handoff']['claim_sample_count'],
                          projection['handoff']['claim_missing_count']), (0, 1, 0))

    async def test_inbox_messages_preserve_reception_run_association(self):
        result = await self.send()
        run_id = result['result']['reception']['run_id']
        messages = self.service.inbox_messages(principal=self.owner, agent_id='expert-a',
                                               conversation_id=self.session['conversation_id'])
        self.assertEqual([message['reception']['run_id'] for message in messages], [run_id, run_id])

    async def test_duplicate_input_returns_same_turn_without_generating_again(self):
        first = await self.send()
        again = await self.send()
        self.assertEqual(again['result']['reception']['run_id'], first['result']['reception']['run_id'])
        self.assertEqual(len(self.messages()), 2)
        self.assertEqual(len(self.provider.payloads), 1)
        conflict = await self.send('different input')
        self.assertFalse(conflict['ok'])
        self.assertEqual(len(self.messages()), 2)

    async def test_human_claim_fences_delayed_answer(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        self.service.claim(principal=self.owner, agent_id='expert-a', conversation_id=self.session['conversation_id'])
        self.provider.release.set()
        result = await pending
        self.assertEqual(result['result']['reception']['status'], 'superseded')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual([m['sender'] for m in self.messages()], ['visitor'])

    async def test_new_input_fences_delayed_answer(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        self.service.visitor_send(conversation_id=self.session['conversation_id'], visitor_token=self.session['visitor_token'], text='还有第二个问题')
        self.provider.release.set()
        result = await pending
        self.assertEqual(result['result']['reception']['status'], 'superseded')
        self.assertEqual(len(self.messages()), 2)

    async def test_revoked_source_discards_generated_answer(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        self.configuration.revoke_knowledge_source(tenant_id='tenant-a', agent_id='expert-a', source_id=self.source['source_id'])
        self.provider.release.set()
        result = await pending
        self.assertEqual(result['result']['reception']['status'], 'knowledge_unavailable')
        self.assertIsNone(result['result']['assistant'])

    async def test_source_content_change_discards_generated_answer(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        with self.store._tx() as cursor:
            cursor.execute('UPDATE knowledge_sources SET content_hash=? WHERE source_id=?', ('0' * 64, self.source['source_id']))
        self.provider.release.set()
        result = await pending
        self.assertEqual(result['result']['reception']['status'], 'knowledge_unavailable')
        self.assertEqual(len(self.messages()), 1)

    async def test_default_policy_is_disabled_and_offline_only_obeys_open_hours(self):
        no_ai = spec()
        self.publish(no_ai, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'disabled')
        self.assertEqual(self.provider.payloads, [])
        offline = spec()
        offline['ai_reception'] = {**self.config['ai_reception'], 'mode': 'offline'}
        self.publish(offline, 'sandbox-v3')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'outside_schedule')
        self.assertEqual(self.provider.payloads, [])
        offline['widget'] = {'hours': []}
        self.publish(offline, 'sandbox-v4')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'answered')

    async def test_explicitly_disabled_reception_keeps_visitor_message_in_inbox(self):
        disabled = spec()
        disabled['ai_reception'] = {**self.config['ai_reception'], 'enabled': False}
        self.publish(disabled, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')

        result = await self.send()

        self.assertEqual(result['result']['reception']['status'], 'disabled')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual(self.provider.payloads, [])
        inbox = self.service.inbox_list(principal=self.owner, agent_id='expert-a')
        conversation = next(item for item in inbox if item['conversation_id'] == self.session['conversation_id'])
        self.assertEqual((conversation['latest_sequence'], conversation['unread_count']), (1, 1))
        self.assertEqual([message['text'] for message in self.service.inbox_messages(
            principal=self.owner, agent_id='expert-a', conversation_id=self.session['conversation_id'])],
            ['体验课多少钱？'])

    async def test_reception_mode_obeys_schedule_at_local_start_and_end_boundaries(self):
        hours = {'timezone': 'Asia/Shanghai',
                 'hours': [{'days': [0], 'start': '09:00', 'end': '17:00'}]}
        cases = [
            ('always', datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc), 'answered'),
            ('always', datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc), 'answered'),
            ('offline', datetime(2026, 11, 2, 0, 59, tzinfo=timezone.utc), 'answered'),
            ('offline', datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc), 'outside_schedule'),
            ('offline', datetime(2026, 11, 2, 8, 59, tzinfo=timezone.utc), 'outside_schedule'),
            ('offline', datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc), 'answered'),
        ]
        for index, (mode, moment, expected) in enumerate(cases, start=2):
            with self.subTest(mode=mode, moment=moment.isoformat()):
                config = spec()
                config['widget'] = hours
                config['ai_reception'] = {**self.config['ai_reception'], 'mode': mode}
                self.publish(config, f'sandbox-v{index}')
                self.session = self.service.open_widget(
                    tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
                with patch('loomrise.widget_configuration.datetime') as clock:
                    clock.now.return_value = moment
                    result = await self.send(message_id=f'scheduled-{index}')
                self.assertEqual(result['result']['reception']['status'], expected)
                self.assertEqual(result['result']['assistant'] is not None, expected == 'answered')
        self.assertEqual(len(self.provider.payloads), 4)

    async def test_offline_reception_obeys_the_full_weekly_schedule(self):
        timezone_info = ZoneInfo('Asia/Shanghai')
        week_start = datetime(2026, 11, 2, tzinfo=timezone_info)
        config = spec()
        config['widget'] = {'timezone': 'Asia/Shanghai', 'hours': [
            {'days': [0, 1, 2, 3, 4], 'start': '09:00', 'end': '17:00'},
            {'days': [5], 'start': '10:00', 'end': '12:00'},
        ]}
        config['ai_reception'] = {**self.config['ai_reception'], 'mode': 'offline'}
        self.publish(config, 'sandbox-weekly-offline')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')

        cases = []
        for weekday in range(5):
            day = week_start + timedelta(days=weekday)
            cases.extend((
                (day + timedelta(hours=9), 'outside_schedule'),
                (day + timedelta(hours=17), 'answered'),
            ))
        saturday = week_start + timedelta(days=5)
        cases.extend((
            (saturday + timedelta(hours=10), 'outside_schedule'),
            (saturday + timedelta(hours=12), 'answered'),
            (week_start + timedelta(days=6, hours=12), 'answered'),
        ))

        for index, (local_moment, expected) in enumerate(cases, start=1):
            with self.subTest(local_moment=local_moment.isoformat()):
                moment = local_moment.astimezone(timezone.utc)
                with patch('loomrise.widget_configuration.datetime') as clock:
                    clock.now.return_value = moment
                    result = await self.send(message_id=f'weekly-offline-{index}')
                self.assertEqual(result['result']['reception']['status'], expected)
                self.assertEqual(result['result']['assistant'] is not None, expected == 'answered')

        self.assertEqual(len(self.provider.payloads), 7)
        self.assertEqual(len(self.messages()), 20)

    def test_widget_schedule_respects_daylight_saving_gaps_and_repeated_hours(self):
        spring = {'widget': {'timezone': 'America/New_York',
            'hours': [{'days': [6], 'start': '02:00', 'end': '03:30'}]}}
        self.assertEqual(public_widget_configuration(spring, at=datetime(
            2026, 3, 8, 6, 59, tzinfo=timezone.utc))['availability'], 'closed')
        self.assertEqual(public_widget_configuration(spring, at=datetime(
            2026, 3, 8, 7, 0, tzinfo=timezone.utc))['availability'], 'open')

        fall = {'widget': {'timezone': 'America/New_York',
            'hours': [{'days': [6], 'start': '01:30', 'end': '01:45'}]}}
        self.assertEqual(public_widget_configuration(fall, at=datetime(
            2026, 11, 1, 5, 29, tzinfo=timezone.utc))['availability'], 'closed')
        self.assertEqual(public_widget_configuration(fall, at=datetime(
            2026, 11, 1, 5, 30, tzinfo=timezone.utc))['availability'], 'open')
        self.assertEqual(public_widget_configuration(fall, at=datetime(
            2026, 11, 1, 6, 44, tzinfo=timezone.utc))['availability'], 'open')
        self.assertEqual(public_widget_configuration(fall, at=datetime(
            2026, 11, 1, 6, 45, tzinfo=timezone.utc))['availability'], 'closed')

    def test_weekly_overnight_schedule_keeps_start_day_and_half_open_end(self):
        config = {'widget': {'timezone': 'Asia/Shanghai',
            'hours': [{'days': [4, 6], 'start': '22:00', 'end': '02:00'}]}}
        cases = [
            (datetime(2026, 11, 6, 13, 59, tzinfo=timezone.utc), 'closed'),
            (datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc), 'open'),
            (datetime(2026, 11, 6, 17, 59, tzinfo=timezone.utc), 'open'),
            (datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc), 'closed'),
            (datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc), 'open'),
            (datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc), 'closed'),
            (datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc), 'closed'),
        ]
        for moment, expected in cases:
            with self.subTest(moment=moment.isoformat()):
                self.assertEqual(public_widget_configuration(config, at=moment)['availability'], expected)

    def test_weekly_schedule_maps_weekdays_and_weekend_half_open_boundaries(self):
        timezone_info = ZoneInfo('Asia/Shanghai')
        week_start = datetime(2026, 11, 2, tzinfo=timezone_info)
        config = {'widget': {'timezone': 'Asia/Shanghai', 'hours': [
            {'days': [0, 1, 2, 3, 4], 'start': '09:00', 'end': '17:00'},
            {'days': [5], 'start': '10:00', 'end': '12:00'},
        ]}}
        cases = []
        for weekday in range(5):
            day = week_start + timedelta(days=weekday)
            cases.extend((
                (day + timedelta(hours=8, minutes=59), 'closed'),
                (day + timedelta(hours=9), 'open'),
                (day + timedelta(hours=17), 'closed'),
            ))
        saturday = week_start + timedelta(days=5)
        cases.extend((
            (saturday + timedelta(hours=9, minutes=59), 'closed'),
            (saturday + timedelta(hours=10), 'open'),
            (saturday + timedelta(hours=12), 'closed'),
            (week_start + timedelta(days=6, hours=12), 'closed'),
        ))
        for local_moment, expected in cases:
            with self.subTest(local_moment=local_moment.isoformat()):
                moment = local_moment.astimezone(timezone.utc)
                self.assertEqual(public_widget_configuration(config, at=moment)['availability'], expected)

    async def test_widget_guidance_is_the_only_initial_welcome_surface(self):
        config = spec()
        config['persona']['greeting'] = 'Bot 身份欢迎语。'
        config['widget'] = {'greeting': 'Widget 引导语。'}
        config['ai_reception'] = self.config['ai_reception']
        self.publish(config, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')

        widget = self.service.widget_configuration(
            principal=self.owner, agent_id='expert-a', entry_id='entry-a',
            conversation_id=self.session['conversation_id'], visitor_token=self.session['visitor_token'])
        self.assertEqual(widget['widget']['greeting'], 'Widget 引导语。')
        self.assertEqual(self.messages(), [])

        await self.send()

        messages = self.messages()
        self.assertEqual([message['sender'] for message in messages], ['visitor', 'assistant'])
        self.assertNotIn('Bot 身份欢迎语。', json.dumps(messages, ensure_ascii=False))
        self.assertNotIn('Widget 引导语。', json.dumps(messages, ensure_ascii=False))

    async def test_entry_new_version_does_not_change_existing_conversation(self):
        self.publish(spec('新的专家目标'), 'sandbox-v2')
        result = await self.send()
        self.assertEqual(result['result']['reception']['version_id'], 'sandbox-v1')
        self.assertEqual(self.provider.payloads[0]['persona']['goal'], self.config['persona']['goal'])

    async def test_existing_offline_conversation_keeps_its_schedule_after_new_version_is_published(self):
        offline = spec('旧版离线接待')
        offline['ai_reception'] = {**self.config['ai_reception'], 'mode': 'offline'}
        offline['widget'] = {'timezone': 'Asia/Shanghai',
            'hours': [{'days': [0], 'start': '09:00', 'end': '17:00'}]}
        self.publish(offline, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        conversation_id = self.session['conversation_id']

        with patch('loomrise.widget_configuration.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
            first = await self.send(message_id='message-offline')
        self.assertEqual(first['result']['reception']['status'], 'answered')
        self.assertEqual(first['result']['reception']['version_id'], 'sandbox-v2')

        online = spec('新版在线接待')
        online['ai_reception'] = {**self.config['ai_reception'], 'mode': 'always'}
        online['widget'] = offline['widget']
        self.publish(online, 'sandbox-v3')
        current = self.service.widget_configuration(principal=self.owner, agent_id='expert-a', entry_id='entry-a')
        self.assertEqual(current['version_id'], 'sandbox-v3')
        with patch('loomrise.widget_configuration.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
            second = await self.send('在线时段的追问', message_id='message-online')

        self.assertEqual(second['result']['reception']['status'], 'outside_schedule')
        self.assertEqual(second['result']['reception']['version_id'], 'sandbox-v2')
        self.assertEqual(self.session['conversation_id'], conversation_id)
        self.assertEqual([message['text'] for message in self.messages()],
                         ['体验课多少钱？', '体验课价格为 19 元。', '在线时段的追问'])
        self.assertEqual(len(self.provider.payloads), 1)
        self.assertEqual(self.provider.payloads[0]['persona']['goal'], '旧版离线接待')

    async def test_human_request_stops_later_model_calls(self):
        result = await self.send(request_human=True)
        self.assertEqual(result['result']['reception']['status'], 'human_requested')
        later = await self.send('第二条消息', message_id='message-2')
        self.assertEqual(later['result']['reception']['status'], 'human_requested')
        self.assertEqual(self.provider.payloads, [])

    async def test_handoff_phrase_matches_literal_casefolded_text_without_a_model_call(self):
        self.publish({**self.config, 'ai_reception': {**self.config['ai_reception'],
            'handoff_phrases': ['  转人工  ', 'Straße', '[help]']}}, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        missed = await self.send('help please', message_id='literal-miss')
        self.assertEqual(missed['result']['reception']['status'], 'answered')
        self.assertEqual(len(self.provider.payloads), 1)
        matched = await self.send('Bitte STRASSE jetzt', message_id='casefold-match')
        self.assertEqual(matched['result']['reception']['status'], 'human_requested')
        self.assertIsNone(matched['result']['assistant'])
        self.assertEqual(len(self.provider.payloads), 1)
        current = self.service.inbox_list(principal=self.owner, agent_id='expert-a')[0]
        self.assertEqual(current['conversation_id'], self.session['conversation_id'])
        self.assertEqual(current['state'], 'human_requested')
        finished = self.store.load_events(matched['result']['reception']['run_id'])[-1]
        self.assertTrue(finished.payload['handoff_requested'])

    async def test_handoff_phrase_replay_preserves_original_input_hash_and_one_handoff_event(self):
        self.publish({**self.config, 'ai_reception': {**self.config['ai_reception'],
            'handoff_phrases': ['转人工']}}, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        first = await self.send('请转人工', message_id='phrase-match')
        self.assertEqual(first['result']['reception']['status'], 'human_requested')
        events = self.service.inbox_events(principal=self.owner, agent_id='expert-a', after_sequence=0)
        self.assertEqual([event['event_type'] for event in events['events']],
                         ['visitor.message', 'handoff.requested'])
        run_id = first['result']['reception']['run_id']
        run_event_count = len(self.store.load_events(run_id))
        duplicate = await self.send('请转人工', message_id='phrase-match')
        self.assertEqual(duplicate['result'], first['result'])
        self.assertEqual(len(self.messages()), 1)
        self.assertEqual(len(self.store.load_events(run_id)), run_event_count)
        self.assertEqual(self.service.inbox_events(principal=self.owner, agent_id='expert-a', after_sequence=0), events)
        changed_flag = await self.send('请转人工', message_id='phrase-match', request_human=True)
        self.assertFalse(changed_flag['ok'])
        self.assertEqual(len(self.messages()), 1)
        self.assertEqual(self.provider.payloads, [])

    async def test_handoff_phrases_follow_the_conversation_release_and_not_new_drafts(self):
        old_session = self.session
        second_config = {**self.config, 'ai_reception': {**self.config['ai_reception'],
            'handoff_phrases': ['转人工']}}
        self.publish(second_config, 'sandbox-v2')
        second_session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        current = self.configuration.get_draft(tenant_id='tenant-a', agent_id='expert-a')
        third_config = {**second_config, 'ai_reception': {**second_config['ai_reception'],
            'handoff_phrases': ['找客服']}}
        self.configuration.save_draft(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=current['revision'], config=third_config)
        self.session = second_session
        draft_only = await self.send('请找客服', message_id='draft-does-not-match')
        self.assertEqual(draft_only['result']['reception']['status'], 'answered')
        self.publish(third_config, 'sandbox-v3')
        self.session = old_session
        original = await self.send('请转人工', message_id='no-default-phrases')
        self.assertEqual(original['result']['reception']['version_id'], 'sandbox-v1')
        self.assertEqual(original['result']['reception']['status'], 'answered')
        self.session = second_session
        pinned = await self.send('请转人工', message_id='old-phrase-still-matches')
        self.assertEqual(pinned['result']['reception']['version_id'], 'sandbox-v2')
        self.assertEqual(pinned['result']['reception']['status'], 'human_requested')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        latest = await self.send('请找客服', message_id='new-phrase-matches')
        self.assertEqual(latest['result']['reception']['version_id'], 'sandbox-v3')
        self.assertEqual(latest['result']['reception']['status'], 'human_requested')
        self.assertEqual(len(self.provider.payloads), 2)

    async def test_handoff_phrase_preserves_existing_human_owner_and_generation(self):
        self.publish({**self.config, 'ai_reception': {**self.config['ai_reception'],
            'handoff_phrases': ['转人工']}}, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        claimed = self.service.claim(principal=self.owner, agent_id='expert-a',
            conversation_id=self.session['conversation_id'])
        for index, request_human in enumerate((False, True)):
            with self.subTest(request_human=request_human):
                result = await self.send('请转人工', message_id=f'owned-{index}', request_human=request_human)
                self.assertEqual(result['result']['reception']['status'], 'human_requested')
                current = next(item for item in self.service.inbox_list(principal=self.owner, agent_id='expert-a')
                               if item['conversation_id'] == self.session['conversation_id'])
                self.assertEqual(current['state'], 'human')
                self.assertEqual(current['assigned_to'], self.owner.actor_id)
                self.assertEqual(current['occupancy_generation'], claimed['occupancy_generation'])
                finished = self.store.load_events(result['result']['reception']['run_id'])[-1]
                self.assertFalse(finished.payload['handoff_requested'])
        events = self.service.inbox_events(principal=self.owner, agent_id='expert-a', after_sequence=0)['events']
        self.assertNotIn('handoff.requested', [event['event_type'] for event in events])
        self.assertEqual(self.provider.payloads, [])

    async def test_handoff_phrase_fences_an_in_flight_model_answer(self):
        self.publish({**self.config, 'ai_reception': {**self.config['ai_reception'],
            'handoff_phrases': ['转人工']}}, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        pending_release = asyncio.Event()
        self.provider.release = pending_release
        pending = asyncio.create_task(self.send(message_id='pending-answer'))
        await self.provider.started.wait()
        self.provider.release = None
        try:
            requested = await self.send('请转人工', message_id='phrase-during-generation')
        finally:
            pending_release.set()
        delayed = await pending
        self.assertEqual(requested['result']['reception']['status'], 'human_requested')
        self.assertEqual(delayed['result']['reception']['status'], 'superseded')
        self.assertIsNone(delayed['result']['assistant'])
        self.assertEqual(len(self.provider.payloads), 1)
        self.assertEqual([message['sender'] for message in self.messages()], ['visitor', 'visitor'])

    async def test_human_owned_followup_is_not_counted_as_a_new_handoff_request(self):
        first = await self.send(request_human=True)
        followup = await self.send('补充内容', message_id='message-2')
        first_event = next(event for event in self.store.load_events(first['result']['reception']['run_id'])
                           if event.event_type == 'customer.reception.finished')
        followup_event = next(event for event in self.store.load_events(followup['result']['reception']['run_id'])
                              if event.event_type == 'customer.reception.finished')
        self.assertIs(first_event.payload['handoff_requested'], True)
        self.assertIs(followup_event.payload['handoff_requested'], False)

    async def test_duplicate_in_flight_never_starts_second_generation(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        duplicate = await self.send()
        self.assertEqual(duplicate['result']['reception']['status'], 'generating')
        self.assertEqual(len(self.messages()), 1)
        self.provider.release.set()
        await pending
        self.assertEqual(len(self.provider.payloads), 1)

    async def test_cancellation_persists_interrupted_without_resending_input(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'interrupted')
        self.assertEqual(len(self.messages()), 1)

    async def test_recovered_run_cannot_be_resurrected_by_late_model_answer(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.send())
        await self.provider.started.wait()
        receipt = self.messages()[0]['reception']
        self.store.recover(owner_id='next-process')
        self.provider.release.set()
        result = await pending
        self.assertEqual(result['result']['reception']['status'], 'interrupted')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual(self.store.run_row(receipt['run_id'])['status'], 'failed')

    async def test_restarted_server_marks_orphaned_reception_without_replaying(self):
        import hashlib
        self.store.begin_customer_reception(conversation_id=self.session['conversation_id'],
            visitor_token_hash=hashlib.sha256(self.session['visitor_token'].encode()).hexdigest(),
            text='体验课多少钱？', request_human=False, message_id='message-1')
        restored = SqliteStore(self.store.path, owner_id='new-http-instance')
        try:
            restored.recover_customer_receptions()
            service = CustomerService(restored, ConfigurationService(restored), reception_provider=self.provider)
            result = await service.visitor_send_with_reception(conversation_id=self.session['conversation_id'],
                visitor_token=self.session['visitor_token'], text='体验课多少钱？', message_id='message-1')
            self.assertEqual(result['reception']['status'], 'interrupted')
            self.assertEqual(self.provider.payloads, [])
            self.assertEqual(len(self.messages()), 1)
        finally:
            restored.close()

    async def test_context_remains_within_provider_budget(self):
        self.config['persona'].update(name='角色' * 10000, goal='目标' * 10000, audience='访客' * 10000,
                                     scope='范围' * 10000, fallback='转人工' * 10000)
        for i in range(15):
            source = self.configuration.create_knowledge_source(tenant_id='tenant-a', agent_id='expert-a',
                kind='faq', locator='这是补充说明材料。' * 2000, display_name='附加资料', authorization='owned')
            source = self.configuration.ingest_knowledge_source(tenant_id='tenant-a', agent_id='expert-a', source_id=source['source_id'])
            self.config['ai_reception']['sources'].append({'source_id': source['source_id'], 'content_hash': source['content_hash']})
        self.publish(self.config, 'sandbox-v2')
        self.session = self.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        for i in range(12):
            self.service.visitor_send(conversation_id=self.session['conversation_id'], visitor_token=self.session['visitor_token'], text='访客内容' * 1000)
        await self.send('长问题' * 2500)
        self.assertLess(len(json.dumps(self.provider.payloads[0], ensure_ascii=False).encode()), 64000)

    async def test_provider_budget_is_per_turn(self):
        original = self.provider
        class Factory:
            def for_run(self):
                return original
        self.service.reception.provider = Factory()
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'answered')

    async def test_changed_provider_model_cannot_run_under_the_old_approved_version(self):
        self.provider.model = 'unapproved-model'
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'model_changed')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual(self.provider.payloads, [])

    async def test_later_sources_do_not_expand_approved_allowlist(self):
        extra = self.configuration.create_knowledge_source(tenant_id='tenant-a', agent_id='expert-a',
            kind='faq', locator='未经此版本批准的内容', display_name='另一份资料', authorization='owned')
        self.configuration.ingest_knowledge_source(tenant_id='tenant-a', agent_id='expert-a', source_id=extra['source_id'])
        await self.send()
        self.assertEqual([source['source_id'] for source in self.provider.payloads[0]['sources']], [self.source['source_id']])

    async def test_http_generation_yields_to_human_claim_and_returns_persisted_status(self):
        from aiohttp.test_utils import TestClient, TestServer
        from loomrise.config_http import create_configuration_http_app
        path = Path(self.tmp.name) / 'principal.json'
        path.write_text(json.dumps({'tenant_id': 'tenant-a', 'actor_id': 'owner', 'role': 'owner',
                                    'agent_ids': ['expert-a']}), encoding='utf-8')
        os.chmod(path, 0o600)
        app = create_configuration_http_app(principal_path=path, database_path=self.store.path,
                                            reception_provider=self.provider)
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(client.post('/api/customer-service', json={'action': 'widget.send', 'payload': {
            'conversation_id': self.session['conversation_id'], 'visitor_token': self.session['visitor_token'],
            'text': '体验课多少钱？', 'message_id': 'http-message'}}))
        await asyncio.wait_for(self.provider.started.wait(), 2)
        claimed = await client.post('/api/customer-service', json={'action': 'inbox.claim', 'payload': {
            'agent_id': 'expert-a', 'conversation_id': self.session['conversation_id']}})
        self.assertEqual(claimed.status, 200)
        self.assertTrue((await claimed.json())['ok'])
        self.provider.release.set()
        response = await pending
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body['result']['reception']['status'], 'superseded')
        self.assertIsNone(body['result']['assistant'])
        self.assertEqual(len(self.messages()), 1)

    async def test_completed_turn_and_citations_survive_backup_restore(self):
        response = await self.send()
        backup = str(Path(self.tmp.name) / 'backup.db')
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            service = CustomerService(restored, ConfigurationService(restored), reception_provider=self.provider)
            messages = service.visitor_messages(conversation_id=self.session['conversation_id'], visitor_token=self.session['visitor_token'])
            self.assertEqual(messages[1]['citations'][0]['content_hash'], self.source['content_hash'])
            result = await service.visitor_send_with_reception(conversation_id=self.session['conversation_id'],
                visitor_token=self.session['visitor_token'], text='体验课多少钱？', message_id='message-1')
            self.assertEqual(result['reception']['run_id'], response['result']['reception']['run_id'])
            self.assertEqual(len(self.provider.payloads), 1)
        finally:
            restored.close()

    async def test_provider_failure_accepts_input_once_without_leaking_error(self):
        self.provider.failure = RuntimeError('sk-private-secret https://private.provider.invalid')
        result = await self.send()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['reception']['status'], 'provider_error')
        self.assertNotIn('private', str(result))
        self.assertEqual(len(self.messages()), 1)
        again = await self.send()
        self.assertEqual(again['result']['reception']['status'], 'provider_error')
        self.assertEqual(len(self.provider.payloads), 1)

    async def test_missing_provider_has_explicit_status_and_no_fake_answer(self):
        self.service.reception.provider = None
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'not_configured')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual(len(self.messages()), 1)

    async def test_unknown_citation_is_rejected_and_handoff_is_persisted(self):
        self.provider.response = {'text': '无法核验', 'citations': [{'source_id': 'unknown', 'quote': '伪造'}], 'handoff': False, 'provider': {}}
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'invalid_response')
        self.assertIsNone(result['result']['assistant'])
        self.assertEqual(self.service.inbox_list(principal=self.owner, agent_id='expert-a')[0]['state'], 'human_requested')

    async def test_missing_evidence_handoff_uses_approved_fallback(self):
        self.provider.response = {'text': '未经证实的业务承诺', 'citations': [], 'handoff': True, 'provider': {}}
        result = await self.send()
        self.assertEqual(result['result']['reception']['status'], 'handoff')
        self.assertNotIn('未经证实', result['result']['assistant']['text'])
        self.assertEqual(self.service.inbox_list(principal=self.owner, agent_id='expert-a')[0]['state'], 'human_requested')

    async def test_message_byte_limit_is_checked_before_accepting(self):
        result = await self.send('😀' * 17000)
        self.assertFalse(result['ok'])
        self.assertEqual(self.messages(), [])


class ReceptionConfigurationCase(unittest.TestCase):
    def test_invalid_policy_cannot_freeze(self):
        for config in ({'enabled': 'yes'}, {'enabled': True, 'mode': 'sometimes'},
                       {'enabled': True, 'sources': [{'source_id': 's', 'content_hash': 'wrong'}]},
                       {'api_key': 'never-allowed'}):
            value = spec()
            value['ai_reception'] = config
            self.assertTrue(any(issue.code == 'invalid_ai_reception' for issue in validate_configuration(value, submitting=True)), config)


if __name__ == '__main__':
    unittest.main()
