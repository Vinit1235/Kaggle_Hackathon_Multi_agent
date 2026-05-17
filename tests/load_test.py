"""
load_test.py: Locust load testing script for the AI Agency Platform backend.
Simulates concurrent users submitting workflows and polling status.
"""

from locust import HttpUser, task, between
import json

class AgencyPlatformUser(HttpUser):
    wait_time = between(1, 5)

    @task(3)
    def check_health(self):
        self.client.get("/health")

    @task(1)
    def submit_workflow(self):
        payload = {
            "domain": "youtube_creator",
            "user_goal": "Create a short video script about AI",
            "user_preferences": {"tone": "informative", "length": "short"}
        }
        with self.client.post("/api/run", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                session_id = data.get("session_id")
                if session_id:
                    # Poll for status a few times
                    self.client.get(f"/api/session/{session_id}")
            else:
                response.failure(f"Failed to submit workflow: {response.text}")
