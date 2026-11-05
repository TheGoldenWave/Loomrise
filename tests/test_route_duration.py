import unittest
from loomrise.graph_runtime import GraphRuntime
from tests.test_graph_runtime import config


class RouteDurationTests(unittest.TestCase):
    def test_route_finished_emits_measured_route_duration(self):
        events = []
        runtime = GraphRuntime(config())
        runtime.route_and_emit({}, lambda event_type, **payload: events.append((event_type, payload)))
        finished = [payload for event, payload in events if event == 'route.graph.finished'][-1]
        self.assertIsInstance(finished['duration_ms'], int)
        self.assertGreaterEqual(finished['duration_ms'], 0)


if __name__ == '__main__': unittest.main()
