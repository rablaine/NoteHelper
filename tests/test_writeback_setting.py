"""Tests for MSX auto-writeback setting."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestAutoWritebackSetting:
    """Tests for the msx_auto_writeback preference."""

    def test_default_is_disabled(self, app):
        """Auto-writeback should default to False."""
        with app.app_context():
            from app.models import UserPreference
            pref = UserPreference.query.first()
            assert pref.msx_auto_writeback is False

    def test_toggle_on(self, client, app):
        """Should be able to enable auto-writeback via API."""
        resp = client.post('/api/preferences/msx-auto-writeback',
                           json={'msx_auto_writeback': True},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['msx_auto_writeback'] is True

        with app.app_context():
            from app.models import UserPreference
            pref = UserPreference.query.first()
            assert pref.msx_auto_writeback is True

    def test_toggle_off(self, client, app):
        """Should be able to disable auto-writeback via API."""
        with app.app_context():
            from app.models import UserPreference, db
            pref = UserPreference.query.first()
            pref.msx_auto_writeback = True
            db.session.commit()

        resp = client.post('/api/preferences/msx-auto-writeback',
                           json={'msx_auto_writeback': False},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['msx_auto_writeback'] is False

    def test_settings_page_shows_toggle(self, client):
        """Settings page should show the MSX auto-writeback toggle."""
        resp = client.get('/preferences')
        assert resp.status_code == 200
        assert b'msxAutoWritebackSwitch' in resp.data
        assert b'MSX Auto-Writeback' in resp.data


class TestIsAutoWritebackEnabled:
    """Tests for the is_auto_writeback_enabled() helper."""

    def test_disabled_by_default(self, app, monkeypatch):
        """Should return False when preference is default (False)."""
        monkeypatch.delenv('MSX_WRITEBACK_DISABLED', raising=False)
        with app.app_context():
            from app.services.milestone_tracking import is_auto_writeback_enabled
            assert is_auto_writeback_enabled() is False

    def test_enabled_when_pref_is_true(self, app, monkeypatch):
        """Should return True when preference is enabled."""
        monkeypatch.delenv('MSX_WRITEBACK_DISABLED', raising=False)
        with app.app_context():
            from app.models import UserPreference, db
            from app.services.milestone_tracking import is_auto_writeback_enabled
            pref = UserPreference.query.first()
            pref.msx_auto_writeback = True
            db.session.commit()
            assert is_auto_writeback_enabled() is True

    def test_env_var_overrides_pref(self, app):
        """Env var MSX_WRITEBACK_DISABLED should override the DB setting."""
        with app.app_context():
            from app.models import UserPreference, db
            from app.services.milestone_tracking import is_auto_writeback_enabled
            pref = UserPreference.query.first()
            pref.msx_auto_writeback = True
            db.session.commit()

            os.environ['MSX_WRITEBACK_DISABLED'] = 'true'
            try:
                assert is_auto_writeback_enabled() is False
            finally:
                os.environ.pop('MSX_WRITEBACK_DISABLED', None)


class TestNoteWorkerGating:
    """Tests that note tracking worker respects the writeback setting."""

    @patch('app.services.milestone_tracking._upsert_to_msx')
    @patch('app.services.milestone_tracking._ai_summarize_note')
    @patch('app.services.msx_api.get_milestone_comments')
    def test_note_worker_skips_when_disabled(self, mock_comments, mock_ai,
                                              mock_upsert, app):
        """Worker should skip entirely when auto-writeback is disabled."""
        with app.app_context():
            from app.services.milestone_tracking import _track_note_worker
            _track_note_worker(
                milestones_data=[{"msx_milestone_id": "test-ms", "milestone_id": 1}],
                plain="test note",
                customer_name="Test Corp",
                topics="Azure",
                ref_tag="note-99",
                call_date_iso="2026-03-25T00:00:00.000Z",
                note_id=99,
                app=app,
            )
        mock_comments.assert_not_called()
        mock_ai.assert_not_called()
        mock_upsert.assert_not_called()

    @patch('app.services.milestone_tracking._upsert_to_msx')
    @patch('app.services.milestone_tracking._ai_summarize_note')
    @patch('app.services.msx_api.get_milestone_comments')
    def test_note_worker_runs_when_enabled(self, mock_comments, mock_ai,
                                            mock_upsert, app, monkeypatch):
        """Worker should proceed when auto-writeback is enabled."""
        monkeypatch.delenv('MSX_WRITEBACK_DISABLED', raising=False)
        mock_comments.return_value = {"success": True, "comments": []}
        mock_ai.return_value = "AI summary text"
        mock_upsert.return_value = {"success": True}

        with app.app_context():
            from app.models import UserPreference, db
            pref = UserPreference.query.first()
            pref.msx_auto_writeback = True
            db.session.commit()

            from app.services.milestone_tracking import _track_note_worker
            _track_note_worker(
                milestones_data=[{"msx_milestone_id": "test-ms", "milestone_id": 1}],
                plain="test note",
                customer_name="Test Corp",
                topics="Azure",
                ref_tag="note-99",
                call_date_iso="2026-03-25T00:00:00.000Z",
                note_id=99,
                app=app,
            )
        mock_comments.assert_called_once()
        mock_ai.assert_called_once()


class TestEngagementWorkerGating:
    """Tests that engagement tracking worker respects the writeback setting."""

    @patch('app.services.milestone_tracking._upsert_to_msx')
    @patch('app.services.msx_api.get_milestone_comments')
    @patch('app.services.msx_api.get_msx_user_display_name')
    def test_engagement_worker_skips_when_disabled(self, mock_display,
                                                    mock_comments,
                                                    mock_upsert, app):
        """Worker should skip entirely when auto-writeback is disabled."""
        with app.app_context():
            from app.services.milestone_tracking import _track_engagement_worker
            _track_engagement_worker(
                milestones_data=[{"msx_milestone_id": "test-ms", "milestone_id": 1}],
                content="<table>engagement</table>",
                ref_tag="eng-99",
                app=app,
            )
        mock_display.assert_not_called()
        mock_comments.assert_not_called()
        mock_upsert.assert_not_called()

    @patch('app.services.milestone_tracking._upsert_to_msx')
    @patch('app.services.msx_api.get_milestone_comments')
    @patch('app.services.msx_api.get_msx_user_display_name')
    def test_engagement_worker_runs_when_enabled(self, mock_display,
                                                  mock_comments,
                                                  mock_upsert, app,
                                                  monkeypatch):
        """Worker should proceed when auto-writeback is enabled."""
        monkeypatch.delenv('MSX_WRITEBACK_DISABLED', raising=False)
        mock_display.return_value = "Test User"
        mock_comments.return_value = {"success": True, "comments": []}
        mock_upsert.return_value = {"success": True}

        with app.app_context():
            from app.models import UserPreference, db
            pref = UserPreference.query.first()
            pref.msx_auto_writeback = True
            db.session.commit()

            from app.services.milestone_tracking import _track_engagement_worker
            _track_engagement_worker(
                milestones_data=[{"msx_milestone_id": "test-ms", "milestone_id": 1}],
                content="<table>engagement</table>",
                ref_tag="eng-99",
                app=app,
            )
        mock_display.assert_called_once()
        mock_comments.assert_called_once()
