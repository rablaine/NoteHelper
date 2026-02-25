"""
Tests for the Milestone Tracker feature.

Tests the sync service, tracker routes, model additions, and template rendering.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestMilestoneModel:
    """Test the new Milestone model properties."""
    
    def test_is_active_on_track(self, app, sample_data):
        """Milestones with 'On Track' status should be active."""
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms1',
                msx_status='On Track',
                user_id=user.id,
            )
            assert ms.is_active is True
    
    def test_is_active_at_risk(self, app, sample_data):
        """Milestones with 'At Risk' status should be active."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms2',
                msx_status='At Risk',
                user_id=user.id,
            )
            assert ms.is_active is True
    
    def test_is_active_blocked(self, app, sample_data):
        """Milestones with 'Blocked' status should be active."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms3',
                msx_status='Blocked',
                user_id=user.id,
            )
            assert ms.is_active is True
    
    def test_is_not_active_completed(self, app, sample_data):
        """Milestones with 'Completed' status should not be active."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms4',
                msx_status='Completed',
                user_id=user.id,
            )
            assert ms.is_active is False
    
    def test_is_not_active_cancelled(self, app, sample_data):
        """Milestones with 'Cancelled' status should not be active."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms5',
                msx_status='Cancelled',
                user_id=user.id,
            )
            assert ms.is_active is False
    
    def test_due_date_urgency_past_due(self, app, sample_data):
        """Milestones with past due date should show 'past_due'."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms6',
                due_date=datetime.utcnow() - timedelta(days=5),
                user_id=user.id,
            )
            assert ms.due_date_urgency == 'past_due'
    
    def test_due_date_urgency_this_week(self, app, sample_data):
        """Milestones due within 7 days should show 'this_week'."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms7',
                due_date=datetime.utcnow() + timedelta(days=3),
                user_id=user.id,
            )
            assert ms.due_date_urgency == 'this_week'
    
    def test_due_date_urgency_this_month(self, app, sample_data):
        """Milestones due within 30 days should show 'this_month'."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms8',
                due_date=datetime.utcnow() + timedelta(days=20),
                user_id=user.id,
            )
            assert ms.due_date_urgency == 'this_month'
    
    def test_due_date_urgency_future(self, app, sample_data):
        """Milestones due beyond 30 days should show 'future'."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms9',
                due_date=datetime.utcnow() + timedelta(days=60),
                user_id=user.id,
            )
            assert ms.due_date_urgency == 'future'
    
    def test_due_date_urgency_no_date(self, app, sample_data):
        """Milestones without due date should show 'no_date'."""
        with app.app_context():
            from app.models import Milestone, User
            user = User.query.first()
            ms = Milestone(
                url='https://example.com/ms10',
                due_date=None,
                user_id=user.id,
            )
            assert ms.due_date_urgency == 'no_date'
    
    def test_new_fields_persist(self, app, sample_data):
        """New tracker fields (due_date, dollar_value, etc.) should save and load."""
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            
            due = datetime(2026, 6, 30)
            ms = Milestone(
                url='https://example.com/persist-test',
                msx_milestone_id='test-guid-persist',
                title='Persist Test',
                msx_status='On Track',
                due_date=due,
                dollar_value=50000.0,
                workload='Azure Data',
                monthly_usage=1234.56,
                last_synced_at=datetime.utcnow(),
                user_id=user.id,
                customer_id=sample_data['customer1_id'],
            )
            db.session.add(ms)
            db.session.commit()
            
            loaded = Milestone.query.filter_by(msx_milestone_id='test-guid-persist').first()
            assert loaded is not None
            assert loaded.due_date == due
            assert loaded.dollar_value == 50000.0
            assert loaded.workload == 'Azure Data'
            assert loaded.monthly_usage == 1234.56
            assert loaded.last_synced_at is not None
            
            # Cleanup
            db.session.delete(loaded)
            db.session.commit()


class TestMilestoneSyncService:
    """Test the milestone sync service."""
    
    def _create_test_customer_with_tpid_url(self, app, sample_data):
        """Helper to ensure we have a customer with a proper MSX tpid_url."""
        with app.app_context():
            from app.models import db, Customer
            customer = Customer.query.get(sample_data['customer1_id'])
            # Set a proper MSX URL with a GUID
            customer.tpid_url = (
                'https://microsoftsales.crm.dynamics.com/main.aspx'
                '?appid=fe0c3504&pagetype=entityrecord&etn=account'
                '&id=aaaabbbb-1111-2222-3333-444455556666'
            )
            db.session.commit()
            return customer.id
    
    @patch('app.services.milestone_sync.get_milestones_by_account')
    def test_sync_customer_milestones_creates_new(self, mock_get, app, sample_data):
        """Sync should create new milestones from MSX data."""
        customer_id = self._create_test_customer_with_tpid_url(app, sample_data)
        
        mock_get.return_value = {
            "success": True,
            "milestones": [
                {
                    "id": "ms-guid-111",
                    "name": "Deploy Azure SQL",
                    "number": "7-100001",
                    "status": "On Track",
                    "status_code": 861980000,
                    "status_sort": 1,
                    "opportunity_name": "Acme Cloud Migration",
                    "workload": "Azure SQL",
                    "monthly_usage": 5000.0,
                    "due_date": "2026-03-15T00:00:00Z",
                    "dollar_value": 120000.0,
                    "url": "https://microsoftsales.crm.dynamics.com/main.aspx?id=ms-guid-111",
                },
            ],
            "count": 1,
        }
        
        with app.app_context():
            from app.models import db, Customer, Milestone, User
            from app.services.milestone_sync import sync_customer_milestones
            
            customer = Customer.query.get(customer_id)
            user = User.query.first()
            
            result = sync_customer_milestones(customer, user.id)
            
            assert result["success"] is True
            assert result["created"] == 1
            assert result["updated"] == 0
            
            # Verify sync passes open_opportunities_only and current_fy_only
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            assert call_kwargs == (
                (mock_get.call_args[0][0],),  # account_id positional arg
                {'open_opportunities_only': True, 'current_fy_only': True},
            )
            
            # Verify milestone was created
            ms = Milestone.query.filter_by(msx_milestone_id="ms-guid-111").first()
            assert ms is not None
            assert ms.title == "Deploy Azure SQL"
            assert ms.dollar_value == 120000.0
            assert ms.due_date is not None
            assert ms.customer_id == customer_id
            assert ms.workload == "Azure SQL"
            
            # Cleanup
            db.session.delete(ms)
            db.session.commit()
    
    @patch('app.services.milestone_sync.get_milestones_by_account')
    def test_sync_customer_milestones_updates_existing(self, mock_get, app, sample_data):
        """Sync should update existing milestones with fresh MSX data."""
        customer_id = self._create_test_customer_with_tpid_url(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            
            # Create an existing milestone
            existing = Milestone(
                msx_milestone_id="ms-guid-update",
                url="https://old-url.com",
                title="Old Title",
                msx_status="On Track",
                dollar_value=50000.0,
                customer_id=customer_id,
                user_id=user.id,
            )
            db.session.add(existing)
            db.session.commit()
            existing_id = existing.id
        
        mock_get.return_value = {
            "success": True,
            "milestones": [
                {
                    "id": "ms-guid-update",
                    "name": "Updated Title",
                    "number": "7-200002",
                    "status": "At Risk",
                    "status_code": 861980001,
                    "status_sort": 2,
                    "opportunity_name": "Updated Opp",
                    "workload": "Azure AI",
                    "monthly_usage": 8000.0,
                    "due_date": "2026-04-30T00:00:00Z",
                    "dollar_value": 200000.0,
                    "url": "https://new-url.com",
                },
            ],
            "count": 1,
        }
        
        with app.app_context():
            from app.models import db, Customer, Milestone, User
            from app.services.milestone_sync import sync_customer_milestones
            
            customer = Customer.query.get(customer_id)
            user = User.query.first()
            
            result = sync_customer_milestones(customer, user.id)
            
            assert result["success"] is True
            assert result["created"] == 0
            assert result["updated"] == 1
            
            ms = Milestone.query.get(existing_id)
            assert ms.title == "Updated Title"
            assert ms.msx_status == "At Risk"
            assert ms.dollar_value == 200000.0
            assert ms.workload == "Azure AI"
            assert ms.last_synced_at is not None
            
            # Cleanup
            db.session.delete(ms)
            db.session.commit()
    
    @patch('app.services.milestone_sync.get_milestones_by_account')
    def test_sync_deactivates_missing_milestones(self, mock_get, app, sample_data):
        """Milestones no longer in MSX should be marked as completed."""
        customer_id = self._create_test_customer_with_tpid_url(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            
            # Create a milestone that won't be returned by MSX
            disappearing = Milestone(
                msx_milestone_id="ms-guid-gone",
                url="https://gone.com",
                title="Gone Milestone",
                msx_status="On Track",
                customer_id=customer_id,
                user_id=user.id,
            )
            db.session.add(disappearing)
            db.session.commit()
            disappearing_id = disappearing.id
        
        # MSX returns empty list — our milestone is gone
        mock_get.return_value = {
            "success": True,
            "milestones": [],
            "count": 0,
        }
        
        with app.app_context():
            from app.models import db, Customer, Milestone, User
            from app.services.milestone_sync import sync_customer_milestones
            
            customer = Customer.query.get(customer_id)
            user = User.query.first()
            
            result = sync_customer_milestones(customer, user.id)
            
            assert result["success"] is True
            assert result["deactivated"] == 1
            
            ms = Milestone.query.get(disappearing_id)
            assert ms.msx_status == "Completed"
            
            # Cleanup
            db.session.delete(ms)
            db.session.commit()
    
    @patch('app.services.milestone_sync.get_milestones_by_account')
    def test_sync_handles_msx_error(self, mock_get, app, sample_data):
        """Sync should handle MSX API errors gracefully."""
        customer_id = self._create_test_customer_with_tpid_url(app, sample_data)
        
        mock_get.return_value = {
            "success": False,
            "error": "Not authenticated. Run 'az login' first.",
        }
        
        with app.app_context():
            from app.models import Customer, User
            from app.services.milestone_sync import sync_customer_milestones
            
            customer = Customer.query.get(customer_id)
            user = User.query.first()
            
            result = sync_customer_milestones(customer, user.id)
            
            assert result["success"] is False
            assert "authenticated" in result["error"]
    
    def test_sync_customer_without_tpid_url(self, app, sample_data):
        """Sync should fail for customers without tpid_url."""
        with app.app_context():
            from app.models import Customer, User
            from app.services.milestone_sync import sync_customer_milestones
            
            # customer2 has no tpid_url
            customer = Customer.query.get(sample_data['customer2_id'])
            user = User.query.first()
            
            result = sync_customer_milestones(customer, user.id)
            
            assert result["success"] is False
            assert "account ID" in result["error"]
    
    @patch('app.services.milestone_sync.get_milestones_by_account')
    def test_sync_all_customer_milestones(self, mock_get, app, sample_data):
        """Full sync should process all customers with tpid_url."""
        # Only customer1 has tpid_url in sample_data
        self._create_test_customer_with_tpid_url(app, sample_data)
        
        mock_get.return_value = {
            "success": True,
            "milestones": [
                {
                    "id": "ms-guid-all-sync",
                    "name": "Full Sync Test",
                    "number": "7-300001",
                    "status": "On Track",
                    "status_code": 861980000,
                    "status_sort": 1,
                    "opportunity_name": "Test Opp",
                    "workload": "Azure VM",
                    "monthly_usage": None,
                    "due_date": None,
                    "dollar_value": 75000.0,
                    "url": "https://test.com",
                },
            ],
            "count": 1,
        }
        
        with app.app_context():
            from app.models import db, Milestone, User
            from app.services.milestone_sync import sync_all_customer_milestones
            
            user = User.query.first()
            results = sync_all_customer_milestones(user.id)
            
            assert results["success"] is True
            assert results["customers_synced"] >= 1
            assert results["milestones_created"] >= 1
            assert results["duration_seconds"] >= 0
            
            # Cleanup
            ms = Milestone.query.filter_by(msx_milestone_id="ms-guid-all-sync").first()
            if ms:
                db.session.delete(ms)
                db.session.commit()


class TestMilestoneTrackerData:
    """Test the tracker data retrieval function."""
    
    def _create_tracker_milestones(self, app, sample_data):
        """Create test milestones for tracker data tests."""
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            
            ms1 = Milestone(
                msx_milestone_id="tracker-ms-1",
                url="https://tracker1.com",
                title="High Value Past Due",
                msx_status="On Track",
                dollar_value=500000.0,
                monthly_usage=50000.0,
                due_date=datetime.utcnow() - timedelta(days=10),
                workload="Data: SQL Modernization to Azure SQL DB",
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
                last_synced_at=datetime.utcnow(),
            )
            ms2 = Milestone(
                msx_milestone_id="tracker-ms-2",
                url="https://tracker2.com",
                title="Low Value This Week",
                msx_status="At Risk",
                dollar_value=10000.0,
                monthly_usage=1000.0,
                due_date=datetime.utcnow() + timedelta(days=3),
                workload="Infra: Windows",
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
                last_synced_at=datetime.utcnow(),
            )
            ms3 = Milestone(
                msx_milestone_id="tracker-ms-3",
                url="https://tracker3.com",
                title="No Dollar Value",
                msx_status="Blocked",
                dollar_value=None,
                monthly_usage=None,
                due_date=datetime.utcnow() + timedelta(days=45),
                workload="AI: Foundry Models - OpenAI",
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
            )
            # Completed milestone — should NOT appear in tracker
            ms4 = Milestone(
                msx_milestone_id="tracker-ms-4",
                url="https://tracker4.com",
                title="Completed One",
                msx_status="Completed",
                dollar_value=100000.0,
                monthly_usage=10000.0,
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
            )
            db.session.add_all([ms1, ms2, ms3, ms4])
            db.session.commit()
            return [ms1.id, ms2.id, ms3.id, ms4.id]
    
    def test_tracker_data_excludes_completed(self, app, sample_data):
        """Tracker should only show active milestones."""
        ids = self._create_tracker_milestones(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone
            from app.services.milestone_sync import get_milestone_tracker_data
            
            data = get_milestone_tracker_data()
            
            titles = [m["title"] for m in data["milestones"]]
            assert "Completed One" not in titles
            assert "High Value Past Due" in titles
            assert "Low Value This Week" in titles
            assert "No Dollar Value" in titles
            
            # Cleanup
            for mid in ids:
                ms = Milestone.query.get(mid)
                if ms:
                    db.session.delete(ms)
            db.session.commit()
    
    def test_tracker_data_sorted_by_monthly_usage_desc(self, app, sample_data):
        """Tracker should sort by monthly_usage descending by default."""
        ids = self._create_tracker_milestones(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone
            from app.services.milestone_sync import get_milestone_tracker_data
            
            data = get_milestone_tracker_data()
            milestones = data["milestones"]
            
            # Sorted by monthly_usage desc: 50k, 1k, None(0)
            assert milestones[0]["title"] == "High Value Past Due"
            assert milestones[0]["monthly_usage"] == 50000.0
            assert milestones[1]["title"] == "Low Value This Week"
            assert milestones[1]["monthly_usage"] == 1000.0
            assert milestones[2]["monthly_usage"] is None
            
            # Cleanup
            for mid in ids:
                ms = Milestone.query.get(mid)
                if ms:
                    db.session.delete(ms)
            db.session.commit()
    
    def test_tracker_summary_totals(self, app, sample_data):
        """Summary should have correct counts and totals."""
        ids = self._create_tracker_milestones(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone
            from app.services.milestone_sync import get_milestone_tracker_data
            
            data = get_milestone_tracker_data()
            summary = data["summary"]
            
            assert summary["total_count"] == 3  # 3 active milestones
            assert summary["total_monthly_usage"] == 51000.0  # 50k + 1k
            assert summary["past_due_count"] == 1
            assert summary["this_week_count"] == 1
            
            # Cleanup
            for mid in ids:
                ms = Milestone.query.get(mid)
                if ms:
                    db.session.delete(ms)
            db.session.commit()
    
    def test_tracker_includes_seller_info(self, app, sample_data):
        """Tracker data should include seller info from customer relationship."""
        ids = self._create_tracker_milestones(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone
            from app.services.milestone_sync import get_milestone_tracker_data
            
            data = get_milestone_tracker_data()
            
            # customer1 has seller1 (Alice Smith) in sample_data
            for ms in data["milestones"]:
                assert ms["seller"] is not None
                assert ms["seller"]["name"] == "Alice Smith"
            
            # Cleanup
            for mid in ids:
                ms = Milestone.query.get(mid)
                if ms:
                    db.session.delete(ms)
            db.session.commit()
    
    def test_tracker_extracts_workload_areas(self, app, sample_data):
        """Tracker should extract area prefix from workload strings."""
        ids = self._create_tracker_milestones(app, sample_data)
        
        with app.app_context():
            from app.models import db, Milestone
            from app.services.milestone_sync import get_milestone_tracker_data
            
            data = get_milestone_tracker_data()
            
            # Check workload_area is correctly extracted
            areas_in_data = {ms["workload_area"] for ms in data["milestones"]}
            assert "Data" in areas_in_data
            assert "Infra" in areas_in_data
            assert "AI" in areas_in_data
            
            # Check areas list for dropdown
            assert "Data" in data["areas"]
            assert "Infra" in data["areas"]
            assert "AI" in data["areas"]
            
            # Cleanup
            for mid in ids:
                ms = Milestone.query.get(mid)
                if ms:
                    db.session.delete(ms)
            db.session.commit()


class TestMilestoneTrackerRoutes:
    """Test the milestone tracker route handlers."""
    
    def test_tracker_page_loads(self, client, app, sample_data):
        """Milestone tracker page should load successfully."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'Milestone Tracker' in response.data
    
    def test_tracker_page_shows_empty_state(self, client, app, sample_data):
        """Tracker should show empty state when no milestones."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'No Active Milestones' in response.data or b'Milestone Tracker' in response.data
    
    def test_tracker_page_shows_milestones(self, client, app, sample_data):
        """Tracker should display milestones when they exist."""
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            
            ms = Milestone(
                msx_milestone_id="route-test-ms",
                url="https://route-test.com",
                title="Route Test Milestone",
                msx_status="On Track",
                dollar_value=75000.0,
                monthly_usage=7500.0,
                due_date=datetime.utcnow() + timedelta(days=5),
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
            )
            db.session.add(ms)
            db.session.commit()
        
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'Route Test Milestone' in response.data
        assert b'$7,500' in response.data
        
        with app.app_context():
            from app.models import db, Milestone
            ms = Milestone.query.filter_by(msx_milestone_id="route-test-ms").first()
            if ms:
                db.session.delete(ms)
                db.session.commit()
    
    @patch('app.services.milestone_sync.sync_all_customer_milestones')
    def test_sync_api_endpoint(self, mock_sync, client, app, sample_data):
        """POST /api/milestone-tracker/sync should trigger sync."""
        mock_sync.return_value = {
            "success": True,
            "customers_synced": 5,
            "customers_skipped": 2,
            "customers_failed": 0,
            "milestones_created": 10,
            "milestones_updated": 3,
            "milestones_deactivated": 1,
            "errors": [],
            "duration_seconds": 4.2,
        }
        
        response = client.post('/api/milestone-tracker/sync')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data["success"] is True
        assert data["customers_synced"] == 5
        assert data["milestones_created"] == 10
    
    @patch('app.services.milestone_sync.sync_all_customer_milestones')
    def test_sync_api_partial_failure(self, mock_sync, client, app, sample_data):
        """Sync with partial failures should return 207."""
        mock_sync.return_value = {
            "success": False,
            "customers_synced": 0,
            "customers_failed": 3,
            "milestones_created": 0,
            "milestones_updated": 0,
            "milestones_deactivated": 0,
            "errors": ["Auth failed"],
            "duration_seconds": 1.0,
        }
        
        response = client.post('/api/milestone-tracker/sync')
        assert response.status_code == 207
    
    def test_tracker_page_has_sync_button(self, client, app, sample_data):
        """Tracker page should have a sync button."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'Sync from MSX' in response.data
    
    def test_tracker_page_has_filters(self, client, app, sample_data):
        """Tracker page should have filter controls."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'sellerFilter' in response.data
        assert b'statusFilter' in response.data
        assert b'areaFilter' in response.data
    
    def test_tracker_page_has_sortable_columns(self, client, app, sample_data):
        """Tracker page should have sortable column headers."""
        with app.app_context():
            from app.models import db, Milestone, User
            user = User.query.first()
            ms = Milestone(
                msx_milestone_id="sort-test-ms",
                url="https://sort-test.com",
                title="Sort Test",
                msx_status="On Track",
                customer_id=sample_data['customer1_id'],
                user_id=user.id,
            )
            db.session.add(ms)
            db.session.commit()

        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'sortTable' in response.data
        assert b'data-sort="customer"' in response.data
        assert b'data-sort="seller"' in response.data
        assert b'data-sort="status"' in response.data
        assert b'data-sort="due-date"' in response.data
        assert b'data-sort="monthly"' in response.data

        with app.app_context():
            from app.models import db, Milestone
            ms = Milestone.query.filter_by(msx_milestone_id="sort-test-ms").first()
            if ms:
                db.session.delete(ms)
                db.session.commit()


class TestMilestoneSyncDateParsing:
    """Test the date parsing utility in the sync service."""
    
    def test_parse_iso_date_with_z(self, app):
        """Should parse ISO 8601 date with Z suffix."""
        with app.app_context():
            from app.services.milestone_sync import _parse_msx_date
            result = _parse_msx_date("2026-06-30T00:00:00Z")
            assert result is not None
            assert result.year == 2026
            assert result.month == 6
            assert result.day == 30
    
    def test_parse_iso_date_without_z(self, app):
        """Should parse ISO 8601 date without Z suffix."""
        with app.app_context():
            from app.services.milestone_sync import _parse_msx_date
            result = _parse_msx_date("2026-03-15T00:00:00")
            assert result is not None
            assert result.year == 2026
            assert result.month == 3
    
    def test_parse_none_returns_none(self, app):
        """Should return None for None input."""
        with app.app_context():
            from app.services.milestone_sync import _parse_msx_date
            assert _parse_msx_date(None) is None
    
    def test_parse_empty_returns_none(self, app):
        """Should return None for empty string."""
        with app.app_context():
            from app.services.milestone_sync import _parse_msx_date
            assert _parse_msx_date("") is None
    
    def test_parse_invalid_returns_none(self, app):
        """Should return None for garbage input."""
        with app.app_context():
            from app.services.milestone_sync import _parse_msx_date
            assert _parse_msx_date("not-a-date") is None


class TestMilestoneTrackerNav:
    """Test that the milestone tracker is accessible from navigation."""
    
    def test_nav_has_milestone_tracker_link(self, client, app, sample_data):
        """Main nav should have a link to the milestone tracker."""
        response = client.get('/')
        assert response.status_code == 200
        assert b'milestone-tracker' in response.data
        assert b'Milestones' in response.data


class TestSyncCustomerEndpoint:
    """Test the single-customer sync endpoint."""
    
    @patch('app.services.milestone_sync.sync_customer_milestones')
    def test_sync_single_customer(self, mock_sync, client, app, sample_data):
        """Should sync milestones for a single customer."""
        # customer1 has tpid_url
        mock_sync.return_value = {
            "success": True,
            "created": 2,
            "updated": 1,
            "deactivated": 0,
            "error": "",
        }
        
        response = client.post(
            f'/api/milestone-tracker/sync-customer/{sample_data["customer1_id"]}'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
    
    def test_sync_customer_without_tpid_url(self, client, app, sample_data):
        """Should fail if customer has no tpid_url."""
        response = client.post(
            f'/api/milestone-tracker/sync-customer/{sample_data["customer2_id"]}'
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
    
    def test_sync_nonexistent_customer(self, client, app, sample_data):
        """Should return 404 for nonexistent customer."""
        response = client.post('/api/milestone-tracker/sync-customer/99999')
        assert response.status_code == 404


class TestSSESync:
    """Test the Server-Sent Events streaming sync."""

    def test_sse_event_format(self, app):
        """_sse_event should produce valid SSE format."""
        with app.app_context():
            from app.services.milestone_sync import _sse_event
            result = _sse_event('progress', {'current': 1, 'total': 5})
            assert result.startswith('event: progress\n')
            assert 'data: {' in result
            assert result.endswith('\n\n')

    def test_sse_event_json_payload(self, app):
        """_sse_event data field should be valid JSON."""
        import json
        with app.app_context():
            from app.services.milestone_sync import _sse_event
            result = _sse_event('complete', {'success': True, 'count': 42})
            data_line = [l for l in result.split('\n') if l.startswith('data: ')][0]
            payload = json.loads(data_line[6:])
            assert payload['success'] is True
            assert payload['count'] == 42

    @patch('app.services.milestone_sync.sync_customer_milestones')
    def test_stream_yields_start_progress_complete(self, mock_sync, app, sample_data):
        """Streaming sync should yield start, progress, and complete events."""
        import json
        mock_sync.return_value = {
            'success': True, 'created': 2, 'updated': 1, 'deactivated': 0, 'error': '',
        }

        with app.app_context():
            from app.services.milestone_sync import sync_all_customer_milestones_stream
            from app.models import User
            user = User.query.first()

            events = list(sync_all_customer_milestones_stream(user.id))

        # Parse events
        event_types = []
        for evt in events:
            for line in evt.split('\n'):
                if line.startswith('event: '):
                    event_types.append(line[7:])

        assert event_types[0] == 'start'
        assert 'progress' in event_types
        assert event_types[-1] == 'complete'

    def test_sync_api_sse_returns_event_stream(self, client, app, sample_data):
        """POST with Accept: text/event-stream should return SSE content type."""
        with patch('app.services.milestone_sync.sync_all_customer_milestones_stream') as mock_stream:
            mock_stream.return_value = iter([
                'event: start\ndata: {"total": 1}\n\n',
                'event: complete\ndata: {"success": true}\n\n',
            ])
            response = client.post(
                '/api/milestone-tracker/sync',
                headers={'Accept': 'text/event-stream'},
            )
            assert response.status_code == 200
            assert 'text/event-stream' in response.content_type

    def test_sync_api_json_fallback(self, client, app, sample_data):
        """POST without SSE accept header should return JSON."""
        with patch('app.services.milestone_sync.sync_all_customer_milestones') as mock_sync:
            mock_sync.return_value = {
                "success": True,
                "customers_synced": 1,
                "customers_failed": 0,
                "milestones_created": 3,
                "milestones_updated": 0,
                "milestones_deactivated": 0,
                "errors": [],
                "duration_seconds": 0.5,
            }
            response = client.post(
                '/api/milestone-tracker/sync',
                headers={'Accept': 'application/json'},
            )
            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

    def test_tracker_page_has_progress_bar_html(self, client, app, sample_data):
        """Tracker page should have the progress bar container."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'syncProgressBar' in response.data
        assert b'syncProgressWrap' in response.data

    def test_tracker_page_has_area_filter(self, client, app, sample_data):
        """Tracker page should have the area filter dropdown."""
        response = client.get('/milestone-tracker')
        assert response.status_code == 200
        assert b'areaFilter' in response.data


class TestFiscalYearFilter:
    """Tests for the fiscal-year date filter on milestone queries."""

    def _setup_mock_request(self, mock_request):
        """Configure mock _msx_request to return empty milestone response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'value': []}
        mock_request.return_value = mock_resp

    @patch('app.services.msx_api._msx_request')
    def test_fy_filter_builds_correct_odata(self, mock_request):
        """current_fy_only should add msp_milestonedate range to OData $filter."""
        from app.services.msx_api import get_milestones_by_account
        self._setup_mock_request(mock_request)

        get_milestones_by_account('acct-id', current_fy_only=True)

        url = mock_request.call_args[0][1]  # _msx_request('GET', url)
        assert 'msp_milestonedate ge' in url
        assert 'msp_milestonedate le' in url
        assert '-07-01' in url
        assert '-06-30' in url

    @patch('app.services.msx_api._msx_request')
    def test_fy_filter_disabled_by_default(self, mock_request):
        """Without current_fy_only, no date filter should be present."""
        from app.services.msx_api import get_milestones_by_account
        self._setup_mock_request(mock_request)

        get_milestones_by_account('acct-id')

        url = mock_request.call_args[0][1]
        # msp_milestonedate appears in $select but should NOT appear in $filter
        assert 'msp_milestonedate ge' not in url
        assert 'msp_milestonedate le' not in url

    @patch('app.services.msx_api._msx_request')
    def test_fy_boundary_second_half(self, mock_request):
        """In Oct 2025 (month >= 7), FY starts July 2025 and ends June 2026."""
        from app.services.msx_api import get_milestones_by_account
        self._setup_mock_request(mock_request)

        with patch('app.services.msx_api.dt') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2025, 10, 15)
            get_milestones_by_account('acct-id', current_fy_only=True)

        url = mock_request.call_args[0][1]
        assert '2025-07-01' in url
        assert '2026-06-30' in url

    @patch('app.services.msx_api._msx_request')
    def test_fy_boundary_first_half(self, mock_request):
        """In Mar 2026 (month < 7), FY starts July 2025 and ends June 2026."""
        from app.services.msx_api import get_milestones_by_account
        self._setup_mock_request(mock_request)

        with patch('app.services.msx_api.dt') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 3, 15)
            get_milestones_by_account('acct-id', current_fy_only=True)

        url = mock_request.call_args[0][1]
        assert '2025-07-01' in url
        assert '2026-06-30' in url
