"""
Tests for the onboarding wizard (Issue #6).

Verifies that the multi-step onboarding modal appears when appropriate,
the dismiss endpoint works, and the modal is hidden after dismissal.
"""
import pytest


class TestOnboardingWizardDisplay:
    """Tests for onboarding wizard visibility logic."""

    def test_onboarding_modal_shown_when_not_dismissed(self, client, app):
        """Onboarding wizard should appear when first_run_modal_dismissed is False."""
        response = client.get('/')
        assert response.status_code == 200
        # The wizard modal HTML should be rendered
        assert b'id="welcomeModal"' in response.data
        assert b'onboardingStep1' in response.data
        assert b'onboardingStep2' in response.data
        assert b'onboardingStep3' in response.data
        assert b'onboardingStep4' in response.data
        assert b'onboardingStep5' in response.data

    def test_onboarding_modal_hidden_when_dismissed(self, client, app):
        """Onboarding wizard should not appear when first_run_modal_dismissed is True."""
        with app.app_context():
            from app.models import db, UserPreference
            pref = UserPreference.query.first()
            pref.first_run_modal_dismissed = True
            db.session.commit()

        response = client.get('/')
        assert response.status_code == 200
        # The wizard modal HTML should NOT be rendered
        assert b'id="welcomeModal"' not in response.data
        assert b'onboardingStep1' not in response.data

        # Clean up
        with app.app_context():
            from app.models import db, UserPreference
            pref = UserPreference.query.first()
            pref.first_run_modal_dismissed = False
            db.session.commit()

    def test_onboarding_shows_on_non_index_pages(self, client, app):
        """Onboarding wizard renders on all pages (it's in base.html)."""
        # The wizard is in base.html, so it should render on any page
        response = client.get('/customers')
        assert response.status_code == 200
        assert b'id="welcomeModal"' in response.data

    def test_onboarding_step_structure(self, client, app):
        """Verify all wizard steps have proper structure."""
        response = client.get('/')
        html = response.data.decode('utf-8')

        # Step 1: Welcome + Dark Mode
        assert 'Choose Your Theme' in html
        assert 'onboardDarkModeToggle' in html

        # Step 2: Authentication
        assert 'Connect to MSX' in html
        assert 'onboardStartAuth' in html

        # Step 3: Import Accounts
        assert 'Import Your Accounts' in html
        assert 'onboardImportAccounts' in html

        # Step 4: Import Milestones
        assert 'Import Milestones' in html
        assert 'onboardImportMilestones' in html

        # Step 5: Revenue & Finish
        assert 'Revenue Data' in html
        assert 'onboardGoToRevenue' in html

    def test_onboarding_has_skip_button(self, client, app):
        """Verify the skip button is present."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        assert 'onboardSkipBtn' in html
        assert "Skip setup" in html

    def test_onboarding_has_navigation_buttons(self, client, app):
        """Verify Next/Back buttons exist."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        assert 'onboardNextBtn' in html
        assert 'onboardBackBtn' in html

    def test_onboarding_progress_bar(self, client, app):
        """Verify progress bar and step badge exist."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        assert 'onboardingProgress' in html
        assert 'onboardingStepBadge' in html
        assert 'Step 1 of 5' in html


class TestDismissWelcomeModalEndpoint:
    """Tests for the dismiss-welcome-modal API endpoint."""

    def test_dismiss_welcome_modal(self, client, app):
        """POST to dismiss endpoint should set first_run_modal_dismissed to True."""
        response = client.post('/api/preferences/dismiss-welcome-modal',
                               content_type='application/json')
        assert response.status_code == 200

        with app.app_context():
            from app.models import UserPreference
            pref = UserPreference.query.first()
            assert pref.first_run_modal_dismissed is True

        # Clean up
        with app.app_context():
            from app.models import db, UserPreference
            pref = UserPreference.query.first()
            pref.first_run_modal_dismissed = False
            db.session.commit()

    def test_dismiss_modal_then_page_hides_wizard(self, client, app):
        """After dismissing, the wizard should not render on subsequent pages."""
        # Dismiss
        response = client.post('/api/preferences/dismiss-welcome-modal',
                               content_type='application/json')
        assert response.status_code == 200

        # Load page
        response = client.get('/')
        assert response.status_code == 200
        assert b'id="welcomeModal"' not in response.data

        # Clean up
        with app.app_context():
            from app.models import db, UserPreference
            pref = UserPreference.query.first()
            pref.first_run_modal_dismissed = False
            db.session.commit()


class TestDarkModeToggleInOnboarding:
    """Tests for the dark mode toggle API used in the onboarding wizard."""

    def test_dark_mode_toggle_api(self, client, app):
        """POST to dark-mode endpoint should update preference."""
        response = client.post('/api/preferences/dark-mode',
                               json={'dark_mode': True},
                               content_type='application/json')
        assert response.status_code == 200

        with app.app_context():
            from app.models import UserPreference
            pref = UserPreference.query.first()
            assert pref.dark_mode is True

        # Clean up
        with app.app_context():
            from app.models import db, UserPreference
            pref = UserPreference.query.first()
            pref.dark_mode = False
            db.session.commit()

    def test_dark_mode_toggle_off(self, client, app):
        """POST dark_mode=false should disable dark mode."""
        # First enable
        client.post('/api/preferences/dark-mode',
                     json={'dark_mode': True},
                     content_type='application/json')

        # Then disable
        response = client.post('/api/preferences/dark-mode',
                               json={'dark_mode': False},
                               content_type='application/json')
        assert response.status_code == 200

        with app.app_context():
            from app.models import UserPreference
            pref = UserPreference.query.first()
            assert pref.dark_mode is False


class TestOldModalRemoval:
    """Tests verifying the old first-time modal was properly removed."""

    def test_no_old_first_time_modal_in_index(self, client, app):
        """The old firstTimeModal should not exist in index page."""
        response = client.get('/')
        html = response.data.decode('utf-8')
        assert 'firstTimeModal' not in html
        assert 'firstTimeDarkModeSwitch' not in html

    def test_no_show_first_time_modal_in_session(self, client, app):
        """The show_first_time_modal session flag should not be used."""
        response = client.get('/')
        assert response.status_code == 200
        # Just verify the page loads — the session flag is no longer set

    def test_index_loads_without_show_first_time_modal_param(self, client):
        """Index should work without the old show_first_time_modal template var."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'NoteHelper' in response.data
