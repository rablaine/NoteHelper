"""Tests for the MSX Workspace report page and API endpoints."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture
def msx_data(app, sample_data):
    """Create opportunity and milestone sample data for MSX workspace tests."""
    with app.app_context():
        from app.models import db, Opportunity, Milestone, Customer

        customer = Customer.query.get(sample_data['customer1_id'])

        opp1 = Opportunity(
            msx_opportunity_id='aaa-111-opp',
            opportunity_number='7-000000001',
            name='Big Cloud Deal',
            statecode=0,
            state='Open',
            status_reason='In Progress',
            estimated_value=500000,
            estimated_close_date='2026-06-30',
            owner_name='Alice Smith',
            on_deal_team=True,
            customer_id=customer.id,
            description='Moving workloads to Azure',
            customer_need='Modernize infrastructure',
            compete_threat='AWS',
            msx_url='https://microsoftsales.crm.dynamics.com/main.aspx?id=aaa-111-opp',
        )
        opp2 = Opportunity(
            msx_opportunity_id='bbb-222-opp',
            opportunity_number='7-000000002',
            name='Data Platform Initiative',
            statecode=0,
            state='Open',
            estimated_value=250000,
            owner_name='Bob Jones',
            on_deal_team=False,
            customer_id=customer.id,
        )
        db.session.add_all([opp1, opp2])
        db.session.flush()

        ms1 = Milestone(
            msx_milestone_id='ccc-333-ms',
            milestone_number='7-000000003',
            url='https://microsoftsales.crm.dynamics.com/main.aspx?id=ccc-333-ms',
            title='Azure Migration POC',
            msx_status='On Track',
            due_date=datetime(2026, 5, 15, tzinfo=timezone.utc),
            monthly_usage=10000,
            workload='Azure Core',
            owner_name='Alice Smith',
            on_my_team=True,
            customer_id=customer.id,
            opportunity_id=opp1.id,
        )
        ms2 = Milestone(
            msx_milestone_id='ddd-444-ms',
            milestone_number='7-000000004',
            url='https://microsoftsales.crm.dynamics.com/main.aspx?id=ddd-444-ms',
            title='Synapse Analytics Pilot',
            msx_status='At Risk',
            due_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
            monthly_usage=5000,
            workload='Azure Data',
            owner_name='Bob Jones',
            on_my_team=False,
            customer_id=customer.id,
            opportunity_id=opp1.id,
        )
        db.session.add_all([ms1, ms2])
        db.session.commit()

        return {
            'opp1_id': opp1.id,
            'opp2_id': opp2.id,
            'ms1_id': ms1.id,
            'ms2_id': ms2.id,
            'customer_id': customer.id,
        }


# ---- Page load tests ----

def test_msx_workspace_page_loads(client, sample_data):
    """MSX Workspace report page loads without errors."""
    response = client.get('/reports/msx-workspace')
    assert response.status_code == 200
    assert b'MSX Workspace' in response.data


def test_msx_workspace_shows_customers_in_filter(client, sample_data):
    """Customer dropdown is populated in the MSX Workspace."""
    response = client.get('/reports/msx-workspace')
    assert response.status_code == 200
    assert b'Acme Corp' in response.data


def test_msx_workspace_shows_task_categories(client, sample_data):
    """Task category dropdown is populated."""
    response = client.get('/reports/msx-workspace')
    assert response.status_code == 200
    assert b'Architecture Design Session' in response.data
    assert b'Workshop' in response.data


# ---- Opportunity API tests ----

def test_opportunities_api_returns_data(client, msx_data):
    """Opportunities API returns opportunity data as JSON."""
    response = client.get('/api/reports/msx-workspace/opportunities')
    assert response.status_code == 200
    data = response.get_json()
    assert 'opportunities' in data
    assert data['count'] == 2


def test_opportunities_api_filter_by_customer(client, msx_data):
    """Opportunities API filters by customer_id."""
    response = client.get(
        f'/api/reports/msx-workspace/opportunities?customer_id={msx_data["customer_id"]}'
    )
    data = response.get_json()
    assert data['count'] == 2
    assert all(o['customer_id'] == msx_data['customer_id'] for o in data['opportunities'])


def test_opportunities_api_filter_by_status_open(client, msx_data):
    """Opportunities API filters by open status."""
    response = client.get('/api/reports/msx-workspace/opportunities?status=open')
    data = response.get_json()
    assert data['count'] == 2  # Both are open


def test_opportunities_api_filter_by_team(client, msx_data):
    """Opportunities API filters by deal team membership."""
    response = client.get('/api/reports/msx-workspace/opportunities?team=on')
    data = response.get_json()
    assert data['count'] == 1
    assert data['opportunities'][0]['name'] == 'Big Cloud Deal'


def test_opportunities_api_search(client, msx_data):
    """Opportunities API search by name."""
    response = client.get('/api/reports/msx-workspace/opportunities?search=Data%20Platform')
    data = response.get_json()
    assert data['count'] == 1
    assert data['opportunities'][0]['name'] == 'Data Platform Initiative'


def test_opportunities_api_returns_all_fields(client, msx_data):
    """Opportunity JSON includes all expected fields."""
    response = client.get('/api/reports/msx-workspace/opportunities?team=on')
    data = response.get_json()
    opp = data['opportunities'][0]
    assert opp['msx_id'] == 'aaa-111-opp'
    assert opp['number'] == '7-000000001'
    assert opp['estimated_value'] == 500000
    assert opp['on_deal_team'] is True
    assert opp['customer_name'] == 'Acme Corp'
    assert opp['description'] == 'Moving workloads to Azure'
    assert opp['compete_threat'] == 'AWS'


# ---- Milestone API tests ----

def test_milestones_api_returns_data(client, msx_data):
    """Milestones API returns milestone data as JSON."""
    response = client.get('/api/reports/msx-workspace/milestones')
    assert response.status_code == 200
    data = response.get_json()
    assert 'milestones' in data
    assert data['count'] == 2


def test_milestones_api_filter_by_status(client, msx_data):
    """Milestones API filters by status."""
    response = client.get('/api/reports/msx-workspace/milestones?status=On%20Track')
    data = response.get_json()
    assert data['count'] == 1
    assert data['milestones'][0]['title'] == 'Azure Migration POC'


def test_milestones_api_filter_by_team(client, msx_data):
    """Milestones API filters by team membership."""
    response = client.get('/api/reports/msx-workspace/milestones?team=on')
    data = response.get_json()
    assert data['count'] == 1
    assert data['milestones'][0]['on_my_team'] is True


def test_milestones_api_filter_by_opportunity(client, msx_data):
    """Milestones API filters by opportunity_id."""
    response = client.get(
        f'/api/reports/msx-workspace/milestones?opportunity_id={msx_data["opp1_id"]}'
    )
    data = response.get_json()
    assert data['count'] == 2  # Both milestones are under opp1


def test_milestones_api_search(client, msx_data):
    """Milestones API search by title."""
    response = client.get('/api/reports/msx-workspace/milestones?search=Synapse')
    data = response.get_json()
    assert data['count'] == 1
    assert data['milestones'][0]['title'] == 'Synapse Analytics Pilot'


def test_milestones_api_returns_all_fields(client, msx_data):
    """Milestone JSON includes all expected fields."""
    response = client.get('/api/reports/msx-workspace/milestones?team=on')
    data = response.get_json()
    ms = data['milestones'][0]
    assert ms['msx_id'] == 'ccc-333-ms'
    assert ms['number'] == '7-000000003'
    assert ms['status'] == 'On Track'
    assert ms['due_date'] == '2026-05-15'
    assert ms['monthly_usage'] == 10000
    assert ms['workload'] == 'Azure Core'
    assert ms['on_my_team'] is True
    assert ms['opportunity_name'] == 'Big Cloud Deal'


def test_milestones_api_multiple_statuses(client, msx_data):
    """Milestones API accepts comma-separated statuses."""
    response = client.get('/api/reports/msx-workspace/milestones?status=On%20Track,At%20Risk')
    data = response.get_json()
    assert data['count'] == 2


# ---- Tasks API tests ----

@patch('app.services.msx_api.get_tasks_for_milestones')
def test_tasks_api_returns_data(mock_get_tasks, client, msx_data):
    """Tasks API fetches from MSX and returns task data."""
    mock_get_tasks.return_value = {
        'success': True,
        'tasks': [
            {
                'task_id': 'task-001',
                'subject': 'Run POC demo',
                'task_category': 861980002,
                'task_category_name': 'Demo',
                'is_hok': True,
                'due_date': '2026-05-01T00:00:00Z',
                'milestone_msx_id': 'ccc-333-ms',
                'task_url': 'https://msxurl/task-001',
            },
        ],
    }
    response = client.get('/api/reports/msx-workspace/tasks?milestone_ids=ccc-333-ms')
    data = response.get_json()
    assert data['count'] == 1
    assert data['tasks'][0]['subject'] == 'Run POC demo'
    mock_get_tasks.assert_called_once_with(['ccc-333-ms'])


@patch('app.services.msx_api.get_tasks_for_milestones')
def test_tasks_api_empty_when_no_ids(mock_get_tasks, client, msx_data):
    """Tasks API returns empty when no milestone_ids provided."""
    response = client.get('/api/reports/msx-workspace/tasks')
    data = response.get_json()
    assert data['count'] == 0
    mock_get_tasks.assert_not_called()


# ---- Task CRUD route tests (in MSX blueprint) ----

@patch('app.services.msx_api.update_task')
def test_update_task_route(mock_update, client, msx_data):
    """PATCH /api/msx/task/<id>/update calls update_task."""
    mock_update.return_value = {'success': True}
    response = client.patch(
        '/api/msx/task/task-001/update',
        json={'subject': 'Updated subject'},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    mock_update.assert_called_once_with('task-001', {'subject': 'Updated subject'})


@patch('app.services.msx_api.close_task')
def test_close_task_route(mock_close, client, msx_data):
    """POST /api/msx/task/<id>/close calls close_task."""
    mock_close.return_value = {'success': True}
    response = client.post('/api/msx/task/task-001/close')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    mock_close.assert_called_once_with('task-001')


@patch('app.services.msx_api.delete_task')
def test_delete_task_route(mock_delete, client, msx_data):
    """DELETE /api/msx/task/<id>/delete calls delete_task."""
    mock_delete.return_value = {'success': True}
    response = client.delete('/api/msx/task/task-001/delete')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    mock_delete.assert_called_once_with('task-001')


@patch('app.services.msx_api.update_milestone')
def test_update_milestone_route(mock_update, client, msx_data):
    """PATCH /api/msx/milestone/<id>/update calls update_milestone."""
    mock_update.return_value = {'success': True}
    response = client.patch(
        '/api/msx/milestone/ccc-333-ms/update',
        json={'msp_milestonedate': '2026-06-01'},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    mock_update.assert_called_once_with('ccc-333-ms', {'msp_milestonedate': '2026-06-01'})


# ---- Reports hub includes MSX Workspace ----

def test_reports_hub_includes_msx_workspace(client, sample_data):
    """Reports hub page lists the MSX Workspace report."""
    response = client.get('/reports')
    assert response.status_code == 200
    assert b'MSX Workspace' in response.data
    assert b'msx-workspace' in response.data


# ---- SalesIQ tool coverage ----

def test_salesiq_tools_include_msx_workspace(app):
    """SalesIQ tool registry includes MSX workspace tools."""
    with app.app_context():
        from app.services.salesiq_tools import TOOLS
        tool_names = {t['name'] for t in TOOLS}
        assert 'get_msx_workspace_opportunities' in tool_names
        assert 'get_msx_workspace_milestones' in tool_names
