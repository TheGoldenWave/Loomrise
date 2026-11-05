from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import unittest

import loomrise.widget_configuration as widget_configuration
from loomrise.widget_configuration import (
    public_widget_configuration, validate_ai_reception_configuration, validate_visitor_fields,
    validate_widget_configuration,
)


class _BookingLinkMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.booking = None
        self.booking_parent = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get('id') == 'booking':
            self.booking = attributes
            self.booking_parent = self.stack[-1] if self.stack else None
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]


class WidgetConfigurationTests(unittest.TestCase):
    def test_handoff_phrases_are_optional_trimmed_bounded_and_casefold_unique(self):
        self.assertEqual(validate_ai_reception_configuration({}).get('handoff_phrases'), [])
        try:
            normalized = validate_ai_reception_configuration({
                'handoff_phrases': ['  转人工  ', '🙂' * 100],
            })
        except ValueError as exc:
            self.fail(f'valid handoff phrases were rejected: {exc}')
        self.assertEqual(normalized['handoff_phrases'], ['转人工', '🙂' * 100])
        twenty = [f'人工 {index}' for index in range(20)]
        self.assertEqual(validate_ai_reception_configuration({'handoff_phrases': twenty})['handoff_phrases'], twenty)
        for phrases in (None, '转人工', {}, [None], [True], [42], [''], [' \t '],
                        ['客服\x00'], ['🙂' * 101], twenty + ['第 21 项'],
                        ['HELP', ' help '], ['Straße', 'STRASSE']):
            with self.subTest(phrases=phrases), self.assertRaises(ValueError):
                validate_ai_reception_configuration({'handoff_phrases': phrases})

    def test_handoff_phrases_are_not_part_of_the_public_widget_projection(self):
        config = {'ai_reception': {'handoff_phrases': ['private-handoff-phrase']}}
        self.assertNotIn('handoff_phrases', public_widget_configuration(config))
        self.assertNotIn('private-handoff-phrase', str(public_widget_configuration(config)))

    def test_faq_suggestions_require_an_exact_approved_source_version(self):
        source = {'source_id': 'source-1', 'content_hash': 'a' * 64}
        try:
            value = validate_ai_reception_configuration({
                'enabled': True,
                'model_id': 'fixture-model',
                'sources': [source],
                'faq_suggestions': [{'question': '体验课多少钱？', **source}],
            })
        except ValueError as exc:
            self.fail(f'valid version-bound FAQ suggestions were rejected: {exc}')
        self.assertEqual(value['faq_suggestions'], [{'question': '体验课多少钱？', **source}])

        for suggestion in (
            {'question': '体验课多少钱？', 'source_id': 'source-2', 'content_hash': 'a' * 64},
            {'question': '体验课多少钱？', 'source_id': 'source-1', 'content_hash': 'b' * 64},
        ):
            with self.subTest(suggestion=suggestion), self.assertRaisesRegex(ValueError, '精确来源版本'):
                validate_ai_reception_configuration({
                    'enabled': True, 'model_id': 'fixture-model', 'sources': [source],
                    'faq_suggestions': [suggestion],
                })

    def test_faq_suggestions_are_bounded_and_unique(self):
        source = {'source_id': 'source-1', 'content_hash': 'a' * 64}
        base = {'enabled': True, 'model_id': 'fixture-model', 'sources': [source]}
        with self.assertRaisesRegex(ValueError, '最多 8 项'):
            validate_ai_reception_configuration({**base, 'faq_suggestions': [
                {'question': f'问题 {index}', **source} for index in range(9)
            ]})

        for suggestions, message in (
            ([{'question': '   ', **source}], '非空且不超过 160 字符'),
            ([{'question': 'Q' * 161, **source}], '非空且不超过 160 字符'),
            ([{'question': '问题\x00文本', **source}], '非空且不超过 160 字符'),
            ([{'question': '相同问题', **source}, {'question': '相同问题', **source}], '不能重复'),
        ):
            with self.subTest(suggestions=suggestions), self.assertRaisesRegex(ValueError, message):
                validate_ai_reception_configuration({**base, 'faq_suggestions': suggestions})

    def test_public_faq_suggestions_expose_only_question_text_and_require_enabled_ai(self):
        source = {'source_id': 'private-source-id', 'content_hash': 'a' * 64}
        config = {'ai_reception': {
            'enabled': True,
            'model_id': 'fixture-model',
            'sources': [source],
            'faq_suggestions': [{'question': '体验课多少钱？', **source}],
        }}
        public_projection = getattr(widget_configuration, 'public_faq_suggestions', None)
        self.assertTrue(callable(public_projection), 'public FAQ question projection is missing')
        suggestions = public_projection(config)
        self.assertEqual(suggestions, ['体验课多少钱？'])
        self.assertNotIn('private-source-id', str(suggestions))
        self.assertNotIn('a' * 64, str(suggestions))
        self.assertNotIn('fixture-model', str(suggestions))

        config['ai_reception']['enabled'] = False
        self.assertEqual(public_projection(config), [])
        self.assertEqual(public_projection({'widget': {'title': '联系页'}}), [])

    def test_empty_and_maximum_display_text_values_are_supported(self):
        empty = validate_widget_configuration({'title': '', 'greeting': '', 'offline_message': ''})
        self.assertEqual((empty['title'], empty['greeting'], empty['offline_message']), ('', '', ''))

        maximum = validate_widget_configuration({
            'title': 'T' * 100, 'greeting': 'G' * 2000, 'offline_message': 'O' * 2000,
            'language': 'en',
        })
        self.assertEqual(len(maximum['title']), 100)
        self.assertEqual(len(maximum['greeting']), 2000)
        self.assertEqual(len(maximum['offline_message']), 2000)
        self.assertEqual(maximum['language'], 'en')

        for field, value in (('title', 'T' * 101), ('greeting', 'G' * 2001),
                             ('offline_message', 'O' * 2001)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_widget_configuration({field: value})

    def test_only_declared_widget_languages_are_accepted(self):
        for language in ('zh-CN', 'en'):
            with self.subTest(language=language):
                self.assertEqual(validate_widget_configuration({'language': language})['language'], language)
        for language in ('', 'zh', 'fr', None):
            with self.subTest(language=language), self.assertRaises(ValueError):
                validate_widget_configuration({'language': language})

    def test_only_public_fields_are_returned_and_timezone_overnight_hours_are_correct(self):
        config = {'persona': {'name': '虚构客服', 'prompt': 'private'}, 'tools': [{'secret': 'never-public'}],
            'widget': {'schema_version': 'widget-v1', 'title': '咨询', 'timezone': 'Asia/Shanghai',
                'hours': [{'days': [0], 'start': '22:00', 'end': '02:00'}]}}
        during = public_widget_configuration(config, at=datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(during['availability'], 'open')
        after = public_widget_configuration(config, at=datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(after['availability'], 'closed')
        self.assertNotIn('tools', during)
        self.assertNotIn('prompt', str(during))

    def test_weekday_hours_use_inclusive_start_and_exclusive_end(self):
        config = {'widget': {'timezone': 'Asia/Shanghai',
            'hours': [{'days': [0], 'start': '09:00', 'end': '17:00'}]}}
        before_open = public_widget_configuration(config, at=datetime(2026, 11, 2, 0, 59, tzinfo=timezone.utc))
        at_open = public_widget_configuration(config, at=datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc))
        at_close = public_widget_configuration(config, at=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))

        self.assertEqual(before_open['availability'], 'closed')
        self.assertEqual(at_open['availability'], 'open')
        self.assertEqual(at_close['availability'], 'closed')

    def test_required_visitor_fields_are_validated_and_unknown_fields_rejected(self):
        widget = public_widget_configuration({'widget': {'fields': [
            {'id': 'name', 'label': '姓名', 'type': 'text', 'required': True},
            {'id': 'email', 'label': '邮箱', 'type': 'email', 'required': False},
            {'id': 'phone', 'label': '电话', 'type': 'tel', 'required': False}]}})
        with self.assertRaises(ValueError): validate_visitor_fields(widget, {})
        with self.assertRaises(ValueError): validate_visitor_fields(widget, {'name': ' \t\n', 'email': '', 'phone': ''})
        with self.assertRaises(ValueError): validate_visitor_fields(widget, {'name': '小林', 'admin': 'true'})
        with self.assertRaises(ValueError): validate_visitor_fields(widget, {'name': '小林', 'email': 'invalid'})
        self.assertEqual(validate_visitor_fields(widget, {'name': ' 小林 ', 'email': '', 'phone': '  '}),
                         {'name': '小林'})
        self.assertEqual(validate_visitor_fields(widget, {'name': ' 小林 ', 'email': 'lin@example.invalid'}),
                         {'name': '小林', 'email': 'lin@example.invalid'})
        self.assertEqual(validate_visitor_fields(widget, {
            'name': ' 小林 ', 'email': 'lin@example.invalid', 'phone': 'call me at 123',
        }), {'name': '小林', 'email': 'lin@example.invalid', 'phone': 'call me at 123'})

    def test_visitor_field_values_enforce_text_boundaries(self):
        widget = public_widget_configuration({'widget': {'fields': [
            {'id': 'name', 'label': '姓名', 'type': 'text', 'required': True},
            {'id': 'email', 'label': '邮箱', 'type': 'email', 'required': False},
        ]}})
        self.assertEqual(validate_visitor_fields(widget, {'name': 'N' * 500}), {'name': 'N' * 500})
        for values in (
            {'name': 'N' * 501}, {'name': 'N\x00'}, {'name': 42},
            {'name': '小林', 'email': 'not-an-email'},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_visitor_fields(widget, values)

    def test_malformed_configuration_is_not_replaced_with_working_defaults(self):
        for value in (None, [], {'timezone': 'invalid'}, {'color': 'red;display:none'},
                      {'enabled': 'false'}, {'hours': '周一全天'}, {'fields': [{'id': 'x'}]},
                      {'schema_version': 'future'}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): public_widget_configuration({'widget': value})

    def test_booking_url_is_optional_and_uses_a_safe_external_link_without_side_effects(self):
        booking_url = 'https://booking.example.test/course'
        configured = public_widget_configuration({'widget': {'booking_url': booking_url}})
        empty = public_widget_configuration({'widget': {'booking_url': ''}})
        self.assertEqual(configured['booking_url'], booking_url)
        self.assertEqual(empty['booking_url'], '')
        for unsafe in ('javascript:alert(1)', 'http://booking.example.test/course',
                       'https://user:password@booking.example.test/course'):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                public_widget_configuration({'widget': {'booking_url': unsafe}})

        template = Path(__file__).parents[1].joinpath('loomrise', 'customer_widget.html').read_text(encoding='utf-8')
        markup = _BookingLinkMarkup()
        markup.feed(template)
        self.assertEqual(markup.booking_parent, 'section')
        self.assertTrue({'hidden'} <= set(markup.booking))
        self.assertEqual(markup.booking['target'], '_blank')
        self.assertTrue({'noopener', 'noreferrer'} <= set(markup.booking['rel'].split()))
        self.assertNotIn('onclick', markup.booking)

        self.assertIn("booking.hidden = !widget.booking_url", template)
        self.assertIn("if (widget.booking_url) { booking.href = widget.booking_url", template)
        self.assertNotRegex(template, r"booking\.(?:onclick|addEventListener)|querySelector\(['\"]#booking['\"]\)\.addEventListener")
        self.assertNotIn('booking.success', template)


if __name__ == '__main__':
    unittest.main()
