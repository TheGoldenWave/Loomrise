from __future__ import annotations

from copy import deepcopy
import json
import unittest

from loomrise.customer_statistics import aggregate_reception_statistics
from loomrise.configuration import ConfigurationPrincipal
from loomrise.customer_service import CustomerService, CustomerServiceApplication


START = '2026-11-01T00:00:00+00:00'
END = '2026-11-02T00:00:00+00:00'
OBSERVED = '2026-11-03T00:00:00+00:00'


def events(run='r', request=None, *, start=START, finish='2026-11-01T00:00:00.025+00:00',
           status='answered', generated=True, published=True, usage=None, model='observed-model', version='v1',
           handoff_requested=None):
    request = request or f'q-{run}'
    metadata = dict(scope_tenant_id='t', scope_agent_id='a', conversation_id=f'c-{run}', entry_id='web-entry',
                    release_version=version, turn_input_sequence=1, turn_request_id=request, turn_run_id=run,
                    turn_version_id=version, run_request_id=request, run_tenant_id='t', run_version_id=version,
                    request_tenant_id='t', request_version_id=version)
    metadata['run_snapshot_json'] = json.dumps({'kind': 'customer_reception', 'agent_id': 'a',
        'conversation_id': metadata['conversation_id'], 'input_sequence': 1})
    values = [('started', start, {'conversation_id': metadata['conversation_id'], 'input_sequence': 1,
                                'generation': 0, 'read_only': True})]
    if generated:
        provider = {'provider_response_id': 'same-response-id', 'usage': usage if usage is not None else {'input_tokens': 0, 'output_tokens': 8}}
        if model is not None:
            provider['model'] = model
        values.append(('generated', start, {'text_hash': 'a' * 64, 'provider': provider, 'delivery': 'not_sent'}))
    if published:
        values.append(('published', finish or start, {'conversation_id': metadata['conversation_id'], 'input_sequence': 1,
            'response_sequence': 2, 'delivery': 'stored_for_visitor', 'problem_resolved': False}))
    if finish is not None:
        finished = {'status': status, 'input_sequence': 1, 'response_sequence': 2 if published else None,
                    'read_only': True, 'problem_resolved': False}
        if handoff_requested is not None:
            finished['handoff_requested'] = handoff_requested
        values.append(('finished', finish, finished))
    rows = []
    for sequence, (kind, instant, payload) in enumerate(values, 1):
        event = dict(seq=sequence, run_id=run, request_id=request, tenant_id='t', agent_version=version,
                     channel='text', event_type=f'customer.reception.{kind}', ts=instant, payload=payload)
        rows.append({**metadata, 'rid': sequence, 'run_id': run, 'seq': sequence, 'request_id': request,
                     'event_type': event['event_type'], 'ts': instant, 'payload_json': json.dumps(payload),
                     'prev_hash': '0' * 64, 'hash': '1' * 64, 'event_json': json.dumps(event)})
    return rows


def append_event(rows, run_id, request_id, event_type, payload):
    scoped = next(row for row in rows if row['run_id'] == run_id)
    sequence = max(row['seq'] for row in rows if row['run_id'] == run_id) + 1
    instant = END
    event = {'seq': sequence, 'run_id': run_id, 'request_id': request_id, 'tenant_id': 't',
             'agent_version': scoped['release_version'], 'channel': 'text', 'event_type': event_type,
             'ts': instant, 'payload': payload}
    rows.append({**scoped, 'rid': sequence, 'seq': sequence, 'request_id': request_id,
                 'event_type': event_type, 'ts': instant, 'payload_json': json.dumps(payload),
                 'event_json': json.dumps(event)})


def project(rows, **filters):
    return aggregate_reception_statistics(rows, tenant_id='t', agent_id='a', from_ts=START, to_ts=END,
                                          as_of=OBSERVED, **filters)


def rewrite(row, **values):
    event = json.loads(row['event_json'])
    event.update(values)
    row.update({key: value for key, value in values.items() if key in row})
    row['event_json'] = json.dumps(event)
    if 'payload' in values:
        row['payload_json'] = json.dumps(values['payload'])


class ReceptionStatisticsTests(unittest.TestCase):
    def test_half_open_cohort_normalizes_offsets_and_keeps_finish_outside_window(self):
        rows = events('at-from', start='2026-11-01T01:00:00+01:00', finish='2026-11-02T01:00:00Z')
        rows += events('at-to', start=END) + events('before', start='2026-10-31T23:59:59Z', finish=START)
        result = project(rows)
        self.assertEqual((result['request_count'], result['run_count']), (1, 1))
        self.assertEqual(result['processing_latency']['sample_count'], 1)
        self.assertEqual(result['scope']['from'], START)
        self.assertEqual(result['scope']['basis'], 'customer.reception.started')
        self.assertEqual(result['scope']['as_of'], OBSERVED)
        self.assertEqual(result['entries'], {'web-entry': 1})

    def test_filter_validation_and_unsupported_voice_are_explicit(self):
        for changes in ({'from_ts': START}, {'from_ts': START, 'to_ts': START},
                        {'from_ts': '2026-11-01T00:00:00', 'to_ts': END}, {'channel': 'telegram'},
                        {'version_id': ''}, {'version_id': 4}, {'as_of': 'bad'}):
            options = dict(tenant_id='t', agent_id='a', as_of=OBSERVED)
            options.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                aggregate_reception_statistics([], **options)
        result = project(events(), channel='voice')
        self.assertEqual(result['run_count'], 0)
        self.assertFalse(result['coverage']['requested_channel_supported'])
        self.assertEqual(result['coverage']['supported_channels'], ['text'])
        all_time = aggregate_reception_statistics(events(), tenant_id='t', agent_id='a', as_of=OBSERVED)
        self.assertIsNone(all_time['scope']['from'])

    def test_distinct_requests_versions_and_no_delivery_or_historical_handoff_claims(self):
        rows = events('one', request='same') + events('two', request='same') + events('v2', version='v2')
        result = project(rows)
        self.assertEqual((result['request_count'], result['run_count']), (2, 3))
        self.assertEqual(result['versions'], {'v1': 1, 'v2': 1})
        self.assertEqual(project(rows, version_id='v2')['run_count'], 1)
        self.assertIsNone(result['handoff']['requested_count'])
        self.assertIsNone(result['handoff']['claimed_count'])
        self.assertEqual(result['handoff']['request_missing_count'], 2)
        self.assertEqual(result['handoff']['claim_missing_count'], 2)
        self.assertEqual(result['handoff']['reason'], 'historical_transition_events_not_recorded')
        self.assertIsNone(result['visitor_latency_ms'])
        self.assertEqual(result['delivery'], 'unknown')
        serialized = json.dumps(result)
        self.assertNotIn('same-response-id', serialized)
        self.assertNotIn('text_hash', serialized)

    def test_handoff_counts_require_explicit_event_facts_and_preserve_legacy_unknowns(self):
        rows = (events('requested', status='human_requested', handoff_requested=True)
                + events('not-requested', status='answered', handoff_requested=False)
                + events('legacy', status='handoff'))
        append_event(rows, 'requested', 'q-requested', 'customer.handoff.claimed', {
            'conversation_id': 'c-requested', 'actor_id': 'owner', 'occupancy_generation': 1,
        })
        result = project(rows)
        self.assertEqual(result['handoff']['requested_count'], 1)
        self.assertEqual(result['handoff']['request_sample_count'], 2)
        self.assertEqual(result['handoff']['request_missing_count'], 1)
        self.assertEqual(result['handoff']['claimed_count'], 1)
        self.assertIsNone(result['visitor_latency_ms'])
        self.assertEqual(result['delivery'], 'unknown')

    def test_claimed_zero_is_known_only_for_runs_marked_with_handoff_tracking(self):
        tracked = events('tracked')
        row = next(item for item in tracked if item['event_type'] == 'customer.reception.finished')
        finished = json.loads(row['payload_json'])
        finished['handoff_tracking_version'] = 1
        rewrite(row, payload=finished)
        result = project(tracked)
        self.assertEqual(result['handoff']['claimed_count'], 0)
        self.assertEqual(result['handoff']['claim_sample_count'], 1)
        self.assertEqual(result['handoff']['claim_missing_count'], 0)

    def test_foreign_aliases_snapshot_and_envelope_cannot_enter_cohort(self):
        rows = events('mine')
        for index, (field, value) in enumerate((('scope_tenant_id', 'foreign'), ('scope_agent_id', 'other'),
                ('run_tenant_id', 'foreign'), ('request_tenant_id', 'foreign'), ('run_request_id', 'other'),
                ('request_version_id', 'other'), ('turn_version_id', 'other'), ('release_version', 'other'))):
            bad = events(f'bad-{index}')
            for row in bad:
                row[field] = value
            rows += bad
        for value in ({'kind': 'generic', 'agent_id': 'a'}, {'kind': 'customer_reception', 'agent_id': 'other'}, [], 'bad'):
            bad = events(f'snapshot-{len(rows)}')
            for row in bad:
                row['run_snapshot_json'] = json.dumps(value)
            rows += bad
        for key, value in (('tenant_id', 'other'), ('request_id', 'other'), ('agent_version', 'other'),
                           ('channel', 'voice'), ('seq', True)):
            bad = events(f'envelope-{key}')
            event = json.loads(bad[0]['event_json']); event[key] = value; bad[0]['event_json'] = json.dumps(event)
            rows += bad
        result = project(rows)
        self.assertEqual(result['run_count'], 1)
        self.assertGreater(result['coverage']['ignored_record_count'], 0)

    def test_duplicate_starts_and_finishes_do_not_manufacture_samples(self):
        duplicate_start = events('two-starts')
        row = deepcopy(duplicate_start[0]); rewrite(row, seq=99); duplicate_start.append(row)
        duplicate_finish = events('two-finishes')
        row = deepcopy(duplicate_finish[-1]); rewrite(row, seq=99); duplicate_finish.append(row)
        result = project(events('valid') + duplicate_start + duplicate_finish)
        self.assertEqual(result['run_count'], 2)
        self.assertEqual(result['processing_latency']['sample_count'], 1)
        self.assertEqual(result['processing_latency']['missing_count'], 1)
        self.assertGreater(result['coverage']['ignored_record_count'], 0)

    def test_latency_zero_decimal_missing_reverse_interrupted_and_observation_cutoff(self):
        rows = events('zero', finish=START) + events('decimal', finish='2026-11-01T00:00:00.025Z')
        rows += events('pending', finish=None, published=False)
        rows += events('reverse', finish='2026-10-31T23:59:59Z')
        rows += events('interrupted', status='interrupted', generated=False, published=False)
        rows += events('future-finish', finish='2026-11-04T00:00:00Z')
        result = project(rows)
        self.assertEqual(result['processing_latency']['mean_ms'], 12.5)
        self.assertEqual(result['processing_latency']['sample_count'], 2)
        self.assertEqual(result['processing_latency']['missing_count'], 4)
        self.assertEqual(result['processing_latency']['clock'], 'server_event_wall_clock')
        self.assertEqual(result['reception_outcomes']['interrupted'], 1)

    def test_generated_superseded_usage_partial_unknown_and_zero_stay_distinct(self):
        rows = events('zero', usage={'input_tokens': 0, 'output_tokens': 0})
        rows += events('partial', usage={'input_tokens': 5}, status='superseded', published=False)
        rows += events('invalid-counts', usage={'input_tokens': True, 'output_tokens': -3})
        rows += events('unknown-model', usage={'output_tokens': 8}, model=None)
        rows += events('same-id', usage={'input_tokens': 5, 'output_tokens': 7})
        rows += events('no-generated', generated=False, published=False, status='provider_error')
        result = project(rows)
        usage = result['model_usage']
        self.assertEqual((usage['input_tokens'], usage['output_tokens']), (10, 15))
        self.assertEqual((usage['input_sample_count'], usage['output_sample_count']), (3, 3))
        self.assertEqual((usage['input_missing_count'], usage['output_missing_count']), (3, 3))
        self.assertEqual(usage['runs_without_usage'], 2)
        self.assertTrue(any(row['model'] is None for row in usage['by_model']))
        self.assertEqual((result['generated_count'], result['published_count']), (5, 4))
        self.assertEqual(project(events('none', generated=False, published=False))['model_usage']['input_tokens'], None)

    def test_missing_start_bad_payload_and_generic_model_event_do_not_become_metrics(self):
        rows = events('missing-start')[1:]
        bad = events('bad-start'); rewrite(bad[0], payload={'conversation_id': 'other', 'input_sequence': 1})
        generic = events('generic'); rewrite(generic[0], event_type='model.call_end', payload={'input_tokens': 999})
        result = project(rows + bad + generic)
        self.assertEqual(result['run_count'], 0)
        self.assertEqual(result['coverage']['missing_start_run_count'], 3)

    def test_repeated_reader_rows_do_not_repeat_usage_and_mismatched_payload_is_ignored(self):
        rows = events()
        result = project(rows + [deepcopy(rows[1])])
        self.assertEqual(result['generated_count'], 1)
        self.assertEqual(result['model_usage']['output_tokens'], 8)
        rows[1]['payload_json'] = '{}'
        result = project(rows)
        self.assertEqual(result['generated_count'], 0)
        self.assertIsNone(result['model_usage']['output_tokens'])


class StatisticsApiTests(unittest.TestCase):
    def test_api_keeps_cumulative_fields_and_rejects_spoofed_or_invalid_scope(self):
        class Store:
            def customer_statistics(self, **scope):
                return {'conversation_count': 4, 'response_latency_ms': None, 'states': {'human': 2}}
            def customer_reception_statistics_rows(self, **scope):
                self.scope = scope
                return events()
        store = Store()
        app = CustomerServiceApplication(CustomerService(store, None))
        principal = ConfigurationPrincipal(tenant_id='t', actor_id='operator', role='viewer', agent_ids=('a',))
        result = app.execute(principal=principal, action='customer.statistics', payload={'agent_id': 'a', 'from': START, 'to': END})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['conversation_count'], 4)
        self.assertEqual(result['result']['states'], {'human': 2})
        self.assertIsNone(result['result']['response_latency_ms'])
        self.assertEqual(store.scope, {'tenant_id': 't', 'agent_id': 'a'})
        self.assertIn('reception', result['result'])
        for extra in ({'tenant_id': 'other'}, {'actor_id': 'other'}, {'channel': 'email'}, {'from': START}, {'version_id': None}):
            response = app.execute(principal=principal, action='customer.statistics', payload={'agent_id': 'a', **extra})
            self.assertFalse(response['ok'], extra)
        forbidden = app.execute(principal=principal, action='customer.statistics', payload={'agent_id': 'other'})
        self.assertEqual(forbidden['error']['code'], 'forbidden')


if __name__ == '__main__':
    unittest.main()
