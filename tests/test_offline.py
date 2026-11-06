import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from integrations.motrack_agent import AgentState, BoundedAgent, validate_event


class OfflineTests(unittest.TestCase):
    def test_event_clamps_and_validates(self):
        event = validate_event({"start": 2, "end": 5, "event_type": "made_up", "highlight_score": 300,
                                "confidence": -1, "evidence_timestamps": [3]}, 10)
        self.assertEqual(event["event_type"], "unknown")
        self.assertEqual(event["highlight_score"], 100)
        self.assertEqual(event["confidence"], 0)

    def test_event_rejects_outside_source(self):
        with self.assertRaises(ValueError):
            validate_event({"start": 2, "end": 11}, 10)

    def test_agent_rejects_arbitrary_tools_and_limits_calls(self):
        state = AgentState(Path.cwd(), Path("input.mp4"), 10, max_calls=1)
        agent = BoundedAgent(state, {"probe_video": lambda: {"duration": 10}})
        self.assertEqual(agent.call("probe_video", {})["duration"], 10)
        with self.assertRaises(RuntimeError): agent.call("probe_video", {})
        with self.assertRaises(ValueError): BoundedAgent(state, {}).call("shell", {})


if __name__ == "__main__":
    unittest.main()
