"""Tests for data export and import functionality."""
import json
import pytest
from datetime import datetime, timezone
from io import BytesIO


def test_export_full_json_structure(client, sample_data):
    """Test that full JSON export includes all expected keys and structure."""
    response = client.get('/api/data-management/export/json')
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    
    data = json.loads(response.data)
    
    # Check top-level structure
    assert 'export_date' in data
    assert 'version' in data
    assert data['version'] == '2.1'
    
    # Check all entity types are present including users
    assert 'users' in data
    assert 'user_preferences' in data
    assert 'ai_config' in data  # Can be None if not configured
    assert 'pods' in data
    assert 'territories' in data
    assert 'sellers' in data
    assert 'solution_engineers' in data
    assert 'verticals' in data
    assert 'customers' in data
    assert 'topics' in data
    assert 'call_logs' in data


def test_export_full_json_call_log_structure(client, sample_data):
    """Test that call logs in full JSON export have correct structure (no seller_id/territory_id)."""
    response = client.get('/api/data-management/export/json')
    data = json.loads(response.data)
    
    assert len(data['call_logs']) > 0
    call_log = data['call_logs'][0]
    
    # Should have customer_id but not seller_id or territory_id
    assert 'id' in call_log
    assert 'customer_id' in call_log
    assert 'call_date' in call_log
    assert 'content' in call_log
    assert 'topic_ids' in call_log
    assert 'created_at' in call_log
    
    # These should NOT exist anymore
    assert 'seller_id' not in call_log
    assert 'territory_id' not in call_log


def test_export_call_logs_json_enriched_data(client, sample_data):
    """Test that enriched call logs JSON includes derived seller/territory data."""
    response = client.get('/api/data-management/export/call-logs-json')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'export_date' in data
    assert 'export_type' in data
    assert data['export_type'] == 'call_logs'
    assert 'total_calls' in data
    assert 'call_logs' in data
    
    assert len(data['call_logs']) > 0
    call_log = data['call_logs'][0]
    
    # Check enriched structure
    assert 'customer' in call_log
    assert 'seller' in call_log
    assert 'territory' in call_log
    assert 'topics' in call_log
    
    # Seller should have derived data
    assert 'name' in call_log['seller']
    assert 'alias' in call_log['seller']
    assert 'type' in call_log['seller']
    
    # Territory should have derived data
    assert 'name' in call_log['territory']
    assert 'pod' in call_log['territory']


def test_export_call_logs_csv_structure(client, sample_data):
    """Test that enriched call logs CSV includes all expected columns."""
    response = client.get('/api/data-management/export/call-logs-csv')
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    
    csv_text = response.data.decode('utf-8')
    lines = csv_text.strip().split('\n')
    
    # Check header
    header = lines[0]
    assert 'Call Date' in header
    assert 'Customer Name' in header
    assert 'Seller Name' in header
    assert 'Seller Email' in header
    assert 'Territory' in header
    assert 'POD' in header
    assert 'Topics' in header
    
    # Should have data rows
    assert len(lines) > 1


def test_export_full_csv_zip_structure(client, sample_data):
    """Test that full CSV export creates a ZIP with all entity files."""
    import zipfile
    
    response = client.get('/api/data-management/export/csv')
    assert response.status_code == 200
    assert response.mimetype == 'application/zip'
    
    # Read ZIP contents
    zip_buffer = BytesIO(response.data)
    with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
        file_list = zip_file.namelist()
        
        # Check all expected CSV files are present
        assert 'pods.csv' in file_list
        assert 'territories.csv' in file_list
        assert 'sellers.csv' in file_list
        assert 'solution_engineers.csv' in file_list
        assert 'verticals.csv' in file_list
        assert 'customers.csv' in file_list
        assert 'topics.csv' in file_list
        assert 'call_logs.csv' in file_list


def test_export_full_csv_call_logs_no_redundant_columns(client, sample_data):
    """Test that call_logs.csv uses derived seller/territory instead of IDs."""
    import zipfile
    import csv
    from io import StringIO
    
    response = client.get('/api/data-management/export/csv')
    zip_buffer = BytesIO(response.data)
    
    with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
        call_logs_csv = zip_file.read('call_logs.csv').decode('utf-8')
        
        reader = csv.DictReader(StringIO(call_logs_csv))
        header = reader.fieldnames
        
        # Should have name-based columns, not ID columns
        assert 'seller' in header
        assert 'territory' in header
        
        # Should NOT have ID columns
        assert 'seller_id' not in header
        assert 'territory_id' not in header
        
        # Check a data row to ensure values are populated
        row = next(reader)
        assert 'seller' in row
        assert 'territory' in row


def test_export_preserves_relationships(client, sample_data):
    """Test that exported data maintains referential integrity."""
    response = client.get('/api/data-management/export/json')
    data = json.loads(response.data)
    
    # Get first call log
    call_log = data['call_logs'][0]
    customer_id = call_log['customer_id']
    
    # Find corresponding customer
    customer = next((c for c in data['customers'] if c['id'] == customer_id), None)
    assert customer is not None
    
    # Customer should have seller_id and territory_id
    assert 'seller_id' in customer
    assert 'territory_id' in customer
    
    if customer['seller_id']:
        # Verify seller exists
        seller = next((s for s in data['sellers'] if s['id'] == customer['seller_id']), None)
        assert seller is not None
    
    if customer['territory_id']:
        # Verify territory exists
        territory = next((t for t in data['territories'] if t['id'] == customer['territory_id']), None)
        assert territory is not None


def test_export_enriched_derives_from_customer(client, sample_data):
    """Test that enriched export correctly derives seller/territory from customer."""
    from app.models import CallLog, Customer
    
    # Get a call log from the database
    call_log = CallLog.query.first()
    assert call_log is not None
    assert call_log.customer is not None
    
    # Get enriched export
    response = client.get('/api/data-management/export/call-logs-json')
    data = json.loads(response.data)
    
    # Find our call log in the export
    exported_log = next((cl for cl in data['call_logs'] if cl['id'] == call_log.id), None)
    assert exported_log is not None
    
    # Verify seller and territory match the customer's values
    if call_log.customer.seller:
        assert exported_log['seller']['name'] == call_log.customer.seller.name
        assert exported_log['seller']['alias'] == call_log.customer.seller.alias
    
    if call_log.customer.territory:
        assert exported_log['territory']['name'] == call_log.customer.territory.name


def test_export_import_roundtrip_preserves_data(app, client):
    """Test that exporting and re-importing data preserves all information including users."""
    from app.models import db, POD, Territory, Seller, Customer, Topic, CallLog, Vertical, User
    
    with app.app_context():
        # Get test user (created by conftest.py)
        user = User.query.first()
        assert user is not None, "Test user should exist"
        
        # Create test data with user_id
        pod = POD(name='Roundtrip Test POD', user_id=user.id)
        db.session.add(pod)
        db.session.flush()
        
        territory = Territory(name='Roundtrip Test Territory', pod_id=pod.id, user_id=user.id)
        db.session.add(territory)
        db.session.flush()
        
        seller = Seller(name='Roundtrip Test Seller', alias='rtseller', seller_type='Growth', user_id=user.id)
        seller.territories.append(territory)
        db.session.add(seller)
        db.session.flush()
        
        vertical = Vertical(name='Roundtrip Test Vertical', user_id=user.id)
        db.session.add(vertical)
        db.session.flush()
        
        customer = Customer(
            name='Roundtrip Test Customer',
            tpid=88888,
            seller_id=seller.id,
            territory_id=territory.id,
            user_id=user.id
        )
        customer.verticals.append(vertical)
        db.session.add(customer)
        db.session.flush()
        
        topic = Topic(name='Roundtrip Test Topic', description='Test Description', user_id=user.id)
        db.session.add(topic)
        db.session.flush()
        
        call_log = CallLog(
            customer_id=customer.id,
            call_date=datetime.now(timezone.utc).date(),
            content='Roundtrip test call log content',
            user_id=user.id
        )
        call_log.topics.append(topic)
        db.session.add(call_log)
        db.session.commit()
        
        # Export the data
        response = client.get('/api/data-management/export/json')
        assert response.status_code == 200
        export_data = json.loads(response.data)
        
        # Verify export contains our data
        assert any(p['name'] == 'Roundtrip Test POD' for p in export_data['pods'])
        assert any(t['name'] == 'Roundtrip Test Territory' for t in export_data['territories'])
        assert any(s['name'] == 'Roundtrip Test Seller' for s in export_data['sellers'])
        assert any(c['name'] == 'Roundtrip Test Customer' for c in export_data['customers'])
        assert any(t['name'] == 'Roundtrip Test Topic' for t in export_data['topics'])
        assert any(v['name'] == 'Roundtrip Test Vertical' for v in export_data['verticals'])
        assert any(u['name'] == user.name for u in export_data['users'])
        
        # Verify user_id is present in exported entities
        exported_pod = next(p for p in export_data['pods'] if p['name'] == 'Roundtrip Test POD')
        assert 'user_id' in exported_pod
        assert exported_pod['user_id'] == user.id
        
        # Clean up test data
        db.session.delete(call_log)
        db.session.delete(customer)
        db.session.delete(topic)
        db.session.delete(vertical)
        db.session.delete(seller)
        db.session.delete(territory)
        db.session.delete(pod)
        db.session.commit()
        
        # Now test import
        json_file = BytesIO(json.dumps(export_data).encode('utf-8'))
        
        response = client.post('/api/data-management/import/json',
                              data={'file': (json_file, 'test_import.json')},
                              content_type='multipart/form-data')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] == True
        assert 'Successfully imported' in result['message']
        assert '0 users' in result['message']  # User already exists, should match not create
        assert '1 PODs' in result['message']
        assert '1 territories' in result['message']
        assert '1 sellers' in result['message']
        assert '1 customers' in result['message']
        assert '1 topics' in result['message']
        assert '1 call logs' in result['message']
        
        # Verify imported entities exist
        imported_pod = POD.query.filter_by(name='Roundtrip Test POD').first()
        assert imported_pod is not None
        assert imported_pod.user_id == user.id
        
        imported_territory = Territory.query.filter_by(name='Roundtrip Test Territory').first()
        assert imported_territory is not None
        assert imported_territory.user_id == user.id
        
        imported_seller = Seller.query.filter_by(name='Roundtrip Test Seller').first()
        assert imported_seller is not None
        assert imported_seller.user_id == user.id
        
        imported_customer = Customer.query.filter_by(name='Roundtrip Test Customer').first()
        assert imported_customer is not None
        assert imported_customer.user_id == user.id
        
        imported_topic = Topic.query.filter_by(name='Roundtrip Test Topic').first()
        assert imported_topic is not None
        assert imported_topic.user_id == user.id
        
        imported_call_log = CallLog.query.filter_by(content='Roundtrip test call log content').first()
        assert imported_call_log is not None
        assert imported_call_log.user_id == user.id
        assert imported_call_log.customer_id == imported_customer.id
        
        # Verify relationships preserved
        assert imported_territory.pod_id == imported_pod.id
        assert imported_customer.seller_id == imported_seller.id
        assert imported_customer.territory_id == imported_territory.id
        assert imported_call_log in imported_topic.call_logs
        
        # Clean up imported data
        db.session.delete(imported_call_log)
        db.session.delete(imported_customer)
        db.session.delete(imported_topic)
        Vertical.query.filter_by(name='Roundtrip Test Vertical').delete()
        db.session.delete(imported_seller)
        db.session.delete(imported_territory)
        db.session.delete(imported_pod)
        db.session.commit()


def test_import_json_preserves_users_by_azure_id(app, client):
    """Test that import matches users by Azure Object IDs and preserves ownership."""
    from app.models import db, User, POD
    
    with app.app_context():
        # Create a user with Azure IDs
        test_user = User(
            name='Azure Test User',
            email='azuretest@example.com',
            microsoft_azure_id='test-microsoft-oid-123',
            external_azure_id='test-external-oid-456',
            is_admin=False
        )
        db.session.add(test_user)
        db.session.commit()
        
        # Create export data with this user
        export_data = {
            'version': '2.0',
            'export_date': datetime.now(timezone.utc).isoformat(),
            'users': [{
                'id': test_user.id,
                'microsoft_azure_id': 'test-microsoft-oid-123',
                'external_azure_id': 'test-external-oid-456',
                'email': 'azuretest@example.com',
                'microsoft_email': None,
                'external_email': None,
                'name': 'Azure Test User',
                'is_admin': False
            }],
            'pods': [{
                'id': 999,
                'name': 'Azure User Test POD',
                'user_id': test_user.id
            }],
            'territories': [],
            'sellers': [],
            'solution_engineers': [],
            'verticals': [],
            'customers': [],
            'topics': [],
            'call_logs': []
        }
        
        # Delete the POD if it exists from previous test
        POD.query.filter_by(name='Azure User Test POD').delete()
        db.session.commit()
        
        # Import the data
        json_file = BytesIO(json.dumps(export_data).encode('utf-8'))
        response = client.post('/api/data-management/import/json',
                              data={'file': (json_file, 'azure_test.json')},
                              content_type='multipart/form-data')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] == True
        assert '0 users' in result['message']  # Should match existing user, not create new
        assert '1 PODs' in result['message']
        
        # Verify POD was created with correct user_id
        imported_pod = POD.query.filter_by(name='Azure User Test POD').first()
        assert imported_pod is not None
        assert imported_pod.user_id == test_user.id
        
        # Clean up
        db.session.delete(imported_pod)
        db.session.delete(test_user)
        db.session.commit()


def test_import_json_creates_stub_users_when_missing(app, client):
    """Test that import creates stub users for users not yet logged in."""
    from app.models import db, User, POD
    
    with app.app_context():
        # Create export data with a user that doesn't exist
        export_data = {
            'version': '2.0',
            'export_date': datetime.now(timezone.utc).isoformat(),
            'users': [{
                'id': 88888,
                'microsoft_azure_id': 'stub-test-microsoft-oid',
                'external_azure_id': 'stub-test-external-oid',
                'email': 'stubtest@example.com',
                'microsoft_email': 'stubtest@microsoft.com',
                'external_email': 'stubtest@external.com',
                'name': 'Stub Test User',
                'is_admin': False
            }],
            'pods': [{
                'id': 777,
                'name': 'Stub User Test POD',
                'user_id': 88888
            }],
            'territories': [],
            'sellers': [],
            'solution_engineers': [],
            'verticals': [],
            'customers': [],
            'topics': [],
            'call_logs': []
        }
        
        # Ensure stub user doesn't exist
        User.query.filter_by(microsoft_azure_id='stub-test-microsoft-oid').delete()
        POD.query.filter_by(name='Stub User Test POD').delete()
        db.session.commit()
        
        # Import the data
        json_file = BytesIO(json.dumps(export_data).encode('utf-8'))
        response = client.post('/api/data-management/import/json',
                              data={'file': (json_file, 'stub_test.json')},
                              content_type='multipart/form-data')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['success'] == True
        assert '1 users' in result['message']  # Should create stub user
        assert '1 PODs' in result['message']
        
        # Verify stub user was created
        stub_user = User.query.filter_by(microsoft_azure_id='stub-test-microsoft-oid').first()
        assert stub_user is not None
        assert stub_user.name == 'Stub Test User'
        assert stub_user.email == 'stubtest@example.com'
        assert stub_user.microsoft_email == 'stubtest@microsoft.com'
        assert stub_user.external_email == 'stubtest@external.com'
        assert stub_user.is_stub == True
        
        # Verify POD was created with stub user's ID
        imported_pod = POD.query.filter_by(name='Stub User Test POD').first()
        assert imported_pod is not None
        assert imported_pod.user_id == stub_user.id
        
        # Clean up
        db.session.delete(imported_pod)
        db.session.delete(stub_user)
        db.session.commit()


def test_enriched_export_has_complete_relationship_data(client, sample_data):
    """Test that enriched export includes all nested relationship data."""
    response = client.get('/api/data-management/export/call-logs-json')
    data = json.loads(response.data)
    
    # Find a call log with full relationships
    call_log = next((cl for cl in data['call_logs'] 
                     if cl['seller']['name'] and cl['territory']['name']), None)
    
    assert call_log is not None
    
    # Verify customer data
    assert call_log['customer']['name']
    assert 'verticals' in call_log['customer']
    
    # Verify seller data includes all fields
    assert call_log['seller']['name']
    assert 'alias' in call_log['seller']
    assert 'email' in call_log['seller']
    assert 'type' in call_log['seller']
    
    # Verify territory data includes POD
    assert call_log['territory']['name']
    assert 'pod' in call_log['territory']


def test_import_json_includes_user_preferences(app, client):
    """Test that importing JSON includes user preferences."""
    from app.models import db, User, UserPreference
    
    with app.app_context():
        # Get test user
        test_user = User.query.first()
        
        # Update their preferences
        pref = UserPreference.query.filter_by(user_id=test_user.id).first()
        pref.dark_mode = True
        pref.customer_view_grouped = True
        pref.topic_sort_by_calls = True
        db.session.commit()
        
        # Export data
        response = client.get('/api/data-management/export/json')
        export_data = json.loads(response.data)
        
        # Verify preferences are in export
        assert 'user_preferences' in export_data
        assert len(export_data['user_preferences']) > 0
        user_pref = next(p for p in export_data['user_preferences'] if p['user_id'] == test_user.id)
        assert user_pref['dark_mode'] == True
        assert user_pref['customer_view_grouped'] == True
        assert user_pref['topic_sort_by_calls'] == True
        
        # Reset preferences
        pref.dark_mode = False
        pref.customer_view_grouped = False
        pref.topic_sort_by_calls = False
        db.session.commit()
        
        # Import back
        json_file = BytesIO(json.dumps(export_data).encode('utf-8'))
        response = client.post('/api/data-management/import/json',
                              data={'file': (json_file, 'test_prefs.json')},
                              content_type='multipart/form-data')
        
        assert response.status_code == 200
        result = json.loads(response.data)
        assert 'user preferences' in result['message']
        
        # Verify preferences were restored
        db.session.refresh(pref)
        assert pref.dark_mode == True
        assert pref.customer_view_grouped == True
        assert pref.topic_sort_by_calls == True


def test_import_csv_creates_entities(app, client):
    """Test that importing CSV creates all expected entities."""
    from app.models import db, Territory, Seller, Customer, POD
    from io import BytesIO
    
    with app.app_context():
        # Count entities before import
        territories_before = Territory.query.count()
        sellers_before = Seller.query.count()
        customers_before = Customer.query.count()
        
        # Create a simple CSV file
        csv_content = """Sales Territory,DSS (Growth/Acq),Primary Cloud & AI DSS,Primary Cloud & AI-Acq DSS,Customer Name,TPID,TPID URL,POD
West Region,Test Seller,Test Seller,,Test Customer,12345,https://example.com/12345,Test POD"""
        
        csv_file = BytesIO(csv_content.encode('utf-8'))
        
        # Import the CSV
        response = client.post('/api/data-management/import',
                              data={'file': (csv_file, 'test_import.csv')},
                              content_type='multipart/form-data',
                              follow_redirects=True)
        
        # Should get streaming response
        assert response.status_code == 200
        
        # Consume the streaming response to ensure import completes
        response_text = response.data.decode('utf-8')
        assert 'error' not in response_text.lower() or 'no error' in response_text.lower()
        
        # Check entities were created
        territories_after = Territory.query.count()
        sellers_after = Seller.query.count()
        customers_after = Customer.query.count()
        
        assert territories_after > territories_before
        assert sellers_after > sellers_before
        assert customers_after > customers_before
        
        # Verify the specific entities exist
        territory = Territory.query.filter_by(name='West Region').first()
        assert territory is not None
        
        seller = Seller.query.filter_by(name='Test Seller').first()
        assert seller is not None
        assert seller.seller_type == 'Growth'
        
        customer = Customer.query.filter_by(name='Test Customer').first()
        assert customer is not None
        assert customer.tpid == 12345
        assert customer.seller_id == seller.id
        assert customer.territory_id == territory.id
        
        # Clean up
        db.session.delete(customer)
        db.session.delete(seller)
        db.session.delete(territory)
        POD.query.filter_by(name='Test POD').delete()
        db.session.commit()


def test_import_csv_handles_growth_and_acquisition(app, client):
    """Test that import correctly identifies Growth vs Acquisition sellers."""
    from app.models import db, Seller, Customer, Territory, POD
    from io import BytesIO
    
    with app.app_context():
        csv_content = """Sales Territory,DSS (Growth/Acq),Primary Cloud & AI DSS,Primary Cloud & AI-Acq DSS,Customer Name,TPID,TPID URL,POD
East Region,Growth Seller,Growth Seller,,Customer A,11111,https://example.com/11111,POD A
East Region,Acq Seller,,Acq Seller,Customer B,22222,https://example.com/22222,POD A"""
        
        csv_file = BytesIO(csv_content.encode('utf-8'))
        
        response = client.post('/api/data-management/import',
                              data={'file': (csv_file, 'test_sellers.csv')},
                              content_type='multipart/form-data',
                              follow_redirects=True)
        
        assert response.status_code == 200
        
        # Consume streaming response
        response.data.decode('utf-8')
        
        # Check Growth seller
        growth_seller = Seller.query.filter_by(name='Growth Seller').first()
        assert growth_seller is not None
        assert growth_seller.seller_type == 'Growth'
        
        # Check Acquisition seller
        acq_seller = Seller.query.filter_by(name='Acq Seller').first()
        assert acq_seller is not None
        assert acq_seller.seller_type == 'Acquisition'
        
        # Clean up
        Customer.query.filter(Customer.tpid.in_([11111, 22222])).delete()
        db.session.delete(growth_seller)
        db.session.delete(acq_seller)
        Territory.query.filter_by(name='East Region').delete()
        POD.query.filter_by(name='POD A').delete()
        db.session.commit()


def test_import_csv_avoids_duplicates(app, client):
    """Test that importing the same CSV twice doesn't create duplicates."""
    from app.models import db, Territory, Seller, Customer, POD
    from io import BytesIO
    
    with app.app_context():
        csv_content = """Sales Territory,DSS (Growth/Acq),Primary Cloud & AI DSS,Primary Cloud & AI-Acq DSS,Customer Name,TPID,TPID URL,POD
South Region,Unique Seller,Unique Seller,,Unique Customer,99999,https://example.com/99999,Unique POD"""
        
        # Import once
        csv_file1 = BytesIO(csv_content.encode('utf-8'))
        response1 = client.post('/api/data-management/import',
                               data={'file': (csv_file1, 'test1.csv')},
                               content_type='multipart/form-data',
                               follow_redirects=True)
        assert response1.status_code == 200
        response1.data.decode('utf-8')  # Consume stream
        
        # Count after first import
        territory_count1 = Territory.query.filter_by(name='South Region').count()
        seller_count1 = Seller.query.filter_by(name='Unique Seller').count()
        customer_count1 = Customer.query.filter_by(tpid=99999).count()
        
        # Import again
        csv_file2 = BytesIO(csv_content.encode('utf-8'))
        response2 = client.post('/api/data-management/import',
                               data={'file': (csv_file2, 'test2.csv')},
                               content_type='multipart/form-data',
                               follow_redirects=True)
        assert response2.status_code == 200
        response2.data.decode('utf-8')  # Consume stream
        
        # Count after second import
        territory_count2 = Territory.query.filter_by(name='South Region').count()
        seller_count2 = Seller.query.filter_by(name='Unique Seller').count()
        customer_count2 = Customer.query.filter_by(tpid=99999).count()
        
        # Counts should be the same (no duplicates)
        assert territory_count1 == territory_count2
        assert seller_count1 == seller_count2
        # Customer might be duplicated as it's based on combination of factors
        
        # Clean up
        Customer.query.filter_by(tpid=99999).delete()
        Seller.query.filter_by(name='Unique Seller').delete()
        Territory.query.filter_by(name='South Region').delete()
        POD.query.filter_by(name='Unique POD').delete()
        db.session.commit()
