"""
Tests for restocking-orders API endpoints.
"""
import re
from datetime import datetime

import pytest


VALID_ORDER_NUMBER = re.compile(r"^RSK-\d{4}-\d{4}$")


@pytest.fixture
def sample_restocking_payload():
    """Sample restocking order request body."""
    return {
        "budget": 5000,
        "items": [
            {"sku": "PCB-001", "name": "Single Layer PCB Assembly", "quantity": 100, "unit_cost": 24.99},
            {"sku": "TMP-201", "name": "Temperature Sensor Module", "quantity": 50, "unit_cost": 89.5}
        ]
    }


class TestRestockingOrdersEndpoints:
    """Test suite for restocking-orders endpoints."""

    def test_get_restocking_orders_returns_list(self, client):
        """Test that GET returns a list (may be empty or contain orders from other tests)."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

    def test_create_restocking_order_success(self, client, sample_restocking_payload):
        """Test submitting a valid restocking order."""
        response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        assert response.status_code == 201

        order = response.json()
        assert "id" in order
        assert VALID_ORDER_NUMBER.match(order["order_number"])
        assert order["status"] == "Submitted"
        assert order["budget"] == 5000

        expected_total = sum(item["quantity"] * item["unit_cost"] for item in sample_restocking_payload["items"])
        assert abs(order["total_cost"] - expected_total) < 0.01

    def test_create_restocking_order_appears_in_get_list(self, client, sample_restocking_payload):
        """Test that a submitted order is retrievable via GET afterwards."""
        create_response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        created_order = create_response.json()

        list_response = client.get("/api/restocking-orders")
        all_orders = list_response.json()

        order_ids = [o["id"] for o in all_orders]
        assert created_order["id"] in order_ids

    def test_restocking_order_lead_time_in_range(self, client, sample_restocking_payload):
        """Test that lead_time_days is randomized within the documented 7-14 day range."""
        response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        order = response.json()

        assert isinstance(order["lead_time_days"], int)
        assert 7 <= order["lead_time_days"] <= 14

    def test_restocking_order_expected_delivery_matches_lead_time(self, client, sample_restocking_payload):
        """Test that expected_delivery is created_date offset by lead_time_days."""
        response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        order = response.json()

        created = datetime.fromisoformat(order["created_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])

        assert (expected_delivery - created).days == order["lead_time_days"]

    def test_restocking_order_fields_present(self, client, sample_restocking_payload):
        """Test that all required fields are present on a created order."""
        response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        order = response.json()

        required_fields = [
            "id", "order_number", "items", "budget", "total_cost",
            "status", "created_date", "lead_time_days", "expected_delivery"
        ]
        for field in required_fields:
            assert field in order

    def test_restocking_order_item_structure(self, client, sample_restocking_payload):
        """Test that each item in a created order has the expected structure and types."""
        response = client.post("/api/restocking-orders", json=sample_restocking_payload)
        order = response.json()

        assert len(order["items"]) == len(sample_restocking_payload["items"])
        for item in order["items"]:
            assert "sku" in item
            assert "name" in item
            assert "quantity" in item
            assert "unit_cost" in item
            assert isinstance(item["quantity"], int)
            assert isinstance(item["unit_cost"], (int, float))

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is still accepted, with zero total cost.

        The backend intentionally doesn't reject empty orders - preventing an
        empty submission is a UI-level guard (disable "Place Order"), not an API rule.
        """
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 201

        order = response.json()
        assert order["items"] == []
        assert order["total_cost"] == 0

    def test_create_restocking_order_missing_budget_returns_422(self, client):
        """Test that omitting a required field fails Pydantic validation."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 422

    def test_create_restocking_order_missing_item_field_returns_422(self, client):
        """Test that an item missing a required field fails validation."""
        payload = {
            "budget": 1000,
            "items": [{"sku": "PCB-001", "name": "Single Layer PCB Assembly", "quantity": 10}]
        }
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 422

    def test_create_restocking_order_negative_quantity_returns_422(self, client):
        """Test that a negative or zero item quantity fails validation."""
        payload = {
            "budget": 1000,
            "items": [{"sku": "PCB-001", "name": "Single Layer PCB Assembly", "quantity": -5, "unit_cost": 24.99}]
        }
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 422

    def test_create_restocking_order_negative_budget_returns_422(self, client):
        """Test that a negative budget fails validation."""
        response = client.post("/api/restocking-orders", json={"budget": -100, "items": []})
        assert response.status_code == 422

    def test_restocking_order_numbers_increment(self, client, sample_restocking_payload):
        """Test that sequential order numbers increase by 1."""
        first = client.post("/api/restocking-orders", json=sample_restocking_payload).json()
        second = client.post("/api/restocking-orders", json=sample_restocking_payload).json()

        first_seq = int(first["order_number"].split("-")[-1])
        second_seq = int(second["order_number"].split("-")[-1])
        assert second_seq == first_seq + 1
