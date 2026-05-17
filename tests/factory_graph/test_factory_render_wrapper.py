from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.graph import build_factory_graph
from agent_factory.factory_graph.render_manifest import FACTORY_NODE_RENDER_SPECS, get_factory_node_render_spec
from agent_factory.factory_graph.render_wrapper import wrap_factory_node


class FactoryRenderManifestTest(unittest.TestCase):
    def test_factory_render_manifest_covers_all_stages(self) -> None:
        for stage_id in STAGE_IDS:
            with self.subTest(stage_id=stage_id):
                spec = FACTORY_NODE_RENDER_SPECS[stage_id]
                self.assertEqual(spec.node_id, stage_id)
                self.assertTrue(spec.label)
                self.assertTrue(spec.kind)
                self.assertTrue(spec.purpose)
                self.assertTrue(spec.doing)
                self.assertTrue(spec.expected_output)


class FactoryRenderWrapperTest(unittest.TestCase):
    def test_wrap_factory_node_emits_started_and_completed_without_mutating_patch(self) -> None:
        events = []
        patch = {
            "current_stage": "requirement_capture",
            "stage_log": [
                {
                    "stage_id": "requirement_capture",
                    "status": "done",
                    "message": "requirement ready",
                }
            ],
        }

        def runner(state):
            return patch

        wrapped = wrap_factory_node(
            node_id="requirement_capture",
            runner=runner,
            render_spec=get_factory_node_render_spec("requirement_capture"),
        )

        with patch_stream_writer(events.append):
            result = wrapped({"status": "running"})

        self.assertIs(result, patch)
        self.assertEqual([event["payload"]["event_type"] for event in events], ["node_started", "node_completed"])
        self.assertEqual(events[0]["payload"]["node_label"], "需求捕获")
        self.assertEqual(events[1]["payload"]["payload"]["output_summary"], "requirement ready")

    def test_wrap_factory_node_emits_failed_and_reraises(self) -> None:
        events = []

        def runner(state):
            raise RuntimeError("boom")

        wrapped = wrap_factory_node(
            node_id="requirement_capture",
            runner=runner,
            render_spec=get_factory_node_render_spec("requirement_capture"),
        )

        with patch_stream_writer(events.append):
            with self.assertRaises(RuntimeError):
                wrapped({"status": "running"})

        self.assertEqual([event["payload"]["event_type"] for event in events], ["node_started", "node_failed"])
        self.assertEqual(events[-1]["payload"]["severity"], "error")
        self.assertIn("boom", events[-1]["payload"]["payload"]["error_summary"])


class FactoryGraphRenderRegistrationTest(unittest.TestCase):
    def test_build_factory_graph_wraps_all_stage_nodes(self) -> None:
        wrapped_nodes = []

        def fake_wrap_factory_node(*, node_id, runner, render_spec):
            wrapped_nodes.append((node_id, runner, render_spec.node_id))
            return runner

        with patch("agent_factory.factory_graph.graph.wrap_factory_node", side_effect=fake_wrap_factory_node):
            build_factory_graph()

        self.assertEqual([item[0] for item in wrapped_nodes], list(STAGE_IDS))
        self.assertEqual([item[2] for item in wrapped_nodes], list(STAGE_IDS))


def patch_stream_writer(writer):
    return patch("agent_factory.factory_graph.render_wrapper.get_stream_writer", return_value=writer)


if __name__ == "__main__":
    unittest.main()
