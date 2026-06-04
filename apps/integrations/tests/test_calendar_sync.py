"""RV07 (Epic 7) — Sync bidirecional de agenda com o Google.

Leitura (Google → Calendário) e escrita (OS → Google), tudo com httpx/provider
mockado. Nenhum teste toca a rede.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.integrations import services
from apps.integrations.models import IntegrationConnection
from apps.integrations.providers.base import ProviderResult
from apps.integrations.providers.google import GoogleCalendarProvider
from apps.operations.models import WorkOrder
from apps.operations.views import _google_event_days


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _connected_conn(empresa):
    conn = IntegrationConnection.objects.create(
        empresa=empresa,
        provider=IntegrationConnection.Provider.GOOGLE,
        status=IntegrationConnection.Status.CONNECTED,
        scopes=["calendar"],
    )
    conn.set_access_token("at")
    conn.set_refresh_token("rt")
    conn.expires_at = timezone.now() + timedelta(hours=1)
    conn.save()
    return conn


class ProviderListUpdateTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="cal-prov")
        self.conn = _connected_conn(self.empresa)

    @patch("httpx.request")
    def test_list_events_parses_items(self, mock_req):
        mock_req.return_value = FakeResp(200, {"items": [
            {"id": "a", "summary": "Reunião", "htmlLink": "http://a",
             "start": {"dateTime": "2026-06-10T10:00:00-03:00"},
             "end": {"dateTime": "2026-06-10T11:00:00-03:00"}},
            {"id": "b", "summary": "Feriado",
             "start": {"date": "2026-06-12"}, "end": {"date": "2026-06-13"}},
        ]})
        res = GoogleCalendarProvider(self.conn).list_events(
            time_min=timezone.now(), time_max=timezone.now(),
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(res["items"]), 2)
        self.assertFalse(res["items"][0]["all_day"])
        self.assertTrue(res["items"][1]["all_day"])

    @patch("httpx.request")
    def test_update_event_ok(self, mock_req):
        mock_req.return_value = FakeResp(200, {"id": "e1", "htmlLink": "http://e"})
        res = GoogleCalendarProvider(self.conn).update_event(
            "e1", title="x", start=date(2026, 6, 1), end=date(2026, 6, 2),
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(mock_req.call_args[0][0], "PATCH")

    @patch("httpx.request")
    def test_update_event_404_signals_not_found(self, mock_req):
        mock_req.return_value = FakeResp(404, text="gone")
        res = GoogleCalendarProvider(self.conn).update_event(
            "missing", title="x", start=date(2026, 6, 1), end=date(2026, 6, 2),
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["detail"], "not_found")


class ListCalendarEventsServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="cal-list")
        cache.clear()

    def test_no_connection_returns_empty(self):
        self.assertEqual(
            services.list_calendar_events(
                self.empresa, time_min=timezone.now(), time_max=timezone.now(),
            ),
            [],
        )

    def test_connected_returns_items_and_caches(self):
        _connected_conn(self.empresa)
        items = [{"id": "x", "title": "Ev", "start": "2026-06-10",
                  "end": "2026-06-11", "all_day": True, "html_link": ""}]
        with patch.object(
            GoogleCalendarProvider, "list_events",
            return_value=ProviderResult(status="ok", items=items),
        ) as mock_list:
            tmin = timezone.now()
            tmax = tmin + timedelta(days=30)
            first = services.list_calendar_events(self.empresa, time_min=tmin, time_max=tmax)
            second = services.list_calendar_events(self.empresa, time_min=tmin, time_max=tmax)
        self.assertEqual(first, items)
        self.assertEqual(second, items)
        mock_list.assert_called_once()  # 2ª veio do cache


class SyncWorkOrderToCalendarTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="cal-sync")

    def test_no_connection_is_noop(self):
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", scheduled_date=date(2026, 6, 10),
        )
        res = services.sync_work_order_to_calendar(wo)
        self.assertEqual(res.get("status"), "not_configured")

    def test_creates_event_and_stores_id(self):
        _connected_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS Nova", scheduled_date=date(2026, 6, 10),
        )
        with patch.object(
            GoogleCalendarProvider, "create_event",
            return_value=ProviderResult(status="ok", integration_ready=True, event_id="evt-new"),
        ) as mock_create:
            services.sync_work_order_to_calendar(wo)
        mock_create.assert_called_once()
        # fim all-day exclusivo: 1 dia => end = start + 1
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["end"], date(2026, 6, 11))
        wo.refresh_from_db()
        self.assertEqual(wo.google_event_id, "evt-new")

    def test_existing_id_updates(self):
        _connected_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", scheduled_date=date(2026, 6, 10),
            google_event_id="evt-1",
        )
        with patch.object(
            GoogleCalendarProvider, "update_event",
            return_value=ProviderResult(status="ok", integration_ready=True, event_id="evt-1"),
        ) as mock_upd, patch.object(GoogleCalendarProvider, "create_event") as mock_create:
            services.sync_work_order_to_calendar(wo)
        mock_upd.assert_called_once()
        mock_create.assert_not_called()

    def test_update_not_found_recreates(self):
        _connected_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", scheduled_date=date(2026, 6, 10),
            google_event_id="stale",
        )
        with patch.object(
            GoogleCalendarProvider, "update_event",
            return_value=ProviderResult(status="error", detail="not_found"),
        ), patch.object(
            GoogleCalendarProvider, "create_event",
            return_value=ProviderResult(status="ok", integration_ready=True, event_id="evt-2"),
        ) as mock_create:
            services.sync_work_order_to_calendar(wo)
        mock_create.assert_called_once()
        wo.refresh_from_db()
        self.assertEqual(wo.google_event_id, "evt-2")

    def test_unscheduled_with_event_deletes(self):
        _connected_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", scheduled_date=None,
            google_event_id="evt-old",
        )
        with patch.object(
            GoogleCalendarProvider, "delete_event",
            return_value=ProviderResult(status="ok", integration_ready=True),
        ) as mock_del:
            services.sync_work_order_to_calendar(wo)
        mock_del.assert_called_once_with("evt-old")
        wo.refresh_from_db()
        self.assertEqual(wo.google_event_id, "")


class SignalIntegrationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="cal-signal")

    def test_creating_scheduled_wo_triggers_sync(self):
        _connected_conn(self.empresa)
        with patch.object(
            GoogleCalendarProvider, "create_event",
            return_value=ProviderResult(status="ok", integration_ready=True, event_id="evt-sig"),
        ) as mock_create:
            with self.captureOnCommitCallbacks(execute=True):
                WorkOrder.objects.create(
                    empresa=self.empresa, title="OS Signal",
                    scheduled_date=date(2026, 6, 20),
                )
        mock_create.assert_called_once()

    def test_status_change_without_schedule_change_does_not_sync(self):
        _connected_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", scheduled_date=date(2026, 6, 20),
            google_event_id="evt-x",
        )
        # muda só o status — não deve chamar a API de novo
        with patch.object(GoogleCalendarProvider, "update_event") as mock_upd, \
                patch.object(GoogleCalendarProvider, "create_event") as mock_create:
            with self.captureOnCommitCallbacks(execute=True):
                wo.status = WorkOrder.Status.IN_PROGRESS
                wo.save()
        mock_upd.assert_not_called()
        mock_create.assert_not_called()


class CalendarViewOverlayTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="cal-view")
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)

    def test_calendar_shows_google_events(self):
        _connected_conn(self.empresa)
        event = {"id": "g1", "title": "Reunião Google", "start": "2026-06-15",
                 "end": "2026-06-16", "all_day": True, "html_link": "http://g"}
        with patch("apps.integrations.services.list_calendar_events", return_value=[event]):
            resp = self.client.get(reverse("operations:calendar"), {"year": 2026, "month": 6})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Reunião Google")
        self.assertContains(resp, "Agenda Google")  # legenda

    def test_calendar_without_connection_has_no_overlay(self):
        resp = self.client.get(reverse("operations:calendar"), {"year": 2026, "month": 6})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Agenda Google")

    def test_htmx_partial_includes_nav_and_month_name(self):
        # Correção do bug de navegação: a resposta PARCIAL (HTMX) precisa conter
        # o título do mês e os botões ◀▶ com alvos frescos — antes ficavam fora
        # do #calendar-container e defasavam ("não muda o nome nem o mês").
        resp = self.client.get(
            reverse("operations:calendar"), {"year": 2026, "month": 7},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Julho 2026", html)   # título dentro do parcial
        self.assertIn("month=8", html)       # ▶ aponta p/ agosto (mês seguinte)
        self.assertIn("month=6", html)       # ◀ aponta p/ junho (mês anterior)


class GoogleEventDaysHelperTests(TestCase):
    def test_all_day_multi_day_spread_clamped_to_month(self):
        # evento 28/05 a 02/06 (fim exclusivo 02/06 => último dia 01/06)
        ev = {"start": "2026-05-28", "end": "2026-06-02", "all_day": True}
        self.assertEqual(_google_event_days(ev, 2026, 6), [1])  # só o que cai em junho

    def test_timed_event_single_day(self):
        ev = {"start": "2026-06-15T10:00:00-03:00", "end": "2026-06-15T11:00:00-03:00",
              "all_day": False}
        self.assertEqual(_google_event_days(ev, 2026, 6), [15])

    def test_event_outside_month_returns_empty(self):
        ev = {"start": "2026-07-10", "end": "2026-07-11", "all_day": True}
        self.assertEqual(_google_event_days(ev, 2026, 6), [])
