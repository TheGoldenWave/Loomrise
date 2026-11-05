"""模型身份来自实际执行的 Adapter 模型，不从配置版本推断。"""
import unittest

from agentscope.event import ModelCallEndEvent
from agentscope.message import Msg, TextBlock

from loomrise.adapters.agentscope_runtime import (
    ScriptedChatModel,
    build_agent,
    build_toolkit,
    drive_reply,
    project_event,
)


class ModelEventProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_records_actual_model_identity_and_preserves_usage(self):
        for model_name in ("scripted-s1", "fictional-provider/custom-model-v2"):
            with self.subTest(model=model_name):
                model = ScriptedChatModel(model_name, script=[{"text": "虚构测试答复"}])
                agent = build_agent(
                    name="projection-test", system_prompt="仅用于虚构测试。", model=model,
                    toolkit=await build_toolkit([]), middlewares=[],
                )
                emitted = []

                def emit(event_type, **payload):
                    emitted.append((event_type, payload))

                upstream = [
                    event async for event_type, event in drive_reply(
                        agent, emit,
                        first_input=Msg(name="user", role="user", content=[TextBlock(text="你好")]),
                        ask_confirm=lambda calls: [],
                    ) if event_type == "model.call_end"
                ]
                projected = [payload for event_type, payload in emitted if event_type == "model.call_end"]
                self.assertEqual(len(upstream), 1)
                self.assertEqual(len(projected), 1)
                self.assertEqual(projected[0]["model"], model_name)
                self.assertEqual(projected[0]["input_tokens"], upstream[0].input_tokens)
                self.assertEqual(projected[0]["output_tokens"], upstream[0].output_tokens)
                self.assertEqual(projected[0]["output_tokens"], 64)
                self.assertEqual(projected[0]["finished_reason"], str(upstream[0].finished_reason))

    async def test_direct_projection_without_model_context_remains_compatible(self):
        event = ModelCallEndEvent(reply_id="reply-test", input_tokens=9, output_tokens=4)
        emitted = []

        def emit(event_type, **payload):
            emitted.append((event_type, payload))

        self.assertEqual(project_event(event, emit), "model.call_end")
        self.assertEqual(emitted, [("model.call_end", {
            "model": None, "input_tokens": 9, "output_tokens": 4,
            "finished_reason": str(event.finished_reason),
        })])


if __name__ == "__main__":
    unittest.main()
